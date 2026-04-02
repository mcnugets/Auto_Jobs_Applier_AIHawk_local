import os
import sys
import argparse
import time
import random
from pathlib import Path
from loguru import logger
from dataclasses import dataclass

from src.utils import chrome_browser_options
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

from src.llm.llm_manager import GPTAnswerer
from src.aihawk_authenticator import AIHawkAuthenticator
from src.job_application_profile import JobApplicationProfile
from lib_resume_builder_AIHawk import Resume, FacadeManager, ResumeGenerator, StyleManager
from src.aihawk_easy_applier import AIHawkEasyApplier
from src.job import Job
from main import FileManager, ConfigValidator

def run_easy_apply_test(job_url: str):
    logger.info(f"Starting Easy Apply Test for URL: {job_url}")
    
    # 1. Load Data/Configs
    data_folder = Path("data_folder")
    secrets_file, config_file, plain_text_resume_file, output_folder = FileManager.validate_data_folder(data_folder)
    parameters = ConfigValidator.validate_config(config_file)
    llm_api_key = ConfigValidator.validate_secrets(secrets_file)
    
    # 2. Force Headless=False for visual feedback
    parameters['headless'] = False
    parameters['outputFileDirectory'] = output_folder
    
    # 3. Resume Setup
    with open(plain_text_resume_file, "r", encoding='utf-8') as f:
        plain_text_resume = f.read()
    profile = JobApplicationProfile(plain_text_resume)
    resume_object = Resume(plain_text_resume)
    
    style_manager = StyleManager()
    resume_generator = ResumeGenerator()
    resume_generator_manager = FacadeManager(
        llm_api_key, 
        style_manager, 
        resume_generator, 
        resume_object, 
        output_folder / "resume.log"
    )
    resume_generator_manager.selected_style = parameters.get("resume_style", "Modern Blue")
    
    # 4. Browser Setup
    options = chrome_browser_options(headless=False)
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        # 5. Authenticate via standard flow
        authenticator = AIHawkAuthenticator(driver)
        logger.info("Initializing Authentication Flow...")
        if not authenticator.is_logged_in():
            logger.info("Manual login might be required. If you see a login screen, please log in now.")
            authenticator.start()
        
        # 6. Initialize LLM Answerer
        gpt_answerer = GPTAnswerer(parameters, llm_api_key)
        gpt_answerer.set_resume(resume_object)
        gpt_answerer.set_job_application_profile(profile)
        
        # 7. Setup Easy Applier
        applier = AIHawkEasyApplier(
            driver=driver,
            resume_dir=None,
            set_old_answers=[],
            gpt_answerer=gpt_answerer,
            resume_generator_manager=resume_generator_manager,
            parameters=parameters,
            config_yaml_path=config_file
        )
        
        # 8. Define the single job to test
        job = Job(
            title="Single Job Test", 
            company="Test Company", 
            location="Remote", 
            link=job_url, 
            apply_method="Easy Apply"
        )
        
        logger.info(f"Attempting to navigate and apply to single job: {job_url}")
        applier.apply_to_job(job)
        logger.info("Single-job Easy Apply test completed successfully.")
        
    except Exception as e:
        logger.error(f"Test Execution Failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
    finally:
        logger.info("Closing browser in 10 seconds...")
        time.sleep(10)
        driver.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply for exactly ONE LinkedIn Easy Apply job.")
    parser.add_argument("url", help="Full LinkedIn Job URL")
    args = parser.parse_args()
    
    if not args.url.startswith("https://www.linkedin.com/"):
        print("Error: Please provide a valid LinkedIn Job URL.")
        sys.exit(1)
        
    run_easy_apply_test(args.url)
