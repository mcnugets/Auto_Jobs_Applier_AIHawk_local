"""Monitor Telegram channels for Python job postings."""
import asyncio
import logging
from typing import List, Dict
from telethon import TelegramClient, events
from telethon.tl.types import Message

from .config import API_ID, API_HASH, PHONE_NUMBER, SESSION_PATH, CHANNELS, PYTHON_KEYWORDS
from .config import GEMINI_API_KEY
from .database import JobDatabase
from .utils import match_python_keywords, extract_contact_info, extract_job_title, has_website_application, is_title_incorrect
from .gemini_job_processor import process_job_batch

# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler('job_monitor.log'),
#         logging.StreamHandler()
#     ]
# )
logger = logging.getLogger(__name__)


class JobMonitor:
    """Monitors Telegram channels for job postings."""
    
    def __init__(self, db: JobDatabase, batch_size: int = 30, flush_interval_seconds: int = 60):
        """Initialize the job monitor.
        
        Args:
            db: JobDatabase instance
            batch_size: Max number of jobs to collect before processing with Gemini
            flush_interval_seconds: Flush the current batch every N seconds (so < batch_size still gets processed)
        """
        self.db = db
        self.client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds
        self.job_batch: List[Dict] = []  # Buffer for collecting jobs before processing
        self._flush_task: asyncio.Task | None = None

    async def _periodic_flush(self):
        """Flush batch periodically so we don't wait forever to hit batch_size."""
        while True:
            await asyncio.sleep(self.flush_interval_seconds)
            if self.job_batch:
                logger.info(
                    f"Periodic flush: processing partial batch of {len(self.job_batch)} jobs "
                    f"(max batch_size={self.batch_size})"
                )
                await self.process_batch()
    
    async def process_batch(self):
        """Process collected job batch with Gemini and save to database."""
        if not self.job_batch:
            return
        
        if not GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not configured, skipping batch processing")
            self.job_batch.clear()
            return
        
        try:
            logger.info(f"Processing batch of {len(self.job_batch)} jobs with Gemini...")
            
            # Process batch with Gemini
            processed_results = await process_job_batch(self.job_batch)
            
            if not processed_results or len(processed_results) != len(self.job_batch):
                logger.warning(f"Gemini returned {len(processed_results) if processed_results else 0} results, expected {len(self.job_batch)}")
                self.job_batch.clear()
                return
            
            # Save processed jobs to database
            saved_count = 0
            skipped_count = 0
            skip_reasons = {
                "not_python_job": 0,
                "no_keywords": 0,
                "website_application": 0,
                "no_telegram_contact": 0,
                "already_in_db": 0,
                "db_insert_failed": 0,
            }
            
            for i, processed_data in enumerate(processed_results):
                original_job = self.job_batch[i]
                job_id = original_job['job_id']
                
                # Check if it's a Python job
                if not processed_data.is_python_job:
                    skipped_count += 1
                    skip_reasons["not_python_job"] += 1
                    continue
                
                if not processed_data.matched_keywords:
                    skipped_count += 1
                    skip_reasons["no_keywords"] += 1
                    continue
                
                if processed_data.requires_website_application:
                    skipped_count += 1
                    skip_reasons["website_application"] += 1
                    continue
                
                # Skip if no Telegram contact
                contact_info = processed_data.contact_info
                if not contact_info or not contact_info.startswith('@'):
                    skipped_count += 1
                    skip_reasons["no_telegram_contact"] += 1
                    continue
                
                # Check if job already exists
                if self.db.job_exists(job_id):
                    skipped_count += 1
                    skip_reasons["already_in_db"] += 1
                    continue
                
                # Save to database
                success = self.db.add_job(
                    job_id=job_id,
                    title=processed_data.job_title,
                    description=processed_data.cleaned_description,
                    contact_info=contact_info,
                    source_channel=original_job['source_channel'],
                    keywords_matched=processed_data.matched_keywords
                )
                
                if success:
                    saved_count += 1
                    logger.info(
                        f"[Batch] Saved job {job_id}: {processed_data.job_title} "
                        f"(Contact: {contact_info}, Keywords: {', '.join(processed_data.matched_keywords)})"
                    )
                else:
                    skipped_count += 1
                    skip_reasons["db_insert_failed"] += 1
            
            # High-signal summary of why things were skipped
            logger.info(
                "Batch processing complete: %s saved, %s skipped | reasons: not_python=%s, no_keywords=%s, "
                "website=%s, no_contact=%s, already_in_db=%s, db_fail=%s",
                saved_count,
                skipped_count,
                skip_reasons["not_python_job"],
                skip_reasons["no_keywords"],
                skip_reasons["website_application"],
                skip_reasons["no_telegram_contact"],
                skip_reasons["already_in_db"],
                skip_reasons["db_insert_failed"],
            )
            
        except Exception as e:
            logger.error(f"Error processing batch: {str(e)}", exc_info=True)
        finally:
            # Clear batch after processing
            self.job_batch.clear()
    
    async def start(self, run_audit: bool = False):
        """Start the Telegram client and register event handlers.
        
        Args:
            run_audit: If True, run title audit before starting monitoring
        """
        await self.client.start(phone=PHONE_NUMBER)
        logger.info("Telegram client started successfully")
        
        # Run audit if requested
        if run_audit:
            logger.info("Running title audit before monitoring...")
            await self.audit_job_titles()
            logger.info("Title audit completed. Starting monitoring...")
        
        # Start periodic flush task (only useful in long-running monitor mode)
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._periodic_flush())

        # Register handler for new messages in monitored channels
        @self.client.on(events.NewMessage(chats=CHANNELS))
        async def handler(event):
            await self.collect_message(event.message)
        
        logger.info(f"Monitoring channels: {', '.join(CHANNELS)}")
        logger.info(f"Collecting jobs in batches of {self.batch_size}. Press Ctrl+C to stop.")
        
        # Keep the client running
        try:
            await self.client.run_until_disconnected()
        finally:
            # Stop periodic flush task
            if self._flush_task:
                self._flush_task.cancel()
                self._flush_task = None
        
        # Process any remaining batch when stopping
        if self.job_batch:
            logger.info("Processing remaining batch before shutdown...")
            await self.process_batch()
    
    async def collect_message(self, message: Message):
        """Collect a new message in batch for processing.
        
        Args:
            message: Telegram message object
        """
        try:
            # Get message text
            message_text = message.message or ""
            
            if not message_text:
                return  # Skip messages without text

            # Cheap pre-filter BEFORE Gemini (saves quota):
            # - must match Python keywords
            # - must NOT be website application
            # - must have at least one '@' (Gemini will decide if it's a real contact handle in context)
            pre_matched = match_python_keywords(message_text, PYTHON_KEYWORDS)
            if not pre_matched:
                return

            if has_website_application(message_text):
                return

            if '@' not in message_text:
                return
            
            # Get channel info
            channel = await message.get_chat()
            channel_username = getattr(channel, 'username', None) or channel.title
            
            # Create unique job ID (channel_id + message_id)
            job_id = f"{channel.id}_{message.id}"
            
            # Check if job already exists
            if self.db.job_exists(job_id):
                logger.debug(f"Job {job_id} already exists in database")
                return
            
            # Add to batch
            self.job_batch.append({
                'job_id': job_id,
                'raw_message': message_text,
                'source_channel': channel_username
            })
            
            logger.info(f"Potential job found in {channel_username}! Adding to batch ({len(self.job_batch)}/{self.batch_size})")
            
            # Process batch when it reaches the threshold
            if len(self.job_batch) >= self.batch_size:
                await self.process_batch()
        
        except Exception as e:
            logger.error(f"Error collecting message {message.id}: {str(e)}", exc_info=True)
    
    async def scan_recent_messages(self, limit: int = 100, client_started: bool = False):
        """Scan recent messages from monitored channels and process in batches.
        
        Collects messages first, then processes them in batches with Gemini to avoid rate limits.
        
        Args:
            limit: Number of recent messages to scan per channel
            client_started: If True, assumes client is already started
        """
        # Start client only if not already started
        if not client_started:
            await self.client.start(phone=PHONE_NUMBER)
        logger.info(f"Scanning recent messages (collecting in batches of {self.batch_size})...")
        
        # Clear any existing batch
        self.job_batch.clear()
        
        # First pass: collect all messages
        for channel_username in CHANNELS:
            try:
                entity = await self.client.get_entity(channel_username)
                logger.info(f"Scanning channel: {channel_username}")
                
                async for message in self.client.iter_messages(entity, limit=limit):
                    if isinstance(message, Message) and message.message:
                        await self.collect_message(message)
                
                logger.info(f"Finished collecting from {channel_username}")
            
            except Exception as e:
                logger.error(f"Error scanning channel {channel_username}: {str(e)}")
        
        # Process any remaining batch
        if self.job_batch:
            logger.info(f"Processing final batch of {len(self.job_batch)} jobs...")
            await self.process_batch()
        
        await self.client.disconnect()
        logger.info("Scan and processing completed")
    
    async def audit_job_titles(self, use_gemini: bool = True):
        """Audit and fix incorrect job titles in the database using Gemini.
        
        Collects jobs in batch and uses Gemini with PydanticAI to extract
        and clean titles with structured JSON output.
        
        Note: Assumes client is already started (doesn't start/stop it).
        
        Args:
            use_gemini: If True, use Gemini for cleaning. If False, use rule-based approach.
        """
        logger.info("Starting job title audit...")
        
        all_jobs = self.db.get_all_jobs_for_audit()
        total_jobs = len(all_jobs)
        
        if total_jobs == 0:
            logger.info("No jobs found in database to audit")
            return
        
        logger.info(f"Auditing {total_jobs} jobs...")
        
        if use_gemini:
            try:
                from gemini_title_cleaner import clean_all_job_titles
                
                # Collect all jobs in batch and process with Gemini
                logger.info("Using Gemini for batch title cleaning...")
                results = await clean_all_job_titles(all_jobs, batch_size=10)
                
                fixed_count = 0
                skipped_count = 0
                
                # Update database with cleaned titles
                for job in all_jobs:
                    job_id = job['job_id']
                    current_title = job.get('title', '')
                    
                    if job_id in results:
                        result = results[job_id]
                        
                        if result.is_valid and result.cleaned_title != current_title:
                            self.db.update_job_title(job_id, result.cleaned_title)
                            logger.info(
                                f"Fixed job {job_id}: '{current_title[:50]}...' -> '{result.cleaned_title[:50]}...' "
                                f"(Reason: {result.reason})"
                            )
                            fixed_count += 1
                        else:
                            logger.debug(f"Skipped job {job_id}: {result.reason}")
                            skipped_count += 1
                    else:
                        skipped_count += 1
                
                logger.info(
                    f"Gemini title audit completed. "
                    f"Fixed: {fixed_count}, Skipped: {skipped_count}, Total: {total_jobs}"
                )
                return
            except Exception as e:
                logger.error(f"Gemini cleaning failed, falling back to rule-based: {str(e)}")
                # Fall through to rule-based approach
        
        # Fallback to rule-based approach
        logger.info("Using rule-based title cleaning...")
        fixed_count = 0
        skipped_count = 0
        
        for job in all_jobs:
            job_id = job['job_id']
            current_title = job.get('title', '')
            description = job.get('description', '')
            
            # Check if title is incorrect
            if is_title_incorrect(current_title, description):
                logger.info(f"Found incorrect title for job {job_id}: '{current_title[:50]}...'")
                
                # Re-extract title using improved logic
                new_title = extract_job_title(description)
                
                # Only update if new title is different and better
                if new_title != current_title and not is_title_incorrect(new_title, description):
                    self.db.update_job_title(job_id, new_title)
                    logger.info(f"  Fixed: '{new_title[:80]}'")
                    fixed_count += 1
                else:
                    logger.debug(f"  Skipped (new title also incorrect or same)")
                    skipped_count += 1
            else:
                skipped_count += 1
        
        logger.info(
            f"Title audit completed. "
            f"Fixed: {fixed_count}, Skipped: {skipped_count}, Total: {total_jobs}"
        )


