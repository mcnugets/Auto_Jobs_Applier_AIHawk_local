import base64
import json
import os
import random
import re
import time
import traceback
from typing import List, Optional, Any, Tuple, Dict
from pathlib import Path

from httpx import HTTPStatusError
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from reportlab.pdfbase.pdfmetrics import stringWidth
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

import src.utils as utils
from loguru import logger


class SelectorCache:
    def __init__(self, cache_file: Path):
        self.cache_file = cache_file
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except: return {}
        return {}

    def save(self):
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=4)
        except: pass

    def get(self, key: str) -> Optional[dict]:
        return self.cache.get(key)

    def update(self, key: str, value: dict):
        self.cache[key] = value
        self.save()

class AIHawkEasyApplier:
    def __init__(self, driver: Any, resume_dir: Optional[str], set_old_answers: List[Tuple[str, str, str]],
                 gpt_answerer: Any, resume_generator_manager, parameters: dict, config_yaml_path: Path):
        logger.debug("Initializing AIHawkEasyApplier")
        if resume_dir is None or not os.path.exists(resume_dir):
            resume_dir = None
        self.driver = driver
        self.resume_path = resume_dir
        self.set_old_answers = set_old_answers
        self.gpt_answerer = gpt_answerer
        self.resume_generator_manager = resume_generator_manager
        self.all_data = self._load_questions_from_json()
        self.current_job = None
        self.batch_answers = {}
        self.parameters = parameters
        self.config_yaml_path = config_yaml_path
        
        # Initialize Selector Cache
        cache_path = Path("data_folder/output/selectors_cache.json")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.selector_cache = SelectorCache(cache_path)

        logger.debug("AIHawkEasyApplier initialized successfully")

    def _load_questions_from_json(self) -> List[dict]:
        output_file = 'answers.json'
        logger.debug(f"Loading questions from JSON file: {output_file}")
        try:
            with open(output_file, 'r') as f:
                try:
                    data = json.load(f)
                    if not isinstance(data, list):
                        raise ValueError("JSON file format is incorrect. Expected a list of questions.")
                except json.JSONDecodeError:
                    logger.error("JSON decoding failed")
                    data = []
            logger.debug("Questions loaded successfully from JSON")
            return data
        except FileNotFoundError:
            logger.warning("JSON file not found, returning empty list")
            return []
        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Error loading questions data from JSON file: {tb_str}")
            raise Exception(f"Error loading questions data from JSON file: \nTraceback:\n{tb_str}")

    def check_for_premium_redirect(self, job: Any, max_attempts=3):

        current_url = self.driver.current_url
        attempts = 0

        while "linkedin.com/premium" in current_url and attempts < max_attempts:
            logger.warning("Redirected to AIHawk Premium page. Attempting to return to job page.")
            attempts += 1

            self.driver.get(job.link)
            time.sleep(2)
            current_url = self.driver.current_url

        if "linkedin.com/premium" in current_url:
            logger.error(f"Failed to return to job page after {max_attempts} attempts. Cannot apply for the job.")
            raise Exception(
                f"Redirected to AIHawk Premium page and failed to return after {max_attempts} attempts. Job application aborted.")
            
    def apply_to_job(self, job: Any) -> None:
        """
        Starts the process of applying to a job.
        :param job: A job object with the job details.
        :return: None
        """
        logger.debug(f"Applying to job: {job}")
        try:
            self.job_apply(job)
            logger.info(f"Successfully applied to job: {job.title}")
        except Exception as e:
            logger.error(f"Failed to apply to job: {job.title}, error: {str(e)}")
            raise e

    def job_apply(self, job: Any):
        logger.debug(f"Starting job application for job: {job}")
        self.batch_answers = {}

        try:
            self.driver.get(job.link)
            logger.debug(f"Navigated to job link: {job.link}")
        except Exception as e:
            logger.error(f"Failed to navigate to job link: {job.link}, error: {str(e)}")
            raise

        time.sleep(random.uniform(3, 5))
        self.check_for_premium_redirect(job)

        try:

            self.driver.execute_script("document.activeElement.blur();")
            logger.debug("Focus removed from the active element")

            self.check_for_premium_redirect(job)

            easy_apply_button = self._find_easy_apply_button(job)

            self.check_for_premium_redirect(job)

            logger.debug("Retrieving job description")
            job_description = self._get_job_description()
            if not job_description:
                raise Exception("Failed to retrieve job description after multiple attempts. Aborting application for this job.")
            job.set_job_description(job_description)
            logger.debug(f"Job description set: {job_description[:100]}...")

            logger.debug("Retrieving recruiter link")
            recruiter_link = self._get_job_recruiter()
            job.set_recruiter_link(recruiter_link)
            logger.debug(f"Recruiter link set: {recruiter_link}")

            self.current_job = job

            logger.debug("Attempting to click 'Easy Apply' button")
            if not utils.safe_click(self.driver, easy_apply_button):
                 # If safe_click failed (popup open), we'll try a fallback: click the button via JS
                 logger.debug("Safe click blocked by popup. Forcing click via JS...")
                 self.driver.execute_script("arguments[0].click();", easy_apply_button)
            logger.debug("'Easy Apply' button clicked successfully")

            logger.debug("Passing job information to GPT Answerer")
            self.gpt_answerer.set_job(job)

            logger.debug("Filling out application form")
            self._fill_application_form(job)
            logger.debug(f"Job application process completed successfully for job: {job}")

        except Exception as e:

            tb_str = traceback.format_exc()
            logger.error(f"Failed to apply to job: {job}, error: {tb_str}")

            logger.debug("Discarding application due to failure")
            self._discard_application()

            raise Exception(f"Failed to apply to job! Original exception:\nTraceback:\n{tb_str}")

    def _fill_application_form(self, job: Any):
        """
        Fills the application form page by page until completion or error.
        """
        logger.debug(f"Iterating through application form for job: {job.title}")
        max_pages = 25
        page_count = 0
        last_page_hash = None

        while page_count < max_pages:
            page_count += 1
            logger.info(f"Processing application form page #{page_count}")
            
            # 0. Ensure we are in the best context (modal/iframe)
            self._switch_to_best_context()

            # Detection for "Stuck on same page"
            current_page_source = self.driver.page_source
            current_page_hash = len(current_page_source)
            if last_page_hash is not None and current_page_hash == last_page_hash:
                 # If we are on the same page twice, and nothing was filled/clicked successfully
                 # we should raise an error to avoid the loop.
                 logger.warning("Detected identical page content as the previous iteration.")
                 # (Optional: Add more complex hash check if needed)
            
            last_page_hash = current_page_hash

            # 1. Fill out the current page
            # We pass page_count to allow special handling (like skipping contact info on page 1)
            self.fill_up(job, page_count=page_count)

            # 2. Attempt to move to next page or submit
            if self._next_or_submit():
                logger.info(f"Successfully submitted application for {job.title} after {page_count} pages.")
                return

            # Wait for next page transition (additional buffer)
            time.sleep(random.uniform(1, 2))

        if page_count >= max_pages:
            raise Exception(f"Maximum page limit ({max_pages}) reached during application. Possible infinite loop detected.")

    def _find_easy_apply_button(self, job: Any) -> WebElement:
        """
        Finds the 'Easy Apply' button on a job page with an exhaustive list of selectors.
        """
        logger.debug(f"Searching for 'Easy Apply' button for job: {job.title}")
        self.check_for_premium_redirect(job)
        self._scroll_page(speed='fast')
        time.sleep(1) # Allow page to settle after scroll

        # 1. Check if already applied first to give a better error message
        try:
            already_applied_selectors = [
                "//div[contains(@class, 'jobs-apply-button--top-card')]//span[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'applied')]",
                "//button[contains(@class, 'jobs-apply-button') and @disabled]",
                "//div[contains(@class, 'jobs-unified-top-card')]//span[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'applied')]",
                "//div[contains(@class, 'artdeco-inline-feedback--success') and contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'application sent')]"
            ]
            for xpath in already_applied_selectors:
                elements = self.driver.find_elements(By.XPATH, xpath)
                if elements and any(el.is_displayed() for el in elements):
                    logger.info("It appears you have already applied to this job.")
                    # We still continue to look for the button just in case
                    break
        except Exception as e:
            logger.debug(f"Error checking 'already applied' status: {e}")

        # 2. Comprehensive list of button XPaths
        xpaths = []

        # Try cached XPath first if available
        cached_xpath = self.parameters.get('learned_easy_apply_xpath')
        if cached_xpath:
            xpaths.append(cached_xpath)
            logger.debug(f"Attempting to use learned Easy Apply XPath: {cached_xpath}")

        xpaths.extend([
            "//button[@aria-label='Easy Apply']",
            "//button[contains(@aria-label, 'Easy Apply')]",
            "//button[contains(., 'Easy Apply')]",
            "//button[contains(@class, 'jobs-apply-button') and contains(., 'Easy Apply')]",
            "//button[contains(@class, 'jobs-apply-button--top-card')]//button",
            "//button[contains(@class, 'artdeco-button--primary') and contains(., 'Easy Apply')]",
            "//div[contains(@class, 'jobs-s-apply')]//button",
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'easy apply')]",
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'apply now')]",
            "//span[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'easy apply')]/parent::button",
            "//button[contains(@class, 'jobs-apply-button')]",
            "//a[contains(@class, 'jobs-apply-button') and contains(., 'Easy Apply')]",
            "//button[contains(., 'Apply')]",
            "//a[contains(., 'Apply')]"
        ])

        for xpath in xpaths:
            try:
                logger.debug(f"Searching for 'Easy Apply' button with XPath: {xpath}")
                # Use a longer timeout to handle slow loading pages
                buttons = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_all_elements_located((By.XPATH, xpath))
                )
                
                for button in buttons:
                    try:
                        is_displayed = button.is_displayed()
                        is_enabled = button.is_enabled()
                        
                        if is_displayed and is_enabled:
                            # Improved external site check
                            href = button.get_attribute('href')
                            if button.tag_name == 'a' and href:
                                if 'linkedin.com' not in href and href.startswith('http'):
                                    logger.debug(f"Rejected button at {xpath}: External link {href}")
                                    continue
                            
                            # Log details of the button found
                            text = button.text.strip()
                            logger.info(f"Found clickable button via: {xpath} (Text: '{text}')")

                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                            time.sleep(0.5)
                            
                            clickable_button = WebDriverWait(self.driver, 2).until(
                                EC.element_to_be_clickable(button)
                            )
                            logger.info(f"Button is confirmed clickable.")
                            
                            # Update learned XPath if a new one worked
                            if xpath != cached_xpath:
                                self.parameters['learned_easy_apply_xpath'] = xpath
                                # Save the updated config immediately
                                from main import ConfigValidator
                                ConfigValidator.save_config(self.parameters, self.config_yaml_path)
                                logger.info(f"Learned working 'Easy Apply' XPath and saved to config: {xpath}")

                            return clickable_button
                        else:
                            logger.debug(f"Rejected button at {xpath}: displayed={is_displayed}, enabled={is_enabled}")
                    except Exception as e:
                        logger.debug(f"Button found with XPath '{xpath}' was not clickable: {e}")
                        continue
            except TimeoutException:
                logger.debug(f"XPath '{xpath}' did not yield any elements.")
                continue
            except NoSuchElementException:
                logger.debug(f"NoSuchElementException with XPath '{xpath}'.")
                continue

        logger.error("No 'Easy Apply' or 'Apply now' button found on the page after exhaustive search.")
        raise NoSuchElementException("Could not find a clickable 'Easy Apply' or 'Apply now' button.")


    def _get_job_description(self) -> str:
        """
        Retrieves the full job description from the job page with retries, multiple selectors, and session-like persistence.
        """
        logger.debug("Getting job description")
        max_retries = 3
        
        cached_xpath = self.parameters.get('learned_job_description_xpath')
        if cached_xpath:
            logger.debug(f"Attempting to use learned description XPath from session: {cached_xpath}")

        for attempt in range(max_retries):
            logger.debug(f"Attempt {attempt + 1}/{max_retries} to get job description.")
            
            # Ensure we are scrolled to the top of the job details area first
            try:
                self._scroll_page(speed='fast')
            except: pass

            try:
                # Try to click "see more" button if present
                see_more_xpath = '//button[contains(@aria-label, "see more description")] | //button[contains(., "Show more")] | //button[contains(@class, "jobs-description__footer-button")]'
                see_more_button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, see_more_xpath))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", see_more_button)
                time.sleep(0.5)
                self.driver.execute_script("arguments[0].click();", see_more_button)
                time.sleep(1.5) # Wait for content to expand
                logger.debug(f"Clicked 'see more' button (attempt {attempt + 1}).")
            except (TimeoutException, NoSuchElementException):
                logger.debug(f"'See more' button not found or not clickable (attempt {attempt + 1}).")
            except Exception as e:
                logger.debug(f"Error trying to click 'see more' button: {e}")

            # Define selectors, prioritizing learned one and user suggestions
            selectors = []
            if cached_xpath:
                selectors.append((By.XPATH, cached_xpath))

            # Add standard selectors with more modern LinkedIn classes
            selectors.extend([
                (By.ID, 'job-details'),
                (By.CLASS_NAME, 'jobs-description-content__text'),
                (By.CLASS_NAME, 'jobs-description-content'),
                (By.CLASS_NAME, 'jobs-box__html-content'),
                (By.CLASS_NAME, 'jobs-description__content'),
                (By.CLASS_NAME, 'job-details-jobs-unified-top-card__description-container'),
                (By.CSS_SELECTOR, 'section.scaffold-layout__detail'),
                (By.CSS_SELECTOR, '.jobs-description'),
                (By.XPATH, "//*[@id='job-details']/span"),
                (By.XPATH, "//*[contains(@class, 'jobs-description-content__text')]"),
                (By.XPATH, "//*[contains(@class, 'jobs-box__html-content')]"),
                (By.XPATH, "//div[contains(@class, 'jobs-description')]"),
                (By.CSS_SELECTOR, '.show-more-less-html__markup'),
                (By.TAG_NAME, "article")
            ])

            # Add text-based fallback selectors
            selectors.extend([
                (By.XPATH, "//h2[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'about this job')]/following-sibling::div"),
                (By.XPATH, "//h2[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'job description')]/following-sibling::div"),
                (By.XPATH, "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'about this job')]/.."),
                (By.XPATH, "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'job description')]/..")
            ])

            # Try to find description in top-level content
            for by, value in selectors:
                try:
                    elements = self.driver.find_elements(by, value)
                    for element in elements:
                        if element:
                            # Try multiple ways to get text
                            text = element.text.strip()
                            if not text:
                                text = self.driver.execute_script("return arguments[0].innerText;", element).strip()
                            
                            if text and len(text) > 50:
                                logger.debug(f"Job description found with selector: {by}='{value}' (length: {len(text)})")
                                
                                # Update learned XPath if a new one worked (and it's a stable XPath)
                                if by == By.XPATH and value != cached_xpath:
                                    self.parameters['learned_job_description_xpath'] = value
                                    from main import ConfigValidator
                                    ConfigValidator.save_config(self.parameters, self.config_yaml_path)
                                    logger.info(f"Learned working Job Description XPath and saved to config: {value}")

                                return text
                except: continue

            # If not found, check if description is in an iframe
            try:
                iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                for iframe in iframes:
                    try:
                        self.driver.switch_to.frame(iframe)
                        for by, value in selectors:
                            try:
                                el = self.driver.find_element(by, value)
                                text = el.text.strip() or self.driver.execute_script("return arguments[0].innerText;", el).strip()
                                if text and len(text) > 50:
                                    logger.debug(f"Found description in iframe via {by}='{value}'")
                                    self.driver.switch_to.default_content()
                                    return text
                            except: continue
                        self.driver.switch_to.default_content()
                    except:
                        self.driver.switch_to.default_content()
            except: pass

            # DEEP KEYWORD FALLBACK: Search for common headers and find their containers
            logger.debug("Attempting deep keyword discovery fallback...")
            keywords = ['responsibilities', 'requirements', 'qualifications', 'what you will do', 'about the role', 'ideal candidate']
            for kw in keywords:
                try:
                    kw_xpath = f"//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{kw}')]"
                    kw_elements = self.driver.find_elements(By.XPATH, kw_xpath)
                    for kw_el in kw_elements:
                        if kw_el.is_displayed():
                            # Move up to find a container with substantial text
                            curr = kw_el
                            for _ in range(3): # Traverse up to 3 levels to find the main body
                                try:
                                    curr = curr.find_element(By.XPATH, "..")
                                    p_text = curr.text.strip() or self.driver.execute_script("return arguments[0].innerText;", curr).strip()
                                    if len(p_text) > 300:
                                        logger.debug(f"Deep discovery: found description via keyword '{kw}'")
                                        return p_text
                                except: break
                except: continue

            if attempt < max_retries - 1:
                logger.debug("Description not found yet, retrying...")
                time.sleep(2)

        # FINAL CATCH-ALL: Just grab the biggest text block in the job details area
        try:
            logger.debug("Final fallback: capturing main job details pane text.")
            main_pane = self.driver.find_element(By.XPATH, "//div[contains(@class, 'jobs-search__job-details--container')] | //main")
            text = main_pane.text.strip() or self.driver.execute_script("return arguments[0].innerText;", main_pane).strip()
            if len(text) > 200:
                return text
        except: pass

        logger.error("Job description element not found with any of the selectors after retries.")
        return ""

    def _get_job_recruiter(self):
        """
        Retrieves the recruiter's profile link from the job page, if available.
        """
        logger.debug("Getting job recruiter information")
        try:
            self._scroll_page(speed='slow')
            recruiter_elements = self.driver.find_elements(By.XPATH, '//a[contains(@href, "/in/")]')

            for el in recruiter_elements:
                if "linkedin.com/in/" in el.get_attribute('href'):
                    recruiter_link = el.get_attribute('href')
                    logger.debug(f"Job recruiter link retrieved successfully: {recruiter_link}")
                    return recruiter_link
            return ""
        except NoSuchElementException:
            logger.warning("Failed to retrieve recruiter information.")
            return ""

    def _scroll_page(self, speed: str = 'medium') -> None:
        """
        Scrolls the page to ensure all elements are loaded, with adjustable speed.

        :param speed: 'fast', 'medium', or 'slow' to control scroll behavior.
        """
        logger.debug(f"Scrolling the page with '{speed}' speed.")
        
        scroll_increment_js = {
            'fast': 'window.innerHeight * 0.9',
            'medium': 'window.innerHeight * 0.5',
            'slow': 'window.innerHeight * 0.2'
        }
        
        scrollable_elements_xpaths = [
            "//div[contains(@class, 'jobs-search__job-details--container')]",
            "//div[contains(@class, 'job-view-layout')]",
            "//section[contains(@class, 'scaffold-layout__detail')]",
            "//div[contains(@class, 'job-details-jobs-unified-top-card')]",
            "//main"
        ]

        # Try to use learned scrollable element XPath
        cached_xpath = self.parameters.get('learned_scrollable_element_xpath')
        if cached_xpath:
            scrollable_elements_xpaths.insert(0, cached_xpath)
            logger.debug(f"Attempting to use learned scrollable XPath: {cached_xpath}")

        scrollable_element = None
        working_xpath = None
        for xpath in scrollable_elements_xpaths:
            try:
                scrollable_element = self.driver.find_element(By.XPATH, xpath)
                if scrollable_element.is_displayed():
                    working_xpath = xpath
                    break
            except NoSuchElementException:
                continue
        
        if not scrollable_element:
            try:
                scrollable_element = self.driver.find_element(By.TAG_NAME, 'html')
            except: pass

        if scrollable_element:
            # Save learned XPath if it's not the one we already had and it's not 'html'
            if working_xpath and working_xpath != cached_xpath:
                self.parameters['learned_scrollable_element_xpath'] = working_xpath
                from main import ConfigValidator
                ConfigValidator.save_config(self.parameters, self.config_yaml_path)
                logger.info(f"Learned working Scrollable Element XPath and saved to config: {working_xpath}")

            utils.scroll_slow(self.driver, scrollable_element, step=int(float(self.driver.execute_script("return window.innerHeight;") or 500) * 0.5))
            utils.scroll_slow(self.driver, scrollable_element, step=int(float(self.driver.execute_script("return window.innerHeight;") or 500) * 0.5), reverse=True)
        else:
            logger.warning("No scrollable element found to scroll.")


    def _nuke_obstructors(self):
        """Remove overlays that block clicks."""
        try:
            self.driver.execute_script("""
                (function() {
                    var overlays = document.querySelectorAll('div, span');
                    overlays.forEach(o => {
                        var style = window.getComputedStyle(o);
                        if (parseInt(style.zIndex) > 10 && (o.innerText.trim() === '')) {
                            o.style.pointerEvents = 'none';
                        }
                    });
                })();
            """)
        except: pass

    def _switch_to_best_context(self) -> bool:
        """Find the best context (Main, Iframe, or Shadow-Iframe) containing the application form."""

        # 0. Check Cache First
        cached_context = self.selector_cache.get('context_strategy')
        if cached_context:
            try:
                self.driver.switch_to.default_content()
                if cached_context['type'] == 'main':
                    if self._is_form_present(): return True
                elif cached_context['type'] == 'iframe':
                     iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                     for iframe in iframes:
                         try:
                             self.driver.switch_to.frame(iframe)
                             if self._is_form_present(): return True
                             self.driver.switch_to.default_content()
                         except: self.driver.switch_to.default_content()
                elif cached_context['type'] == 'shadow_iframe':
                    host = self.driver.find_element(By.CSS_SELECTOR, cached_context['host_selector'])
                    shadow_root = self.driver.execute_script("return arguments[0].shadowRoot", host)
                    if shadow_root:
                        iframes = self.driver.execute_script("return arguments[0].querySelectorAll('iframe')", shadow_root)
                        for iframe in iframes:
                            try:
                                self.driver.switch_to.frame(iframe)
                                if self._is_form_present(): return True
                                self.driver.switch_to.default_content()
                            except: pass
            except: 
                pass # Cache invalid, proceed to sweep

        # 1. Start from Main Content
        self.driver.switch_to.default_content()

        def check_and_cache(context_type, host_selector=None):
            if self._is_form_present():
                self.selector_cache.update('context_strategy', {
                    'type': context_type,
                    'host_selector': host_selector
                })
                logger.info(f"Form context identified: {context_type}")
                return True
            return False

        # Try multiple times with small delays for slow loading modals
        for attempt in range(4):
            # A. Check Standard Iframes First (Common for Easy Apply)
            try:
                iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                for iframe in iframes:
                    try:
                        self.driver.switch_to.frame(iframe)
                        if check_and_cache('iframe'): return True
                        self.driver.switch_to.default_content()
                    except:
                        self.driver.switch_to.default_content()
            except: pass

            # B. Check Shadow DOM Interop (LinkedIn Modern UI)
            try:
                interop_hosts = self.driver.find_elements(By.CSS_SELECTOR, "#interop-outlet, [data-testid='interop-outlet'], .interop-outlet, #artdeco-modal-outlet-shadow-root")
                for host in interop_hosts:
                    try:
                        shadow_root = self.driver.execute_script("return arguments[0].shadowRoot", host)
                        if shadow_root:
                            iframes = self.driver.execute_script("return arguments[0].querySelectorAll('iframe')", shadow_root)
                            for iframe in iframes:
                                try:
                                    self.driver.switch_to.frame(iframe)
                                    if check_and_cache('shadow_iframe', host_selector=f"#{host.get_attribute('id')}" if host.get_attribute('id') else ".interop-outlet"): 
                                        return True
                                    self.driver.switch_to.default_content()
                                except: pass
                    except: pass
            except: 
                self.driver.switch_to.default_content()

            # C. Check Main Context last as fallback
            if check_and_cache('main'): return True

            if attempt < 3:
                time.sleep(1.5) # Wait for potential modal/iframe load

        logger.warning("Could not identify a specific context containing the form. Staying in main context.")
        return False

    def _is_form_present(self):
        """Helper to validate if current context has form elements."""
        try:
            # 1. Look for definitive LinkedIn Easy Apply modal indicators
            form_indicators = [
                "//div[contains(@class, 'jobs-easy-apply-modal')]",
                "//div[contains(@class, 'jobs-easy-apply-content')]",
                "//div[@data-test-form-element]", 
                "//div[@data-test-form-section]", 
                "//*[@id='ember239']",
                "//button[@data-easy-apply-next-button]",
                "//button[@data-control-name='continue_unify']",
                "//button[@data-control-name='submit_unify']"
            ]
            if self.driver.find_elements(By.XPATH, " | ".join(form_indicators)):
                return True

            # 2. Check for form buttons with normalized text (case insensitive)
            # This handles "Next", "Submit", "Review", "Continue", "Finish"
            button_indicator = (
                "//button[contains(@class, 'artdeco-button--primary') and ("
                "contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'next') or "
                "contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'submit') or "
                "contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'review') or "
                "contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'continue') or "
                "contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'finish')"
                ")]"
            )
            if self.driver.find_elements(By.XPATH, button_indicator):
                return True

            # 3. Fallback: Check for visible inputs or selects that are not hidden
            inputs = self.driver.find_elements(By.TAG_NAME, "input")
            selects = self.driver.find_elements(By.TAG_NAME, "select")
            if any(i.is_displayed() and i.get_attribute("type") != "hidden" for i in inputs) or \
               any(s.is_displayed() for s in selects):
                return True

            return False
        except: return False

    def _find_primary_button(self) -> Tuple[Optional[WebElement], Optional[str]]:
        """
        Hyper-aggressive dynamic search for the primary action button.
        Scans all interactive elements and filters by text and attributes in Python.
        """
        # Comprehensive list of navigational keywords, prioritized by importance
        keywords = [
            'next', 'submit', 'review', 'continue', 'finish', 'apply', 
            'step', 'proceed', 'done', 'go', 'save', 'agree'
        ]
        
        # 1. Trusted Strategy Pass - Prioritize known good patterns
        strategies = [
            (By.XPATH, "//button[contains(@class,'artdeco-button--primary') and not(@disabled)]"),
            (By.XPATH, "//button[@data-easy-apply-next-button]"),
            (By.XPATH, "//button[@data-control-name='continue_unify']"),
            (By.XPATH, "//button[@data-control-name='submit_unify']"),
            (By.CSS_SELECTOR, "button.artdeco-button--primary"),
            (By.XPATH, "//button[contains(@class, 'primary') and @type='submit']"),
            # Only look for primary buttons that actually contain navigation keywords
            (By.XPATH, "//button[contains(@class, 'primary') and (contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'next') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'submit') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'review') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'continue'))]"),
            (By.XPATH, "//input[@type='submit']"),
            (By.XPATH, "//footer//button")
        ]
        
        for by, selector in strategies:
            try:
                elements = self.driver.find_elements(by, selector)
                for el in elements:
                    if el.is_displayed() and el.is_enabled():
                        text = (el.text or el.get_attribute('innerText') or "").lower()
                        if not keywords or any(k in text for k in keywords):
                            logger.debug(f"Found primary button via strategy: {selector}")
                            return el, f"trusted_{selector}"
            except: continue

        # 2. Hyper-Aggressive pass: Scan ALL clickable-looking elements
        try:
            # Broad search for anything that could be a button or an anchor acting as one
            potential_btns = self.driver.find_elements(By.CSS_SELECTOR, "button, [role='button'], input[type='submit'], input[type='button'], .artdeco-button, a.artdeco-button")
            
            disabled_fallback = None
            best_candidate = None
            
            for btn in potential_btns:
                try:
                    if not btn.is_displayed(): continue
                    
                    # Collate all text-like attributes
                    attrs = [
                        btn.text,
                        btn.get_attribute('innerText'),
                        btn.get_attribute('aria-label'),
                        btn.get_attribute('value'),
                        btn.get_attribute('title'),
                        btn.get_attribute('name'),
                        btn.get_attribute('id')
                    ]
                    combined_text = " ".join([str(a) for a in attrs if a]).lower()
                    
                    if any(k in combined_text for k in keywords):
                        if btn.is_enabled():
                            # If it has "primary" in the class, it's our top choice
                            cls = btn.get_attribute("class") or ""
                            if "primary" in cls.lower():
                                return btn, "dynamic_aggressive_primary"
                            # Otherwise, keep it as a very good candidate
                            best_candidate = btn
                        else:
                            if not disabled_fallback:
                                disabled_fallback = btn
                except: continue
            
            if best_candidate:
                return best_candidate, "dynamic_aggressive_candidate"
            
            if disabled_fallback:
                return disabled_fallback, "dynamic_aggressive_disabled"

        except Exception as e:
            logger.debug(f"Hyper-aggressive button search failed: {e}")

        return None, None

    def _find_button_recursive_js(self) -> Optional[WebElement]:
        """Uses JavaScript to recursively search for the primary button through Shadow DOMs."""
        script = """
            function findPrimaryButton(root) {
                const keywords = ['next', 'submit', 'review', 'continue', 'finish', 'apply', 'agree', 'step', 'save', 'proceed'];
                
                // 1. Try standard selectors first in this root
                const primaryButtons = root.querySelectorAll('button.artdeco-button--primary, button[data-easy-apply-next-button], .artdeco-button--primary, button[type="submit"]');
                for (let btn of primaryButtons) {
                    const text = (btn.innerText || btn.textContent || btn.getAttribute('aria-label') || btn.getAttribute('title') || "").toLowerCase();
                    if (keywords.some(k => text.includes(k)) && btn.offsetParent !== null) {
                        return btn;
                    }
                }
                
                // 2. Broad search for any button-like element
                const allButtons = root.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"], a.artdeco-button');
                for (let btn of allButtons) {
                    const text = (btn.innerText || btn.textContent || btn.getAttribute('aria-label') || btn.getAttribute('value') || btn.getAttribute('title') || "").toLowerCase();
                    if (keywords.some(k => text.includes(k)) && btn.offsetParent !== null) {
                        return btn;
                    }
                }

                // 3. Recurse into Shadow DOMs
                const hosts = root.querySelectorAll('*');
                for (let host of hosts) {
                    if (host.shadowRoot) {
                        const found = findPrimaryButton(host.shadowRoot);
                        if (found) return found;
                    }
                }
                return null;
            }
            return findPrimaryButton(document);
        """
        try:
            return self.driver.execute_script(script)
        except Exception as e:
            logger.debug(f"Recursive JS button search failed: {e}")
            return None

    def _recursive_iframe_search(self) -> Tuple[Optional[WebElement], Optional[str]]:
        """Recursively searches through all iframes for the primary button."""
        def search_frames():
            # Try to find the button in the current frame
            btn, strategy = self._find_primary_button()
            if btn: return btn, strategy
            
            # Try recursive JS search in the current frame
            btn = self._find_button_recursive_js()
            if btn: return btn, "js_recursive_in_iframe"
            
            # Recurse into child frames
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                try:
                    self.driver.switch_to.frame(iframe)
                    result = search_frames()
                    if result[0]: return result
                    self.driver.switch_to.parent_frame()
                except:
                    try: self.driver.switch_to.parent_frame()
                    except: pass
                    continue
            return None, None

        # Start from top-level and recurse
        original_frame = None # Simplified, just go to default first
        self.driver.switch_to.default_content()
        return search_frames()

    def _next_or_submit(self) -> bool:
        logger.debug("Attempting to advance to next page or submit")
        
        # Multi-attempt loop with Deep Context Search
        max_attempts = 3
        next_button = None
        
        for attempt in range(max_attempts):
            # 1. Standard Context Switch and Nuke Obstructors
            self._switch_to_best_context()
            self._nuke_obstructors()

            # 2. Standard Search
            next_button, strategy = self._find_primary_button()
            if next_button: 
                logger.info(f"Primary button found via strategy: {strategy}")
                break

            # 3. Recursive Iframe Search
            logger.debug(f"Primary button not found (attempt {attempt+1}). Performing Recursive Iframe Search...")
            next_button, strategy = self._recursive_iframe_search()
            if next_button:
                logger.info(f"Primary button found in iframe via strategy: {strategy}")
                break
            
            # 4. Recursive JS Search (Shadow DOM traversal)
            self.driver.switch_to.default_content()
            next_button = self._find_button_recursive_js()
            if next_button:
                logger.info("Primary button found via Recursive JS Search (Shadow DOM).")
                break

            time.sleep(1.5)

        if not next_button:
            validation_errors = self._get_validation_error_texts()
            if validation_errors:
                 raise Exception(f"Could not find 'Next' or 'Submit' button. The form has the following validation errors: {validation_errors}")
            
            # Final desperate check: Scroll up and down to trigger lazy-loaded buttons
            logger.debug("Final desperate scroll-and-search for buttons...")
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            next_button, _ = self._find_primary_button()
            if not next_button:
                next_button = self._find_button_recursive_js()
            
            if not next_button:
                raise NoSuchElementException("No 'Next', 'Submit', or 'Review' button found on the current application page.")

        # Check if button is actually clickable
        if not next_button.is_enabled():
            logger.warning("Primary button found but it is currently DISABLED.")
            validation_errors = self._get_validation_error_texts()
            if validation_errors:
                 raise Exception(f"The 'Next'/'Submit' button is disabled. Please fix these errors: {validation_errors}")
            raise Exception("The 'Next'/'Submit' button is disabled. This usually happens when a required field is left empty or has an invalid value.")

        button_text = next_button.text.lower()
        current_page_source = self.driver.page_source
        
        # Robust Click Strategy
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
            time.sleep(0.5)
            
            # Attempt standard click, fallback to JS click if intercepted
            try:
                if not utils.safe_click(self.driver, next_button):
                     logger.debug("Safe click blocked by popup. Forcing click via JS...")
                     self.driver.execute_script("arguments[0].click();", next_button)
            except Exception:
                logger.debug("Standard click failed, using JS click fallback.")
                self.driver.execute_script("arguments[0].click();", next_button)
        except Exception as e:
            logger.error(f"Failed to click the primary button: {e}")
            raise e

        if 'submit' in button_text or 'finish' in button_text:
            logger.info("Submit/Finish button detected. Application should be complete.")
            time.sleep(2)
            return True

        # Wait for page transition and verify progress
        # We use a multi-stage wait to be both responsive and patient
        max_wait = 10
        start_wait = time.time()
        
        while time.time() - start_wait < max_wait:
            time.sleep(1.5)
            new_page_source = self.driver.page_source
            
            # If the page source changed, we've moved forward
            if len(new_page_source) != len(current_page_source):
                logger.debug("Detected page content change, proceeding.")
                return False
            
            # If it hasn't changed, check for validation errors
            if self._has_validation_errors():
                logger.error("Page did not change after clicking button and validation errors are present.")
                raise Exception("Form submission halted due to validation errors.")
            
            # If it hasn't changed and no errors, maybe the button needs another click?
            # Or maybe it's still loading. We continue waiting.
            logger.debug(f"Still waiting for page transition... ({int(time.time() - start_wait)}s)")

        # If we reached here, the page didn't change for 10 seconds and no errors found.
        # Final check: Did the "Next" button become disabled or disappear?
        try:
            self._switch_to_best_context()
            btn, _ = self._find_primary_button()
            if not btn or not btn.is_displayed():
                logger.debug("Primary button disappeared, assuming page changed successfully.")
                return False
        except:
            pass

        logger.warning("Page did not change after 10 seconds of waiting. Proceeding cautiously.")
        return False
    def _unfollow_company(self) -> None:
        try:
            logger.debug("Unfollowing company")
            follow_checkbox = self.driver.find_element(
                By.XPATH, "//label[contains(.,'to stay up to date with their page.')]")
            follow_checkbox.click()
        except Exception as e:
            logger.debug(f"Failed to unfollow company: {e}")

    def _get_validation_error_texts(self) -> List[str]:
        """Collect all visible validation error messages from the page."""
        error_texts = []
        error_selectors = [
            (By.CLASS_NAME, 'artdeco-inline-feedback--error'),
            (By.CSS_SELECTOR, '.artdeco-inline-feedback--error'),
            (By.CSS_SELECTOR, 'div[data-test-form-element-error-messages]'),
            (By.CSS_SELECTOR, 'span[data-test-form-element-error-message]'),
            (By.XPATH, "//*[contains(@class, 'error') and contains(@class, 'feedback')]"),
            (By.XPATH, "//*[contains(@class, 'form-error')]"),
            (By.XPATH, "//*[contains(@class, 'error-message')]"),
            (By.XPATH, "//*[contains(@class, 'validation-error')]"),
            (By.XPATH, "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'required') and contains(@class, 'error')]")
        ]

        # Check current context
        for by, selector in error_selectors:
            try:
                errors = self.driver.find_elements(by, selector)
                visible_errors = [e.text.strip() for e in errors if e.is_displayed() and e.text.strip()]
                error_texts.extend(visible_errors)
            except: continue
            
        # Check Shadow DOM in current context
        try:
            shadow_hosts = self.driver.find_elements(By.CSS_SELECTOR, "[id*='interop-outlet'], [id*='shadow-root']")
            for host in shadow_hosts:
                try:
                    shadow_root = self.driver.execute_script("return arguments[0].shadowRoot", host)
                    if shadow_root:
                        for by, selector in error_selectors:
                            errors = shadow_root.find_elements(by, selector)
                            visible_errors = [e.text.strip() for e in errors if e.is_displayed() and e.text.strip()]
                            error_texts.extend(visible_errors)
                except: pass
        except: pass

        # Deduplicate while preserving order
        unique_errors = list(dict.fromkeys(error_texts))
        return unique_errors

    def _has_validation_errors(self) -> bool:
        """Check for validation errors in the current context."""
        errors = self._get_validation_error_texts()
        if errors:
            logger.warning(f"Validation errors found: {errors}")
            return True
        return False

    def _discard_application(self) -> None:
        logger.debug("Attempting to discard application modal if present")
        try:
            # Check for common modal close buttons
            dismiss_selectors = [
                (By.CLASS_NAME, 'artdeco-modal__dismiss'),
                (By.XPATH, "//button[contains(@aria-label, 'Dismiss')]"),
                (By.XPATH, "//button[contains(@class, 'artdeco-modal__dismiss')]")
            ]
            
            dismiss_button = None
            for by, selector in dismiss_selectors:
                try:
                    elements = self.driver.find_elements(by, selector)
                    for el in elements:
                        if el.is_displayed():
                            dismiss_button = el
                            break
                    if dismiss_button: break
                except: continue
                
            if dismiss_button:
                dismiss_button.click()
                time.sleep(random.uniform(2, 3))
                # Handle the confirmation dialog
                confirm_buttons = self.driver.find_elements(By.CLASS_NAME, 'artdeco-modal__confirm-dialog-btn')
                if not confirm_buttons:
                    # Try a broader search for confirmation buttons
                    confirm_buttons = self.driver.find_elements(By.XPATH, "//button[contains(., 'Discard') or contains(., 'Confirm')]")
                
                for btn in confirm_buttons:
                    if btn.is_displayed():
                        btn.click()
                        logger.debug("Application discarded successfully.")
                        time.sleep(2)
                        return
            else:
                logger.debug("No active application modal found to discard.")
        except Exception as e:
            logger.warning(f"Failed to discard application: {e}")

    def fill_up(self, job, page_count: int = 0) -> None:
        logger.debug(f"Filling up form sections for job: {job}, Page: {page_count}")

        try:
            # 1. Handle any file uploads directly first (often not in pb4 anymore)
            try:
                upload_inputs = self.driver.find_elements(By.XPATH, "//input[@type='file']")
                if upload_inputs:
                    logger.debug(f"Found {len(upload_inputs)} file upload inputs globally. Processing...")
                    self._handle_upload_fields(None, job)
            except Exception as e:
                logger.warning(f"Error checking global file uploads: {e}")

            # 2. Process all standard question fields (dropdowns, text, radio)
            self._fill_additional_questions(page_count=page_count)
        except Exception as e:
            logger.error(f"Failed to find or process form elements: {e}")

    def _process_form_element(self, element: WebElement, job) -> None:
        logger.debug("Processing form element")
        if self._is_upload_field(element):
            self._handle_upload_fields(element, job)
        else:
            self._fill_additional_questions()

    def _handle_dropdown_fields(self, element: WebElement) -> None:
        logger.debug("Handling dropdown fields")

        dropdown = element.find_element(By.TAG_NAME, 'select')
        select = Select(dropdown)
        dropdown_id = dropdown.get_attribute('id')
        if 'phoneNumber-Country' in dropdown_id:
            country = self.resume_generator_manager.get_resume_country()
            if country:
                try:
                    select.select_by_value(country)
                    logger.debug(f"Selected phone country: {country}")
                    return True
                except NoSuchElementException:
                    logger.warning(f"Country {country} not found in dropdown options")

        options = [option.text for option in select.options]
        logger.debug(f"Dropdown options found: {options}")

        parent_element = dropdown.find_element(By.XPATH, '../..')

        label_elements = parent_element.find_elements(By.TAG_NAME, 'label')
        if label_elements:
            question_text = label_elements[0].text.lower()
        else:
            question_text = "unknown"

        logger.debug(f"Detected question text: {question_text}")

        existing_answer = None
        for item in self.all_data:
            if self._sanitize_text(question_text) in item['question'] and item['type'] == 'dropdown':
                existing_answer = item['answer']
                break

        if existing_answer:
            logger.debug(f"Found existing answer for question '{question_text}': {existing_answer}")
        else:
            logger.debug(f"No existing answer found, querying model for: {question_text}")
            existing_answer = self.gpt_answerer.answer_question_from_options(question_text, options)
            logger.debug(f"Model provided answer: {existing_answer}")
            self._save_questions_to_json({'type': 'dropdown', 'question': question_text, 'answer': existing_answer})

        if existing_answer in options:
            select.select_by_visible_text(existing_answer)
            logger.debug(f"Selected option: {existing_answer}")
        else:
            logger.error(f"Answer '{existing_answer}' is not a valid option in the dropdown")
            raise Exception(f"Invalid option selected: {existing_answer}")

    def _is_upload_field(self, element: WebElement) -> bool:
        is_upload = bool(element.find_elements(By.XPATH, ".//input[@type='file']"))
        logger.debug(f"Element is upload field: {is_upload}")
        return is_upload

    def _handle_upload_fields(self, element: WebElement, job) -> None:
        logger.debug("Handling upload fields")

        try:
            show_more_button = self.driver.find_element(By.XPATH,
                                                        "//button[contains(@aria-label, 'Show more resumes')]")
            show_more_button.click()
            logger.debug("Clicked 'Show more resumes' button")
        except NoSuchElementException:
            logger.debug("'Show more resumes' button not found, continuing...")

        file_upload_elements = self.driver.find_elements(By.XPATH, "//input[@type='file']")
        for element in file_upload_elements:
            parent = element.find_element(By.XPATH, "..")
            self.driver.execute_script("arguments[0].classList.remove('hidden')", element)

            output = self.gpt_answerer.resume_or_cover(parent.text.lower())
            if 'resume' in output:
                logger.debug("Uploading resume")
                if self.resume_path is not None and self.resume_path.resolve().is_file():
                    element.send_keys(str(self.resume_path.resolve()))
                    logger.debug(f"Resume uploaded from path: {self.resume_path.resolve()}")
                else:
                    logger.debug("Resume path not found or invalid, generating new resume")
                    self._create_and_upload_resume(element, job)
            elif 'cover' in output:
                logger.debug("Uploading cover letter")
                self._create_and_upload_cover_letter(element, job)

        logger.debug("Finished handling upload fields")

    def _create_and_upload_resume(self, element, job):
        logger.debug("Starting the process of creating and uploading resume.")
        folder_path = 'generated_cv'

        try:
            if not os.path.exists(folder_path):
                logger.debug(f"Creating directory at path: {folder_path}")
            os.makedirs(folder_path, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create directory: {folder_path}. Error: {e}")
            raise

        while True:
            try:
                timestamp = int(time.time())
                file_path_pdf = os.path.join(folder_path, f"CV_{timestamp}.pdf")
                logger.debug(f"Generated file path for resume: {file_path_pdf}")

                logger.debug(f"Generating resume for job: {job.title} at {job.company}")
                
                # Optimized: Use the batched artifact generation to get all tailored sections in one call
                # This stays within 15 RPM Gemini limit by avoiding 7+ individual section calls
                resume_yaml = getattr(self.gpt_answerer.job_application_profile, 'yaml_str', "") if hasattr(self.gpt_answerer, 'job_application_profile') else ""
                artifacts = self.gpt_answerer.generate_application_artifacts(job.description, resume_yaml)
                resume_sections = artifacts.get('resume_sections')
                
                resume_pdf_base64 = self.resume_generator_manager.pdf_base64(
                    job_description_text=job.description,
                    precomputed_sections=resume_sections
                )
                with open(file_path_pdf, "xb") as f:
                    f.write(base64.b64decode(resume_pdf_base64))
                logger.debug(f"Resume successfully generated and saved to: {file_path_pdf}")

                break
            except HTTPStatusError as e:
                if e.response.status_code == 429:

                    retry_after = e.response.headers.get('retry-after')
                    retry_after_ms = e.response.headers.get('retry-after-ms')

                    if retry_after:
                        wait_time = int(retry_after)
                        logger.warning(f"Rate limit exceeded, waiting {wait_time} seconds before retrying...")
                    elif retry_after_ms:
                        wait_time = int(retry_after_ms) / 1000.0
                        logger.warning(f"Rate limit exceeded, waiting {wait_time} milliseconds before retrying...")
                    else:
                        wait_time = 20
                        logger.warning(f"Rate limit exceeded, waiting {wait_time} seconds before retrying...")

                    time.sleep(wait_time)
                else:
                    logger.error(f"HTTP error: {e}")
                    raise

            except Exception as e:
                logger.error(f"Failed to generate resume: {e}")
                tb_str = traceback.format_exc()
                logger.error(f"Traceback: {tb_str}")
                if "RateLimitError" in str(e):
                    logger.warning("Rate limit error encountered, retrying...")
                    time.sleep(20)
                else:
                    raise

        file_size = os.path.getsize(file_path_pdf)
        max_file_size = 2 * 1024 * 1024  # 2 MB
        logger.debug(f"Resume file size: {file_size} bytes")
        if file_size > max_file_size:
            logger.error(f"Resume file size exceeds 2 MB: {file_size} bytes")
            raise ValueError("Resume file size exceeds the maximum limit of 2 MB.")

        allowed_extensions = {'.pdf', '.doc', '.docx'}
        file_extension = os.path.splitext(file_path_pdf)[1].lower()
        logger.debug(f"Resume file extension: {file_extension}")
        if file_extension not in allowed_extensions:
            logger.error(f"Invalid resume file format: {file_extension}")
            raise ValueError("Resume file format is not allowed. Only PDF, DOC, and DOCX formats are supported.")

        try:
            logger.debug(f"Uploading resume from path: {file_path_pdf}")
            element.send_keys(os.path.abspath(file_path_pdf))
            job.pdf_path = os.path.abspath(file_path_pdf)
            time.sleep(2)
            logger.debug(f"Resume created and uploaded successfully: {file_path_pdf}")
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"Resume upload failed: {tb_str}")
            raise Exception(f"Upload failed: \nTraceback:\n{tb_str}")

    def _create_and_upload_cover_letter(self, element: WebElement, job) -> None:
        logger.debug("Starting the process of creating and uploading cover letter.")

        cover_letter_text = self.gpt_answerer.answer_question_textual_wide_range("Write a cover letter")

        folder_path = 'generated_cv'

        try:

            if not os.path.exists(folder_path):
                logger.debug(f"Creating directory at path: {folder_path}")
            os.makedirs(folder_path, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create directory: {folder_path}. Error: {e}")
            raise

        while True:
            try:
                timestamp = int(time.time())
                file_path_pdf = os.path.join(folder_path, f"Cover_Letter_{timestamp}.pdf")
                logger.debug(f"Generated file path for cover letter: {file_path_pdf}")

                c = canvas.Canvas(file_path_pdf, pagesize=A4)
                page_width, page_height = A4
                text_object = c.beginText(50, page_height - 50)
                text_object.setFont("Helvetica", 12)

                max_width = page_width - 100
                bottom_margin = 50
                available_height = page_height - bottom_margin - 50

                def split_text_by_width(text, font, font_size, max_width):
                    wrapped_lines = []
                    for line in text.splitlines():

                        if stringWidth(line, font, font_size) > max_width:
                            words = line.split()
                            new_line = ""
                            for word in words:
                                if stringWidth(new_line + word + " ", font, font_size) <= max_width:
                                    new_line += word + " "
                                else:
                                    wrapped_lines.append(new_line.strip())
                                    new_line = word + " "
                            wrapped_lines.append(new_line.strip())
                        else:
                            wrapped_lines.append(line)
                    return wrapped_lines

                lines = split_text_by_width(cover_letter_text, "Helvetica", 12, max_width)

                for line in lines:
                    text_height = text_object.getY()
                    if text_height > bottom_margin:
                        text_object.textLine(line)
                    else:

                        c.drawText(text_object)
                        c.showPage()
                        text_object = c.beginText(50, page_height - 50)
                        text_object.setFont("Helvetica", 12)
                        text_object.textLine(line)

                c.drawText(text_object)
                c.save()
                logger.debug(f"Cover letter successfully generated and saved to: {file_path_pdf}")

                break
            except Exception as e:
                logger.error(f"Failed to generate cover letter: {e}")
                tb_str = traceback.format_exc()
                logger.error(f"Traceback: {tb_str}")
                raise

        file_size = os.path.getsize(file_path_pdf)
        max_file_size = 2 * 1024 * 1024  # 2 MB
        logger.debug(f"Cover letter file size: {file_size} bytes")
        if file_size > max_file_size:
            logger.error(f"Cover letter file size exceeds 2 MB: {file_size} bytes")
            raise ValueError("Cover letter file size exceeds the maximum limit of 2 MB.")

        allowed_extensions = {'.pdf', '.doc', '.docx'}
        file_extension = os.path.splitext(file_path_pdf)[1].lower()
        logger.debug(f"Cover letter file extension: {file_extension}")
        if file_extension not in allowed_extensions:
            logger.error(f"Invalid cover letter file format: {file_extension}")
            raise ValueError("Cover letter file format is not allowed. Only PDF, DOC, and DOCX formats are supported.")

        try:

            logger.debug(f"Uploading cover letter from path: {file_path_pdf}")
            element.send_keys(os.path.abspath(file_path_pdf))
            job.cover_letter_path = os.path.abspath(file_path_pdf)
            time.sleep(2)
            logger.debug(f"Cover letter created and uploaded successfully: {file_path_pdf}")
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"Cover letter upload failed: {tb_str}")
            raise Exception(f"Upload failed: \nTraceback:\n{tb_str}")

    def _extract_section_info(self, section: WebElement) -> Optional[Dict[str, Any]]:
        try:
            # Check for radio buttons (multiple selector strategies)
            radios = section.find_elements(By.CLASS_NAME, 'fb-text-selectable__option')
            if not radios:
                radios = section.find_elements(By.CSS_SELECTOR, '[data-test-text-selectable-option]')
            if not radios:
                radios = section.find_elements(By.XPATH, ".//fieldset//div[.//input[@type='radio']]")
            if radios:
                question_text = section.text.split('\n')[0].lower().strip()
                options = [radio.text.lower().strip() for radio in radios if radio.text.strip()]
                if question_text and options:
                    return {"id": question_text, "text": question_text, "type": "radio", "options": options}

            # Check for dropdowns
            dropdowns = section.find_elements(By.TAG_NAME, 'select')
            if not dropdowns:
                dropdowns = section.find_elements(By.CSS_SELECTOR, '[data-test-text-entity-list-form-select]')
            if dropdowns:
                dropdown = dropdowns[0]
                select = Select(dropdown)
                options = [option.text.strip() for option in select.options if option.text.strip()]
                label_elements = section.find_elements(By.TAG_NAME, 'label')
                question_text = label_elements[0].text.lower().strip() if label_elements else ""
                if not question_text:
                    question_text = (dropdown.get_attribute('aria-label') or "").lower().strip()
                if not question_text:
                    question_text = "unknown"
                return {"id": question_text, "text": question_text, "type": "dropdown", "options": options}

            # Check for text/numeric inputs
            text_fields = section.find_elements(By.TAG_NAME, 'input') + section.find_elements(By.TAG_NAME, 'textarea')
            text_fields = [tf for tf in text_fields if (tf.get_attribute('type') or 'text') not in ['hidden', 'checkbox', 'radio', 'file', 'submit', 'button']]
            if text_fields:
                text_field = text_fields[0]
                label_elements = section.find_elements(By.TAG_NAME, 'label')
                question_text = label_elements[0].text.lower().strip() if label_elements else ""
                if not question_text:
                    question_text = (text_field.get_attribute('aria-label') or "").lower().strip()
                if not question_text:
                    question_text = (text_field.get_attribute('placeholder') or "").lower().strip()
                if not question_text:
                    return None
                is_numeric = self._is_numeric_field(text_field, question_text)
                return {"id": question_text, "text": question_text, "type": "numeric" if is_numeric else "textbox", "options": []}
            return None
        except Exception:
            return None

    def _find_form_sections(self) -> list:
        """Find form question sections in the current context (Main or Iframe)."""
        # 1. Search current context
        sections = self.driver.find_elements(By.XPATH, "//div[@data-test-form-element] | //div[@data-test-form-section] | //div[contains(@class, 'fb-dash-form-element')] | //div[contains(@class, 'jobs-easy-apply-form-section__grouping')]")
        
        # 2. Check if elements are hidden in a Shadow DOM within this context
        if not sections:
            try:
                shadow_hosts = self.driver.find_elements(By.CSS_SELECTOR, "[id*='interop-outlet'], [id*='shadow-root']")
                for host in shadow_hosts:
                    shadow_root = self.driver.execute_script("return arguments[0].shadowRoot", host)
                    if shadow_root:
                        sections = shadow_root.find_elements(By.CSS_SELECTOR, "div[data-test-form-element], div.fb-dash-form-element, section.fb-dash-form-section")
                        if sections: break
            except: pass

        if sections:
            logger.debug(f"Found {len(sections)} sections in current context.")
            return sections

        # 3. Last resort fallbacks
        modal_xpaths = [
            "//div[contains(@class, 'jobs-easy-apply-content')]//div[contains(@class, 'fb-dash-form-element')]",
            "//div[contains(@class, 'artdeco-modal')]//div[./label and (.//*[self::input or self::select or self::textarea])]",
            "//form//div[./label and (.//*[self::input or self::select or self::textarea or self::fieldset])]",
        ]
        for xpath in modal_xpaths:
            sections = self.driver.find_elements(By.XPATH, xpath)
            if sections: return sections

        return []

    def _fill_additional_questions(self, page_count: int = 0) -> None:
        logger.debug(f"Filling additional questions (Page {page_count})")
        form_sections = self._find_form_sections()

        if not form_sections:
            logger.debug("No form sections detected on this page.")
            return

        # Pre-batch unanswered questions for a single LLM call
        questions_to_batch = []
        sanitized_batch_keys = {self._sanitize_text(k) for k in self.batch_answers.keys()}
        
        for section in form_sections:
            try:
                # SKIP LOGIC: If page 1, skip contact info to avoid overwriting pre-filled data
                if page_count == 1:
                    section_text = section.text.lower()
                    if any(x in section_text for x in ['phone', 'email', 'country', 'mobile']):
                        logger.debug(f"Skipping contact info on page 1: {section_text[:30]}...")
                        continue

                info = self._extract_section_info(section)
                if info:
                    sanitized_text = self._sanitize_text(info['text'])
                    # Check both persistent storage and current batch answers
                    is_answered = any(
                        sanitized_text == self._sanitize_text(item['question'])
                        for item in self.all_data
                    ) or sanitized_text in sanitized_batch_keys
                    
                    if not is_answered:
                        questions_to_batch.append(info)
            except Exception:
                continue

        if questions_to_batch:
            batch_results = self.gpt_answerer.answer_questions_batch(questions_to_batch)
            if batch_results:
                for k, v in batch_results.items():
                    self.batch_answers[self._sanitize_text(k)] = v
            
            # CRITICAL: Identify which questions failed to get an answer in this batch
            # and mark them as 'tried' to avoid infinite batch call loops
            sanitized_results_keys = {self._sanitize_text(k) for k in self.batch_answers.keys()}
            for q in questions_to_batch:
                q_text = q['text']
                sanitized_q = self._sanitize_text(q_text)
                if sanitized_q not in sanitized_results_keys:
                     self.batch_answers[sanitized_q] = None # Mark as tried/no answer found

        for section in form_sections:
            try:
                # SKIP LOGIC: Double check for the actual processing loop
                if page_count == 1:
                    section_text = section.text.lower()
                    if any(x in section_text for x in ['phone', 'email', 'country', 'mobile']):
                        continue

                if self._is_upload_field(section):
                    continue
                self._process_form_section(section)
            except Exception as e:
                logger.warning(f"Error processing a form section, continuing to next: {e}")

    def _process_form_section(self, section: WebElement) -> None:
        logger.debug("Processing form section")
        if self._handle_terms_of_service(section):
            logger.debug("Handled terms of service")
            return
        if self._find_and_handle_checkbox_question(section):
            logger.debug("Handled checkbox question")
            return
        if self._find_and_handle_radio_question(section):
            logger.debug("Handled radio question")
            return
        if self._find_and_handle_textbox_question(section):
            logger.debug("Handled textbox question")
            return
        if self._find_and_handle_date_question(section):
            logger.debug("Handled date question")
            return

        if self._find_and_handle_dropdown_question(section):
            logger.debug("Handled dropdown question")
            return

    def _handle_terms_of_service(self, element: WebElement) -> bool:
        checkbox = element.find_elements(By.TAG_NAME, 'label')
        if checkbox and any(
                term in checkbox[0].text.lower() for term in ['terms of service', 'privacy policy', 'terms of use']):
            checkbox[0].click()
            logger.debug("Clicked terms of service checkbox")
            return True
        return False

    def _find_and_handle_checkbox_question(self, section: WebElement) -> bool:
        try:
            checkboxes = section.find_elements(By.XPATH, ".//input[@type='checkbox']")
            if not checkboxes:
                return False

            # Extract question text from section
            question_text = section.text.split('\n')[0].lower().strip()
            if not question_text or len(question_text) < 3:
                 # Try to find a label or legend
                 labels = section.find_elements(By.TAG_NAME, "label")
                 if labels: question_text = labels[0].text.lower().strip()

            options = []
            for cb in checkboxes:
                parent = cb.find_element(By.XPATH, "./..")
                options.append(parent.text.lower().strip())

            if not options: return False

            sanitized_q = self._sanitize_text(question_text)
            existing_answer = self.batch_answers.get(sanitized_q)

            if existing_answer:
                for i, opt in enumerate(options):
                    if existing_answer.lower() in opt:
                        if not checkboxes[i].is_selected():
                            checkboxes[i].click()
                        return True

            answer = self.gpt_answerer.answer_question_from_options(question_text, options)
            for i, opt in enumerate(options):
                if answer.lower() in opt:
                    if not checkboxes[i].is_selected():
                        checkboxes[i].click()
                    self._save_questions_to_json({'type': 'checkbox', 'question': question_text, 'answer': str(answer)})
                    return True
            
            return False
        except Exception as e:
            logger.debug(f"Failed to handle checkbox question: {e}")
            return False

    def _find_and_handle_radio_question(self, section: WebElement) -> bool:
        try:
            # Try multiple selectors for radio options — LinkedIn changes these frequently
            radios = section.find_elements(By.CLASS_NAME, 'fb-text-selectable__option')
            if not radios:
                radios = section.find_elements(By.CSS_SELECTOR, '[data-test-text-selectable-option]')
            if not radios:
                radios = section.find_elements(By.XPATH, ".//div[contains(@class, 'radio')]//label")
            if not radios:
                radios = section.find_elements(By.XPATH, ".//fieldset//div[.//input[@type='radio']]")

            if not radios:
                return False

            question_text = section.text.split('\n')[0].lower().strip()
            options = [radio.text.lower().strip() for radio in radios if radio.text.strip()]

            if not options:
                return False

            sanitized_q = self._sanitize_text(question_text)
            existing_answer = None
            for item in self.all_data:
                if sanitized_q == self._sanitize_text(item['question']) and item['type'] == 'radio':
                    existing_answer = item['answer']
                    break

            if not existing_answer:
                existing_answer = self.batch_answers.get(sanitized_q)

            if existing_answer:
                self._save_questions_to_json({'type': 'radio', 'question': question_text, 'answer': str(existing_answer)})
                self._select_radio(radios, existing_answer)
                logger.debug(f"Selected existing/batch radio answer: {existing_answer}")
                return True

            answer = self.gpt_answerer.answer_question_from_options(question_text, options)
            self._save_questions_to_json({'type': 'radio', 'question': question_text, 'answer': str(answer)})
            self._select_radio(radios, answer)
            logger.debug(f"Selected new radio answer: {answer}")
            return True
        except Exception as e:
            logger.debug(f"Not a radio question or failed to handle: {e}")
            return False

    def _find_and_handle_textbox_question(self, section: WebElement) -> bool:
        logger.debug("Searching for text fields in the section.")
        try:
            text_fields = section.find_elements(By.TAG_NAME, 'input') + section.find_elements(By.TAG_NAME, 'textarea')
            text_fields = [tf for tf in text_fields if (tf.get_attribute('type') or 'text') not in ['hidden', 'checkbox', 'radio', 'file', 'submit', 'button']]

            if not text_fields:
                return False

            text_field = text_fields[0]

            # Extract question label — try <label>, then aria-label, then placeholder
            question_text = ""
            label_elements = section.find_elements(By.TAG_NAME, 'label')
            if label_elements:
                question_text = label_elements[0].text.lower().strip()
            if not question_text:
                question_text = (text_field.get_attribute('aria-label') or "").lower().strip()
            if not question_text:
                question_text = (text_field.get_attribute('placeholder') or "").lower().strip()
            if not question_text:
                # Fallback: Try to get text from the whole section if it's small, or the first line
                section_text = section.text.strip().split('\n')[0].lower()
                if section_text and len(section_text) > 3:
                    question_text = section_text
            if not question_text:
                logger.debug("No label found for text field, skipping.")
                return False

            logger.debug(f"Found text field with label: {question_text}")

            is_numeric = self._is_numeric_field(text_field, question_text)
            question_type = 'numeric' if is_numeric else 'textbox'
            sanitized_q = self._sanitize_text(question_text)

            is_cover_letter = 'cover letter' in question_text

            existing_answer = None
            if not is_cover_letter:
                for item in self.all_data:
                    if self._sanitize_text(item['question']) == sanitized_q and item.get('type') == question_type:
                        existing_answer = item['answer']
                        break
                if not existing_answer:
                    existing_answer = self.batch_answers.get(sanitized_q)

            if existing_answer and not is_cover_letter:
                answer = existing_answer
                self._save_questions_to_json({'type': question_type, 'question': question_text, 'answer': str(answer)})
                logger.debug(f"Using existing/batch answer: {answer}")
            else:
                if is_numeric:
                    answer = self.gpt_answerer.answer_question_numeric(question_text)
                else:
                    answer = self.gpt_answerer.answer_question_textual_wide_range(question_text)

            # Extra safety for numeric fields: ensure we only enter digits
            if is_numeric:
                answer = "".join(re.findall(r'\d+', str(answer)))
                if not answer: answer = "2" # Fallback minimum

            self._enter_text(text_field, str(answer))

            if not is_cover_letter:
                self._save_questions_to_json({'type': question_type, 'question': question_text, 'answer': str(answer)})

            return True
        except Exception as e:
            logger.debug(f"Not a textbox question or failed to handle: {e}")
            return False

    def _find_and_handle_date_question(self, section: WebElement) -> bool:
        try:
            date_fields = section.find_elements(By.CLASS_NAME, 'artdeco-datepicker__input')
            if not date_fields:
                date_fields = section.find_elements(By.XPATH, ".//input[contains(@class, 'datepicker')]")
            if date_fields:
                date_field = date_fields[0]
                question_text = section.text.lower()
                answer_date = self.gpt_answerer.answer_question_date()
                answer_text = answer_date.strftime("%Y-%m-%d")

                existing_answer = None
                for item in self.all_data:
                    if self._sanitize_text(question_text) in item['question'] and item['type'] == 'date':
                        existing_answer = item['answer']
                        break

                if not existing_answer:
                    existing_answer = self.batch_answers.get(question_text.split('\n')[0].lower().strip())

                if existing_answer:
                    self._save_questions_to_json({'type': 'date', 'question': question_text, 'answer': str(existing_answer)})
                    self._enter_text(date_field, existing_answer)
                    logger.debug(f"Selected existing/batch date answer: {existing_answer}")
                    return True

                self._save_questions_to_json({'type': 'date', 'question': question_text, 'answer': answer_text})
                self._enter_text(date_field, answer_text)
                logger.debug("Selected new date answer")
                return True
        except Exception as e:
            logger.debug(f"Not a date question or failed to handle: {e}")
        return False

    def _find_and_handle_dropdown_question(self, section: WebElement) -> bool:
        try:
            # Search for <select> elements directly in section
            dropdowns = section.find_elements(By.TAG_NAME, 'select')
            if not dropdowns:
                dropdowns = section.find_elements(By.CSS_SELECTOR, '[data-test-text-entity-list-form-select]')

            if not dropdowns:
                return False

            dropdown = dropdowns[0]
            select = Select(dropdown)
            options = [option.text.strip() for option in select.options if option.text.strip()]
            dropdown_id = (dropdown.get_attribute('id') or "").lower()

            if not options:
                return False

            # Extract and clean question text
            label_elements = section.find_elements(By.TAG_NAME, 'label')
            if label_elements:
                # Clean up double labels (aria-hidden + visually-hidden)
                question_text = label_elements[0].text.split('\n')[0].lower().strip()
            else:
                question_text = (dropdown.get_attribute('aria-label') or "").lower().strip()
            
            if not question_text or len(question_text) < 3:
                # Fallback: Try section text
                section_text = section.text.strip().split('\n')[0].lower()
                if section_text and len(section_text) > 3:
                    question_text = section_text

            if not question_text:
                question_text = "unknown"

            # 3. STANDARD HANDLING: GPT / Cache
            sanitized_q = self._sanitize_text(question_text)
            existing_answer = None
            for item in self.all_data:
                if sanitized_q == self._sanitize_text(item['question']) and item['type'] == 'dropdown':
                    existing_answer = item['answer']
                    break

            if not existing_answer:
                existing_answer = self.batch_answers.get(sanitized_q)

            if existing_answer:
                if existing_answer in options:
                    select.select_by_visible_text(existing_answer)
                    logger.debug(f"Selected existing dropdown answer: {existing_answer}")
                    return True

            # Query LLM if no answer found
            answer = self.gpt_answerer.answer_question_from_options(question_text, options)
            if answer in options:
                select.select_by_visible_text(answer)
                self._save_questions_to_json({'type': 'dropdown', 'question': question_text, 'answer': str(answer)})
                return True
            
            return False

        except Exception as e:
            logger.warning(f"Failed to handle dropdown question: {e}")
            return False

    def _is_numeric_field(self, field: WebElement, question_text: str = "") -> bool:
        field_type = (field.get_attribute('type') or 'text').lower()
        field_id = (field.get_attribute('id') or '').lower()
        field_pattern = (field.get_attribute('pattern') or '').lower()
        field_inputmode = (field.get_attribute('inputmode') or '').lower()
        is_numeric = (
            'numeric' in field_id
            or field_type == 'number'
            or field_inputmode in ('numeric', 'decimal')
            or field_pattern in (r'\d*', r'[0-9]*', r'\d+')
        )
        if not is_numeric and question_text:
            q_lower = question_text.lower()
            numeric_keywords = ['how many', 'years', 'number', 'level', 'experience', 'total', 'salary', 'compensation', '0-99', '1-10', 'rate']
            if any(kw in q_lower for kw in numeric_keywords):
                is_numeric = True
        logger.debug(f"Numeric check for '{question_text}': {is_numeric}")
        return is_numeric

    def _enter_text(self, element: WebElement, text: str) -> None:
        text = str(text)
        logger.debug(f"Entering text: {text}")
        element.clear()
        element.send_keys(text)

    def _select_radio(self, radios: List[WebElement], answer: str) -> None:
        logger.debug(f"Selecting radio option: {answer}")
        answer_lower = str(answer).lower().strip()
        for radio in radios:
            if answer_lower in radio.text.lower():
                try:
                    label = radio.find_element(By.TAG_NAME, 'label')
                    label.click()
                except NoSuchElementException:
                    # Some LinkedIn layouts have the radio as a direct clickable element
                    radio.click()
                return
        # Fallback: select last option if no match found
        logger.warning(f"No exact radio match for '{answer}', selecting last option as fallback")
        try:
            radios[-1].find_element(By.TAG_NAME, 'label').click()
        except NoSuchElementException:
            radios[-1].click()

    def _select_dropdown_option(self, element: WebElement, text: str) -> None:
        text = str(text)
        logger.debug(f"Selecting dropdown option: {text}")
        select = Select(element)
        try:
            select.select_by_visible_text(text)
        except NoSuchElementException:
            logger.debug(f"Exact match not found for '{text}', attempting relaxed match.")
            for option in select.options:
                if text.lower() in option.text.lower():
                    select.select_by_visible_text(option.text)
                    logger.debug(f"Relaxed match found: {option.text}")
                    return
            raise

    def _save_questions_to_json(self, question_data: dict) -> None:
        output_file = 'answers.json'
        question_data['question'] = self._sanitize_text(question_data['question'])

        logger.debug(f"Saving question data to JSON: {question_data}")
        try:
            try:
                with open(output_file, 'r') as f:
                    try:
                        data = json.load(f)
                        if not isinstance(data, list):
                            raise ValueError("JSON file format is incorrect. Expected a list of questions.")
                    except json.JSONDecodeError:
                        logger.error("JSON decoding failed")
                        data = []
            except FileNotFoundError:
                logger.warning("JSON file not found, creating new file")
                data = []
            data.append(question_data)
            with open(output_file, 'w') as f:
                json.dump(data, f, indent=4)
            self.all_data = data # Update in-memory cache
            logger.debug("Question data saved successfully to JSON and in-memory cache")
        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Error saving questions data to JSON file: {tb_str}")
            raise Exception(f"Error saving questions data to JSON file: \nTraceback:\n{tb_str}")

    def _sanitize_text(self, text: str) -> str:
        sanitized_text = text.lower().strip().replace('"', '').replace('\\', '')
        sanitized_text = re.sub(r'[\x00-\x1F\x7F]', '', sanitized_text).replace('\n', ' ').replace('\r', '').rstrip(',')
        logger.debug(f"Sanitized text: {sanitized_text}")
        return sanitized_text
