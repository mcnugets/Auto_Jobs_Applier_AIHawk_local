import random
import time

from selenium.common.exceptions import NoSuchElementException, TimeoutException, NoAlertPresentException, TimeoutException, UnexpectedAlertPresentException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from loguru import logger


class AIHawkAuthenticator:

    def __init__(self, driver=None):
        self.driver = driver
        logger.debug(f"AIHawkAuthenticator initialized with driver: {driver}")

    def start(self):
        logger.info("Starting Chrome browser to log in to AIHawk.")
        if self.is_logged_in():
            logger.info("User is already logged in. Skipping login process.")
            return

        logger.info("User is not logged in. Proceeding with login.")
        self.handle_login()
        logger.info("Login process completed. Continuing...")

    def handle_login(self):
        logger.info("Navigating to the AIHawk login page...")
        self.driver.get("https://www.linkedin.com/login")
        
        try:
            self.enter_credentials()
        except NoSuchElementException as e:
            logger.error(f"Could not log in to AIHawk. Element not found: {e}")
        self.handle_security_check()


    def enter_credentials(self):
        try:
            logger.debug("Enter credentials...")
            
            check_interval = 4  # Interval to log the current URL
            elapsed_time = 0

            while True:
                # Log current URL every 4 seconds and remind the user to log in
                current_url = self.driver.current_url
                logger.info(f"Please login on {current_url}")

                # Check if the user is already on the feed page
                if 'feed' in current_url:
                    logger.debug("Login successful, redirected to feed page.")
                    break
                else:
                    # Optionally wait for the password field (or any other element you expect on the login page)
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.ID, "password"))
                    )
                    logger.debug("Password field detected, waiting for login completion.")

                time.sleep(check_interval)
                elapsed_time += check_interval

        except TimeoutException:
            logger.error("Login form not found. Aborting login.")


    def handle_security_check(self):
        try:
            logger.debug("Checking for security checkpoint...")
            # Short wait to see if redirected to challenge page
            WebDriverWait(self.driver, 5).until(
                EC.url_contains('https://www.linkedin.com/checkpoint/challengesV2/')
            )
            logger.warning("Security checkpoint detected. Please complete the challenge.")
            # Long wait for user to solve challenge and reach feed
            WebDriverWait(self.driver, 300).until(
                EC.url_contains('https://www.linkedin.com/feed/')
            )
            logger.info("Security check completed successfully.")
        except TimeoutException:
            # Check if we are already on the feed page
            if 'feed' in self.driver.current_url:
                logger.info("No security check needed or already completed.")
            else:
                logger.debug("No security checkpoint detected within 5 seconds.")
        except Exception as e:
            logger.error(f"Unexpected error during security check: {e}")

    def is_logged_in(self):
        try:
            logger.debug("Checking if user is logged in (passive check)...")
            current_url = self.driver.current_url

            # Prioritize checking for clear logged-out states or intermediate pages first
            if "linkedin.com/login" in current_url:
                logger.debug("Currently on LinkedIn login page. User is not logged in.")
                return False
            if "linkedin.com/checkpoint/challenge" in current_url or "linkedin.com/uas/oauth/authorize" in current_url:
                logger.warning(f"Currently on a security/challenge page: {current_url}. User is not fully logged in.")
                return False
            
            # Attempt to accept cookie/privacy consent if present, without failing the whole check
            try:
                # Look for common cookie consent pop-ups or banners
                consent_button = WebDriverWait(self.driver, 1).until( # Shorter wait to not block
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Accept cookies') or contains(., 'Accept') or contains(., 'Agree')]"))
                )
                if consent_button.is_displayed():
                    consent_button.click()
                    logger.info("Clicked cookie consent button. Continuing login check.")
                    time.sleep(1) # Small pause for page to react
            except TimeoutException:
                logger.debug("No cookie consent pop-up/banner found during passive check.")
            except Exception as e:
                logger.warning(f"Error handling cookie consent during passive check: {e}")

            # Now, check for the most definitive logged-in element on the current page
            # The global navigation bar (ID 'global-nav') is usually a very reliable indicator.
            selectors = [
                (By.ID, 'global-nav'), # Main global navigation bar
                (By.XPATH, "//input[contains(@class, 'search-global-typeahead__input')]") # Global search input field
            ]
            
            for selector_type, selector_value in selectors:
                logger.debug(f"Attempting to detect login via selector: {selector_value}")
                try:
                    # Very short wait, if it's there, it's there. No need to wait long.
                    element = WebDriverWait(self.driver, 1).until(
                        EC.presence_of_element_located((selector_type, selector_value))
                    )
                    if element.is_displayed():
                        logger.info(f"User is logged in (detected via {selector_value})")
                        return True
                except Exception as e:
                    logger.debug(f"Login check failed for selector {selector_value}: {e}")
                    continue

            logger.info("User might not be logged in. No common logged-in elements found on the current page after trying multiple selectors.")
            return False

        except Exception as e:
            logger.error(f"Error during passive login check: {e}")
            return False