async def run_monitor(db: JobDatabase, scan_recent: bool = False, audit_titles: bool = False):
    """Run the job monitor.
    
    Args:
        db: JobDatabase instance
        scan_recent: If True, scan recent messages and exit. If False, monitor continuously.
        audit_titles: If True, run title audit (before scanning/monitoring if also requested).
    """
    monitor = JobMonitor(db)
    
    # Run title audit if requested (doesn't need Telegram connection, but we'll start it anyway)
    if audit_titles:
        await monitor.client.start(phone=PHONE_NUMBER)
        await monitor.audit_job_titles()
        # Don't disconnect yet if we need to scan
        if not scan_recent:
            await monitor.client.disconnect()
            logger.info("Title audit completed. Exiting.")
            return
    
    # Run scan if requested
    if scan_recent:
        # Client already started if audit ran, otherwise start it now
        client_already_started = audit_titles
        if not client_already_started:
            await monitor.client.start(phone=PHONE_NUMBER)
        await monitor.scan_recent_messages(client_started=client_already_started)
        # Client will be disconnected by scan_recent_messages
    else:
        # Continuous monitoring (client already started if audit ran)
        if not audit_titles:
            await monitor.client.start(phone=PHONE_NUMBER)
        await monitor.start(run_audit=False)  # Don't run audit again, already done

