import os
import sys
import time
from pathlib import Path
from loguru import logger
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

from src.utils import chrome_browser_options
from src.aihawk_authenticator import AIHawkAuthenticator
from src.aihawk_easy_applier import AIHawkEasyApplier
from main import FileManager, ConfigValidator

def test_recursive_button(job_url: str):
    logger.info(f"Starting Recursive Button Test for URL: {job_url}")
    
    data_folder = Path("data_folder")
    secrets_file, config_file, plain_text_resume_file, output_folder = FileManager.validate_data_folder(data_folder)
    parameters = ConfigValidator.validate_config(config_file)
    llm_api_key = ConfigValidator.validate_secrets(secrets_file)
    
    # Force Headless=True for CI environment
    options = chrome_browser_options(headless=True)
    
    # Try different user-data-dir paths
    profile_paths = [
        os.path.abspath('chrome_profile/linkedin_profile'),
        os.path.abspath('chrome_profile')
    ]
    
    for path in profile_paths:
        if os.path.exists(path):
            logger.info(f"Using Chrome user-data-dir at: {path}")
            options.add_argument(f"--user-data-dir={path}")
            # options.add_argument("--profile-directory=Default")
            break
    
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        # Navigate to home first to confirm login
        logger.info("Checking login status at https://www.linkedin.com/feed")
        driver.get("https://www.linkedin.com/feed")
        time.sleep(5)
        
        authenticator = AIHawkAuthenticator(driver)
        if not authenticator.is_logged_in():
            logger.warning("Still not detected as logged in at Feed. Page title: " + driver.title)
            driver.save_screenshot("feed_not_logged_in.png")
            # If not logged in, we try the job URL anyway
        
        logger.info(f"Navigating to job URL: {job_url}")
        driver.get(job_url)
        time.sleep(10)
        
        # Look for "Easy Apply" button
        easy_apply_button = None
        selectors = [
            "//button[contains(@class, 'jobs-apply-button')]",
            "//button[@data-control-name='job_details_top_card_apply_methods']",
            "//div[contains(@class, 'jobs-apply-button')]//button",
            "//button[contains(., 'Easy Apply')]",
            "//button[contains(., 'Apply')]"
        ]
        
        for selector in selectors:
            try:
                elements = driver.find_elements(By.XPATH, selector)
                for el in elements:
                    text = el.text.lower()
                    if "easy apply" in text or "apply" in text:
                        logger.info(f"Found candidate button with selector '{selector}'. Text: '{text}'")
                        easy_apply_button = el
                        break
                if easy_apply_button: break
            except:
                continue

        if not easy_apply_button:
            logger.error("Could not find 'Easy Apply' button. Saving screenshot...")
            driver.save_screenshot("easy_apply_not_found.png")
            return

        logger.info("Clicking 'Easy Apply' button...")
        try:
            easy_apply_button.click()
        except:
            driver.execute_script("arguments[0].click();", easy_apply_button)
        time.sleep(5)
        
        # Initialize Applier
        applier = AIHawkEasyApplier(
            driver=driver,
            resume_dir=None,
            set_old_answers=[],
            gpt_answerer=None,
            resume_generator_manager=None,
            parameters=parameters,
            config_yaml_path=config_file
        )
        
        logger.info("Testing recursive button finding logic...")
        
        # Diagnostic search for ANY button
        all_buttons = driver.find_elements(By.TAG_NAME, "button")
        logger.debug(f"Total buttons found on page: {len(all_buttons)}")
        
        # Test 1: Standard find
        btn, strategy = applier._find_primary_button()
        if btn:
            logger.info(f"Standard find found button with strategy: {strategy}. Text: {btn.text}")
        else:
            logger.warning("Standard find failed to find the primary button.")
            
        # Test 2: Recursive JS find
        btn_js = applier._find_button_recursive_js()
        if btn_js:
            logger.info(f"Recursive JS find found button. Text: {btn_js.text}")
        else:
            logger.warning("Recursive JS find failed to find the primary button.")
            
        # Test 3: Full next_or_submit
        logger.info("Executing _next_or_submit()...")
        try:
            result = applier._next_or_submit()
            logger.success(f"_next_or_submit result: {result}")
        except Exception as e:
            logger.error(f"_next_or_submit failed: {str(e)}")
            driver.save_screenshot("next_button_failed.png")
            
    except Exception as e:
        logger.error(f"Test Execution Failed: {str(e)}")
    finally:
        driver.quit()

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.linkedin.com/jobs/view/4055778229"
    test_recursive_button(url)
