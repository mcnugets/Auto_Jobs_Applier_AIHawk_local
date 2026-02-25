"""Send job applications via Telegram."""
import asyncio
import logging
from pathlib import Path
from typing import Optional
from telethon import TelegramClient
from telethon.errors import UsernameNotOccupiedError, FloodWaitError, PeerFloodError, ForbiddenError

from .config import API_ID, API_HASH, PHONE_NUMBER, SESSION_PATH, CV_PATH, MESSAGE_TEMPLATE
from .database import JobDatabase
from .utils import format_message




# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler('job_applier.log'),
#         logging.StreamHandler()
#     ]
# )
logger = logging.getLogger(__name__)

import random
class JobApplier:
    """Sends job applications via Telegram."""
    
    def __init__(self, db: JobDatabase):
        """Initialize the job applier.
        
        Args:
            db: JobDatabase instance
        """
        self.db = db
        self.client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
        self.cv_path = Path(CV_PATH)
        
        if not self.cv_path.exists():
            raise FileNotFoundError(f"CV file not found at {CV_PATH}")
    
    async def start(self):
        """Start the Telegram client."""
        await self.client.start(phone=PHONE_NUMBER)
        logger.info("Telegram client started successfully")
    
    async def has_chat_history(self, entity) -> bool:
        """Check if we have existing chat history with this user.
        
        Args:
            entity: Telegram entity (user/chat)
            
        Returns:
            True if we have sent messages to this user before, False otherwise
        """
        try:
            # Get my own user ID to check if messages are from me
            me = await self.client.get_me()
            my_id = me.id
            
            # Check last 10 messages in the chat
            message_count = 0
            async for message in self.client.iter_messages(entity, limit=10):
                # If we find a message from us, we have history
                if message.sender_id == my_id:
                    return True
                message_count += 1
            
            # If no messages found at all, no history
            return False
        except Exception as e:
            logger.debug(f"Error checking chat history: {str(e)}")
            # On error, assume no history (safer to try than skip)
            return False
    
    async def send_application(self, job: dict) -> bool:
        """Send application message with CV to a job contact.
        
        Args:
            job: Job dictionary from database
            
        Returns:
            True if application was sent successfully, False otherwise
        """
        contact_info = job.get('contact_info', '').strip()
        
        if not contact_info:
            logger.warning(f"Job {job['job_id']} has no contact information, skipping")
            return False
        
        # Only handle Telegram handles
        if not contact_info.startswith('@'):
            logger.warning(
                f"Contact info '{contact_info}' for job {job['job_id']} "
                "is not a Telegram handle (@username), skipping"
            )
            return False
        
        username = contact_info[1:]  # Remove @
        
        try:
            entity = await self.client.get_entity(username)
        except UsernameNotOccupiedError:
            logger.error(f"Telegram username {contact_info} not found for job {job['job_id']}")
            return False
        except Exception as e:
            logger.error(f"Error getting entity {contact_info}: {str(e)}")
            return False
        
        # Check if we have chat history with this user (check actual Telegram messages)
        has_history = await self.has_chat_history(entity)
        if has_history:
            logger.info(
                f"User @{username} has existing chat history, skipping to avoid spam "
                f"(job {job['job_id']})"
            )
            # Mark job as applied and user as contacted to avoid retrying
            self.db.mark_as_applied(job['job_id'])
            self.db.mark_user_contacted(username)
            return False
        
        # Also check database for previously contacted users
        if self.db.is_user_contacted(username):
            logger.info(f"User @{username} already contacted previously (database), skipping to avoid spam")
            # Mark job as applied anyway to avoid retrying
            self.db.mark_as_applied(job['job_id'])
            return False
        
        try:
            # Ensure LLM manager has the resume object for fallback generation
            if getattr(self, 'llm_manager', None) and getattr(self, 'resume_object', None):
                if not getattr(self.llm_manager, 'resume', None):
                    self.llm_manager.set_resume(self.resume_object)

            # Optimized Batched Generation: Get all text artifacts in one call
            artifacts = {}
            if getattr(self, 'llm_manager', None) and getattr(self, 'profile', None):
                artifacts = self.llm_manager.generate_application_artifacts(
                    job.get('description', ''),
                    self.profile.yaml_str
                )
            
            # 1. Generate Application Message (Telegram Caption)
            message = artifacts.get('telegram_message')
            if not message:
                # Fallback to legacy single-call dynamic generation or static template
                if getattr(self, 'llm_manager', None) and getattr(self, 'profile', None):
                    from src.telegram_bot.config import TELEGRAM_MESSAGE_PROMPT
                    job_context = f"Job Title: {job.get('title')}\nDescription: {job.get('description')}"
                    message = self.llm_manager.answer_question_textual_wide_range(
                        f"{TELEGRAM_MESSAGE_PROMPT}\n\n{job_context}"
                    )
                else:
                    from src.telegram_bot.config import MESSAGE_TEMPLATE
                    message = format_message(MESSAGE_TEMPLATE, job.get('title'))
            
            # 2. Generate PDF CV
            current_cv_path = self.cv_path
            if getattr(self, 'facade_manager', None) and getattr(self, 'resume_object', None):
                try:
                    # We need a string job description for the ResumeGenerator to parse
                    plain_desc = str(job.get('description', ''))
                    
                    resume_sections = artifacts.get('resume_sections')
                    pdf_base_64_str = self.facade_manager.pdf_base64(
                        job_description_text=plain_desc,
                        precomputed_sections=resume_sections
                    )
                    
                    if pdf_base_64_str:
                        import base64
                        output_dir = Path("data_folder/output")
                        output_dir.mkdir(parents=True, exist_ok=True)
                        temp_pdf_path = output_dir / f"cv_{job['job_id']}.pdf"
                        
                        with open(temp_pdf_path, "wb") as f:
                            f.write(base64.b64decode(pdf_base_64_str))
                            
                        current_cv_path = temp_pdf_path
                        logger.info(f"Generated tailored CV for job {job.get('job_id', 'unknown')}")
                except Exception as e:
                    logger.error(f"Error generating tailored CV: {e}")
                    # Fallback to static CV path already set above
            
            # Send message with CV attachment
            await self.client.send_file(
                entity,
                current_cv_path,
                caption=message,
                parse_mode='html'
            )
            
            logger.info(
                f"Application sent successfully to {contact_info} "
                f"for job {job['job_id']} ({job.get('title', 'N/A')})"
            )
            
            # Mark user as contacted (persistent tracking to avoid spam)
            self.db.mark_user_contacted(username)
            
            # Mark job as applied
            self.db.mark_as_applied(job['job_id'])
            
            return True
        
        except FloodWaitError as e:
            logger.warning(f"Rate limit exceeded. Need to wait {e.seconds} seconds")
            logger.info(f"Waiting {e.seconds} seconds before retrying...")
            await asyncio.sleep(e.seconds)
            # Retry once after waiting
            return await self.send_application(job)
        
        except (PeerFloodError, ForbiddenError) as e:
            error_name = "Peer flood" if isinstance(e, PeerFloodError) else "Forbidden (Privacy/Premium)"
            logger.error(
                f"{error_name} error when sending to {contact_info}. "
                f"Details: {str(e)}"
            )
            return False
        
        except Exception as e:
            logger.error(
                f"Error sending application to {contact_info} "
                f"for job {job['job_id']}: {str(e)}",
                exc_info=True
            )
            return False
    
    async def apply_to_jobs(self, limit: Optional[int] = None):
        """Apply to all unapplied jobs.
        
        Args:
            limit: Maximum number of jobs to apply to (None for all)
        """
        await self.start()
        
        unapplied_jobs = self.db.get_unapplied_jobs()
        
        if not unapplied_jobs:
            logger.info("No unapplied jobs found")
            await self.client.disconnect()
            return
        
        total_jobs = len(unapplied_jobs)
        if limit:
            unapplied_jobs = unapplied_jobs[:limit]
            logger.info(f"Processing {len(unapplied_jobs)} of {total_jobs} unapplied jobs")
        else:
            logger.info(f"Processing {total_jobs} unapplied jobs")
        
        successful = 0
        failed = 0
        
        for i, job in enumerate(unapplied_jobs, 1):
            logger.info(f"Processing job {i}/{len(unapplied_jobs)}: {job['job_id']}")
            
            success = await self.send_application(job)
            
            if success:
                successful += 1
            else:
                failed += 1
            
            # Add a small delay between messages to avoid rate limiting
            if i < len(unapplied_jobs):
                await asyncio.sleep(random.uniform(5, 10)) 
        
        logger.info(
            f"Application process completed. "
            f"Successful: {successful}, Failed: {failed}"
        )
        
        await self.client.disconnect()


async def run_applier(db: JobDatabase, limit: Optional[int] = None, llm_manager=None, profile=None, facade_manager=None, resume_object=None):
    """Run the job applier.
    
    Args:
        db: JobDatabase instance
        limit: Maximum number of jobs to apply to (None for all)
        llm_manager: Optional instance of GPTAnswerer to generate dynamic text
        profile: Optional instance of JobApplicationProfile
        facade_manager: Optional FacadeManager to build CVs
        resume_object: Optional Resume instance containing parsed profile
    """
    from src.telegram_bot.job_applier import JobApplier
    applier = JobApplier(db)
    applier.llm_manager = llm_manager
    applier.profile = profile
    applier.facade_manager = facade_manager
    applier.resume_object = resume_object
    await applier.apply_to_jobs(limit=limit)

