import os
from pathlib import Path
from selenium.common.exceptions import WebDriverException
from loguru import logger

from src.adapters.base_adapter import BaseJobAdapter
from src.job_application_profile import JobApplicationProfile
from lib_resume_builder_AIHawk import Resume, FacadeManager, ResumeGenerator, StyleManager
from src.llm.llm_manager import GPTAnswerer
from src.aihawk_authenticator import AIHawkAuthenticator
from src.aihawk_job_manager import AIHawkJobManager
from src.aihawk_bot_facade import AIHawkBotFacade
import main  # To use init_browser, or import init_browser from main later

def init_browser(headless=False):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager
    from src.utils import chrome_browser_options
    
    options = chrome_browser_options(headless=headless)
    service = ChromeService(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

class LinkedInAdapter(BaseJobAdapter):
    def __init__(self, profile: JobApplicationProfile, parameters: dict, llm_api_key: str):
        super().__init__(profile, parameters, llm_api_key)
        self.resume_object = None
        self.bot = None

    def login(self) -> bool:
        # Initialized and handled by the old bot start_login()
        pass

    def search_jobs(self, keywords=None) -> list:
        # Internal to AIHawkJobManager
        pass

    def apply_to_job(self, job_data) -> bool:
        pass

    def run(self) -> None:
        try:
            logger.info("Starting LinkedIn Applier")
            style_manager = StyleManager()
            resume_generator = ResumeGenerator()
            
            with open(self.parameters['uploads']['plainTextResume'], "r", encoding='utf-8') as file:
                plain_text_resume = file.read()
            self.resume_object = Resume(plain_text_resume)
      
            # Output folder path logic
            output_folder = Path(self.parameters.get('outputFileDirectory', "data_folder/output"))
            
            resume_generator_manager = FacadeManager(
                self.llm_api_key, 
                style_manager, 
                resume_generator, 
                self.resume_object, 
                output_folder / "resume.log"
            )
            
            # Set style non-interactively
            selected_style = self.parameters.get("resume_style", "Modern Blue")
            resume_generator_manager.selected_style = selected_style
            logger.info(f"Resume style set to: {selected_style}")
            
            browser = init_browser(headless=self.parameters.get('headless', False))
            login_component = AIHawkAuthenticator(browser)
            apply_component = AIHawkJobManager(browser)
            gpt_answerer_component = GPTAnswerer(self.parameters, self.llm_api_key)
            
            self.bot = AIHawkBotFacade(login_component, apply_component)
            self.bot.set_job_application_profile_and_resume(self.profile, self.resume_object)
            self.bot.set_gpt_answerer_and_resume_generator(gpt_answerer_component, resume_generator_manager)
            self.bot.set_parameters(self.parameters)
            
            self.bot.start_login()
            
            if self.parameters.get('collectMode') is True:
                logger.info('Collecting Mode Enabled')
                self.bot.start_collect_data()
            else:
                logger.info('Applying Mode Enabled')
                self.bot.start_apply()
                
        except WebDriverException as e:
            logger.error(f"WebDriver error occurred: {e}")
        except Exception as e:
            raise RuntimeError(f"Error running the bot: {str(e)}")
