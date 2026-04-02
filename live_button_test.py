import os
import sys
import argparse
import time
import random
from pathlib import Path
from loguru import logger
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

from src.utils import chrome_browser_options
from src.aihawk_authenticator import AIHawkAuthenticator
from src.aihawk_easy_applier import AIHawkEasyApplier
from main import FileManager, ConfigValidator

def run_live_button_test(job_url: str):
    logger.info("Starting LIVE 'Next' Button Test...")
    
    # 1. Setup Data Paths
    data_folder = Path("data_folder")
    secrets_file, config_file, plain_text_resume_file, output_folder = FileManager.validate_data_folder(data_folder)
    parameters = ConfigValidator.validate_config(config_file)
    llm_api_key = ConfigValidator.validate_secrets(secrets_file)
    
    # 2. Browser Options (Force Headless=False)
    options = chrome_browser_options(headless=False)
    # Using existing profile if possible to avoid login
    # options.add_argument(f"--user-data-dir={os.path.abspath('chrome_profile/linkedin_profile')}")
    
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        # 3. Authenticate
        authenticator = AIHawkAuthenticator(driver)
        if not authenticator.is_logged_in():
            logger.info("Not logged in. Please log in manually in the opened browser...")
            # We wait for user to login
            while not authenticator.is_logged_in():
                time.sleep(5)
            logger.info("Login detected!")

        # 4. Navigate to Job
        logger.info(f"Navigating to job: {job_url}")
        driver.get(job_url)
        time.sleep(5)
        
        # 5. Initialize Applier (Minimal)
        applier = AIHawkEasyApplier(
            driver=driver,
            resume_dir=None,
            set_old_answers=[],
            gpt_answerer=None, # Not needed for button click test
            resume_generator_manager=None,
            parameters=parameters,
            config_yaml_path=config_file
        )
        
        # 6. Manual step: User should click "Easy Apply" first to open the form
        logger.info("PLEASE CLICK 'EASY APPLY' MANUALLY if it's not already open.")
        logger.info("Once the form is open, I will attempt to test the '_next_or_submit' logic.")
        
        input("Press Enter once the Easy Apply form is open and you're ready to test the 'Next' button...")
        
        # 7. Execute the target method
        logger.info("Executing applier._next_or_submit()...")
        result = applier._next_or_submit()
        
        logger.success(f"Method '_next_or_submit' executed successfully. Result: {result}")
        logger.info("Check the browser to see if the page actually changed.")
        
    except Exception as e:
        logger.error(f"Live Test Failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        logger.info("Test finished. Keeping browser open for 60s for inspection...")
        time.sleep(60)
        driver.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live test for the 'Next' button logic.")
    parser.add_argument("url", help="LinkedIn Job URL with Easy Apply")
    args = parser.parse_args()
    
    run_live_button_test(args.url)
