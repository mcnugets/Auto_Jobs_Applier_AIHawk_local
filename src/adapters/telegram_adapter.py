import asyncio
import logging
import sys
from loguru import logger
from pathlib import Path

from src.adapters.base_adapter import BaseJobAdapter
from src.job_application_profile import JobApplicationProfile

# Import from the newly copied telegram bot
try:
    from src.telegram_bot.database import JobDatabase
    from src.telegram_bot.job_monitor import run_monitor
    from src.telegram_bot.job_applier import run_applier
    from src.telegram_bot.config import validate_config as validate_telegram_config
    
    # AIHawk Core components for dynamic generation
    from src.llm.llm_manager import GPTAnswerer
    from lib_resume_builder_AIHawk import Resume, StyleManager, FacadeManager, ResumeGenerator
except ImportError as e:
    logger.error(f"Failed to import telegram bot or AIHawk modules: {e}")
    JobDatabase = None
    run_monitor = None
    run_applier = None
    validate_telegram_config = None
    GPTAnswerer = None
    Resume = None
    StyleManager = None
    FacadeManager = None
    ResumeGenerator = None

class TelegramAdapter(BaseJobAdapter):
    def __init__(self, profile: JobApplicationProfile, parameters: dict, llm_api_key: str):
        super().__init__(profile, parameters, llm_api_key)
        self.db = None
    
    def login(self) -> bool:
        pass

    def search_jobs(self, keywords=None) -> list:
        pass

    def apply_to_job(self, job_data, profile: JobApplicationProfile) -> bool:
        pass

    def run(self) -> None:
        try:
            logger.info("Validating Telegram Bot Configuration...")
            validate_telegram_config()
            
            db_path = self.parameters.get("telegram_db_path", "jobs.db")
            self.db = JobDatabase(db_path=db_path)
            logger.info(f"Telegram Database initialized at {db_path}")

            # Collect mode will just monitor
            if self.parameters.get('collectMode') is True:
                logger.info("Running Telegram Monitor mode")
                asyncio.run(run_monitor(self.db, scan_recent=True, audit_titles=False))
            else:
                logger.info("Running Telegram Applier mode")
                
                # Verify components are available
                if not all([GPTAnswerer, Resume, StyleManager, FacadeManager, ResumeGenerator]):
                    logger.error("Missing AIHawk components. Cannot run Telegram Applier.")
                    return

                # Initialize Universal AIHawk AI generator
                gpt_manager = GPTAnswerer(self.parameters, self.llm_api_key)
                
                # Load profile into Resume generator
                import os
                resume_object = None
                resume_generator = None
                facade_manager = None
                
                try:
                    resume_object = Resume(self.profile.yaml_str)
                    style_manager = StyleManager()
                    resume_generator = ResumeGenerator()
                    output_folder = Path(self.parameters.get('outputFileDirectory', "data_folder/output"))

                    facade_manager = FacadeManager(
                        self.llm_api_key, 
                        style_manager, 
                        resume_generator, 
                        resume_object, 
                        output_folder / "resume.log"
                    )
                    
                    # Set style non-interactively for the bot
                    selected_style = self.parameters.get("resume_style", "Modern Blue")
                    facade_manager.selected_style = selected_style
                    logger.info(f"Resume style set to: {selected_style}")
                        
                except Exception as e:
                    logger.warning(f"Failed to initialize dynamic Resume generator (using static fallback): {e}")
                    resume_generator = None
                    facade_manager = None
                
                # Can run monitor and then applier for a full pass
                logger.info("="*50)
                logger.info("PHASE 1: SCANNING TELEGRAM CHANNELS")
                logger.info("="*50)
                asyncio.run(run_monitor(self.db, scan_recent=True, audit_titles=False))
                
                logger.info("="*50)
                logger.info("PHASE 2: APPLYING TO DISCOVERED JOBS")
                logger.info("="*50)
                asyncio.run(
                    run_applier(
                        self.db, 
                        limit=None, 
                        llm_manager=gpt_manager, 
                        profile=self.profile,
                        facade_manager=facade_manager,
                        resume_object=resume_object
                    )
                )
                logger.info("="*50)
                logger.info("TELEGRAM ADAPTER SESSION COMPLETED")
                logger.info("="*50)
                
        except Exception as e:
            logger.error(f"Telegram Adapter Error: {e}", exc_info=True)
