from pathlib import Path
import os
import json
import random
import time
import traceback
from itertools import product

from inputimeout import inputimeout, TimeoutOccurred
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import src.utils as utils
from app_config import MINIMUM_WAIT_TIME
from src.job import Job
from src.aihawk_easy_applier import AIHawkEasyApplier
from loguru import logger
import urllib.parse


class EnvironmentKeys:
    def __init__(self):
        logger.debug("Initializing EnvironmentKeys")
        self.skip_apply = self._read_env_key_bool("SKIP_APPLY")
        self.disable_description_filter = self._read_env_key_bool("DISABLE_DESCRIPTION_FILTER")
        logger.debug(f"EnvironmentKeys initialized: skip_apply={self.skip_apply}, disable_description_filter={self.disable_description_filter}")

    @staticmethod
    def _read_env_key(key: str) -> str:
        value = os.getenv(key, "")
        logger.debug(f"Read environment key {key}: {value}")
        return value

    @staticmethod
    def _read_env_key_bool(key: str) -> bool:
        value = os.getenv(key) == "True"
        logger.debug(f"Read environment key {key} as bool: {value}")
        return value


class AIHawkJobManager:
    def __init__(self, driver):
        logger.debug("Initializing AIHawkJobManager")
        self.driver = driver
        self.set_old_answers = set()
        self.easy_applier_component = None
        self.parameters = None
        self.config_file = None
        logger.debug("AIHawkJobManager initialized successfully")

    def set_parameters(self, parameters: dict, config_file: Path):
        logger.debug("Setting parameters for AIHawkJobManager")
        self.parameters = parameters
        self.config_file = config_file
        self.company_blacklist = self.parameters.get('company_blacklist', []) or []
        self.title_blacklist = self.parameters.get('title_blacklist', []) or []
        self.location_blacklist = self.parameters.get('location_blacklist', []) or []
        self.positions = self.parameters.get('positions', [])
        self.locations = self.parameters.get('locations', [])
        self.apply_once_at_company = self.parameters.get('apply_once_at_company', False)
        self.base_search_url = self.get_base_search_url(self.parameters)
        self.seen_jobs = []

        job_applicants_threshold = self.parameters.get('job_applicants_threshold', {})
        self.min_applicants = job_applicants_threshold.get('min_applicants', 0)
        self.max_applicants = job_applicants_threshold.get('max_applicants', float('inf'))

        resume_path = self.parameters.get('uploads', {}).get('resume', None)
        self.resume_path = Path(resume_path) if resume_path and Path(resume_path).exists() else None
        self.output_file_directory = Path(self.parameters['outputFileDirectory'])
        self.env_config = EnvironmentKeys()
        logger.debug("Parameters set successfully")

    def set_gpt_answerer(self, gpt_answerer):
        logger.debug("Setting GPT answerer")
        self.gpt_answerer = gpt_answerer

    def set_resume_generator_manager(self, resume_generator_manager):
        logger.debug("Setting resume generator manager")
        self.resume_generator_manager = resume_generator_manager

    def start_collecting_data(self):
        if not self.positions or not self.locations:
            logger.error("No positions or locations configured. Please check your config.yaml.")
            return
            
        searches = list(product(self.positions, self.locations))
        random.shuffle(searches)
        
        if not searches:
            logger.error("Search list is empty. Please check your positions and locations in config.yaml.")
            return
            
        logger.info(f"Starting data collection loop for {len(searches)} search combinations.")
        
        page_sleep = 0
        minimum_time = 60 * 5
        minimum_page_time = time.time() + minimum_time

        for position, location in searches:
            location_url = "&location=" + location
            job_page_number = -1
            logger.info(f"Collecting data for {position} in {location}.")
            try:
                while True:
                    page_sleep += 1
                    job_page_number += 1
                    logger.info(f"Going to job page {job_page_number}")
                    self.next_job_page(position, location_url, job_page_number)
                    time.sleep(random.uniform(1.5, 3.5))
                    logger.info("Starting the collecting process for this page")
                    self.read_jobs()
                    logger.info("Collecting data on this page has been completed!")

                    time_left = minimum_page_time - time.time()
                    if time_left > 0:
                        logger.info(f"Sleeping for {time_left} seconds.")
                        time.sleep(time_left)
                        minimum_page_time = time.time() + minimum_time
                    if page_sleep % 5 == 0:
                        sleep_time = random.randint(1, 5)
                        logger.info(f"Sleeping for {sleep_time / 60} minutes.")
                        time.sleep(sleep_time)
                        page_sleep += 1
            except Exception:
                pass
            time_left = minimum_page_time - time.time()
            if time_left > 0:
                logger.info(f"Sleeping for {time_left} seconds.")
                time.sleep(time_left)
                minimum_page_time = time.time() + minimum_time
            if page_sleep % 5 == 0:
                sleep_time = random.randint(50, 90)
                logger.info(f"Sleeping for {sleep_time / 60} minutes.")
                time.sleep(sleep_time)
                page_sleep += 1

    def start_applying(self):
        try:
            logger.debug("Starting job application process")
            if not self.positions or not self.locations:
                logger.error("No positions or locations configured. Please check your config.yaml.")
                return

            # Perform health check before starting
            try:
                self.perform_health_check()
            except Exception as e:
                logger.warning(f"Health check failed: {e}. Attempting to proceed anyway...")

            self.easy_applier_component = AIHawkEasyApplier(self.driver, self.resume_path, self.set_old_answers,
                                                              self.gpt_answerer, self.resume_generator_manager,
                                                              self.parameters, self.config_file)
            searches = list(product(self.positions, self.locations))
            random.shuffle(searches)
            
            if not searches:
                logger.error("Search list is empty. Please check your positions and locations in config.yaml.")
                return
                
            logger.info(f"Starting application loop for {len(searches)} search combinations.")
            
            page_sleep = 0
            minimum_time = MINIMUM_WAIT_TIME
            minimum_page_time = time.time() + minimum_time

            for position, location in searches:
                location_url = "&location=" + location
                job_page_number = -1
                logger.info(f"🚀 Starting search for '{position}' in '{location}'.")

                try:
                    while True:
                        page_sleep += 1
                        job_page_number += 1
                        logger.info(f"▶️ Starting search on page {job_page_number + 1} for '{position}' in '{location}'...")
                        self.next_job_page(position, location_url, job_page_number)
                        time.sleep(random.uniform(3.5, 6.5)) # Increased wait for page load
                        logger.debug("Starting the application process for this page...")

                        try:
                            jobs = self.get_jobs_from_page()
                            if not jobs:
                                logger.info("⏹️ No more jobs found for this search query.")
                                break
                        except Exception as e:
                            logger.error(f"Failed to retrieve jobs: {e}")
                            break

                        try:
                            self.apply_jobs()
                        except Exception as e:
                            logger.error(f"Error during job application: {e}")
                            continue

                        logger.info(f"✅ Finished page {job_page_number + 1}.")

                        time_left = minimum_page_time - time.time()

                        # Ask user if they want to skip waiting, with timeout
                        if time_left > 0:
                            try:
                                user_input = inputimeout(
                                    prompt=f"⏸️ Waiting for {time_left:.1f}s before next page. Press 'y' to skip: ",
                                    timeout=60).strip().lower()
                            except TimeoutOccurred:
                                user_input = ''  # No input after timeout
                            if user_input == 'y':
                                logger.debug("User chose to skip waiting.")
                            else:
                                logger.debug(f"Sleeping for {time_left} seconds as user chose not to skip.")
                                time.sleep(time_left)

                        minimum_page_time = time.time() + minimum_time

                        if page_sleep % 5 == 0:
                            sleep_time = random.randint(5, 34)
                            try:
                                user_input = inputimeout(
                                    prompt=f"⏸️ Taking a longer break for {sleep_time}s. Press 'y' to skip: ",
                                    timeout=60).strip().lower()
                            except TimeoutOccurred:
                                user_input = ''  # No input after timeout
                            if user_input == 'y':
                                logger.debug("User chose to skip waiting.")
                            else:
                                logger.debug(f"Sleeping for {sleep_time} seconds.")
                                time.sleep(sleep_time)
                            page_sleep += 1
                except Exception as e:
                    logger.error(f"Unexpected error during job search: {e}")
                    continue

                time_left = minimum_page_time - time.time()

                if time_left > 0:
                    try:
                        user_input = inputimeout(
                            prompt=f"⏸️ Waiting for {time_left:.1f}s. Press 'y' to skip: ",
                            timeout=60).strip().lower()
                    except TimeoutOccurred:
                        user_input = ''  # No input after timeout
                    if user_input == 'y':
                        logger.debug("User chose to skip waiting.")
                    else:
                        logger.debug(f"Sleeping for {time_left} seconds as user chose not to skip.")
                        time.sleep(time_left)

                minimum_page_time = time.time() + minimum_time

                if page_sleep % 5 == 0:
                    sleep_time = random.randint(50, 90)
                    try:
                        user_input = inputimeout(
                            prompt=f"⏸️ Taking a longer break for {sleep_time}s. Press 'y' to skip: ",
                            timeout=60).strip().lower()
                    except TimeoutOccurred:
                        user_input = ''  # No input after timeout
                    if user_input == 'y':
                        logger.debug("User chose to skip waiting.")
                    else:
                        logger.debug(f"Sleeping for {sleep_time} seconds.")
                        time.sleep(sleep_time)
                    page_sleep += 1
        except Exception as e:
            logger.critical(f"FATAL CRASH in apply loop: {e}")
            logger.error(traceback.format_exc())

    def _find_and_scroll_job_list_container(self):
        """
        Attempts to find the scrollable job list container using multiple selectors
        and then performs a slow scroll to load all jobs.
        """
        # Ordered list of potential job list container selectors
        selectors = [
            (By.CSS_SELECTOR, "[data-results-list-top-scroll-limit]"), # Modern stable attribute
            (By.CSS_SELECTOR, "div.scaffold-layout__list"),
            (By.CSS_SELECTOR, "div.jobs-search-results-list"),
            (By.CSS_SELECTOR, ".jobs-search-results"),
            (By.CSS_SELECTOR, "div.scaffold-layout__list-container"),
            (By.XPATH, "//div[contains(@class, 'jobs-search-results') and contains(@class, 'scaffold-layout__list')]"),
            (By.XPATH, "//div[contains(@class, 'jobs-search-results-list')]"),
            (By.XPATH, "//div[contains(@class, 'jobs-search-results') and @role='main']")
        ]

        # Try to use learned XPath if available
        cached_xpath = self.parameters.get('learned_job_list_container_xpath')
        if cached_xpath:
            selectors.insert(0, (By.XPATH, cached_xpath))
            logger.debug(f"Attempting to use learned job list container XPath: {cached_xpath}")

        job_list_container = None
        working_selector = None
        for by, selector in selectors:
            try:
                # Use WebDriverWait to ensure the element is present and visible
                container = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((by, selector))
                )
                if container.is_displayed():
                    # Check if it's actually scrollable before committing to it
                    s_height = int(container.get_attribute("scrollHeight") or 0)
                    c_height = int(container.get_attribute("clientHeight") or 0)
                    if s_height > c_height:
                        job_list_container = container
                        working_selector = (by, selector)
                        logger.debug(f"Found scrollable job list container with selector: {selector}")
                        break
                    else:
                        logger.debug(f"Container found with {selector} but not currently scrollable (s:{s_height} vs c:{c_height}).")
            except Exception:
                logger.debug(f"Job list container not found with selector: {selector}")
                continue

        # If a container was found, scroll it
        if job_list_container:
            # Update learned XPath if a new one worked (and it's an XPath)
            if working_selector and working_selector[0] == By.XPATH:
                xpath = working_selector[1]
                if xpath != cached_xpath:
                    self.parameters['learned_job_list_container_xpath'] = xpath
                    from main import ConfigValidator
                    ConfigValidator.save_config(self.parameters, self.config_file)
                    logger.info(f"Learned working Job List Container XPath and saved to config: {xpath}")

            utils.scroll_slow(self.driver, job_list_container, end=3600, step=300)
            utils.scroll_slow(self.driver, job_list_container, step=300, reverse=True)
            return job_list_container
        else:
            logger.warning("No specific scrollable job list container found. Performing broad scroll on body and html.")
            # Fallback to scrolling both body and html to trigger lazy-loaded jobs
            for tag in ["body", "html"]:
                try:
                    element = self.driver.find_element(By.TAG_NAME, tag)
                    utils.scroll_slow(self.driver, element, end=3600, step=300)
                    utils.scroll_slow(self.driver, element, step=300, reverse=True)
                except Exception as e:
                    logger.debug(f"Failed to scroll {tag}: {e}")
            
            # Return body as the best guess container for finding elements within
            return self.driver.find_element(By.TAG_NAME, "body")

    def get_jobs_from_page(self):
        logger.debug("Attempting to get jobs from the current page.")
        job_results_container = self._find_and_scroll_job_list_container()
        
        # Broad list of job tile selectors, prioritizing stable data attributes
        job_selectors = [
            'li[data-occludable-job-id]', # Highly stable LinkedIn data attribute
            'li[data-job-id]',            # Alternative stable ID
            'div.jobs-search-results-list__list-item',
            'li.jobs-search-results__list-item',
            'div.job-card-container',
            'div.job-card-list__entity-lockup',
            '.jobs-search-two-pane__job-item'
        ]
        
        job_list_elements = []
        for selector in job_selectors:
            elements = job_results_container.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                logger.debug(f"Found {len(elements)} job elements using selector: {selector}")
                job_list_elements.extend(elements)
        
        # Deduplicate elements by reference
        job_list_elements = list(dict.fromkeys(job_list_elements))

        if not job_list_elements:
            logger.debug("No job elements found within container, performing page-wide search as fallback.")
            for selector in job_selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    logger.debug(f"Found {len(elements)} job elements page-wide using selector: {selector}")
                    job_list_elements.extend(elements)
            job_list_elements = list(dict.fromkeys(job_list_elements))

        if not job_list_elements:
            logger.warning("No job elements found on the page after all attempts.")
            return []
        
        logger.info(f"Successfully retrieved {len(job_list_elements)} job elements.")
        return job_list_elements

    def perform_health_check(self):
        """
        Navigates to a sample search to verify that essential selectors are still working.
        """
        logger.info("🛠️ Running system health check...")
        test_url = "https://www.linkedin.com/jobs/search/?keywords=python"
        self.driver.get(test_url)
        time.sleep(5)
        
        results = {
            "job_cards": len(self.driver.find_elements(By.CSS_SELECTOR, "li[data-occludable-job-id]")),
            "easy_apply_filter": len(self.driver.find_elements(By.XPATH, "//button[contains(@aria-label, 'Easy Apply filter')]"))
        }
        
        if results["job_cards"] == 0:
            logger.warning(f"Health check identified potential selector breakage: {results}")
            # We don't raise Exception to allow the bot to try anyway, but we log it clearly
        else:
            logger.info(f"✅ Health check passed: {results}")
        return results

    def read_jobs(self):
        logger.debug("Starting to read jobs from the current page for data collection.")
        try:
            no_jobs_element = self.driver.find_element(By.CLASS_NAME, 'jobs-search-two-pane__no-results-banner--expand')
            if 'No matching jobs found' in no_jobs_element.text:
                logger.info("No more jobs found for this search query on this page.")
                raise Exception("No more jobs on this page")
        except NoSuchElementException:
            pass # No "no jobs found" banner, continue normally

        job_list_elements = self.get_jobs_from_page()
        
        if not job_list_elements:
            logger.info("No job class elements found on page, raising exception.")
            raise Exception("No job class elements found on page")
        
        job_list = [Job(*self.extract_job_information_from_tile(job_element)) for job_element in job_list_elements]
        logger.debug(f"Extracted {len(job_list)} jobs from current page.")

        for job in job_list:            
            if self.is_blacklisted(job.title, job.company, job.link, job.location):
                utils.printyellow(f"Blacklisted {job.title} at {job.company} in {job.location}, skipping...")
                self.write_to_file(job, "skipped")
                continue
            
            # Applicant Threshold Check
            if job.applicants < self.min_applicants or job.applicants > self.max_applicants:
                utils.printyellow(f"Job {job.title} at {job.company} has {job.applicants} applicants, which is outside threshold ({self.min_applicants}-{self.max_applicants}), skipping...")
                self.write_to_file(job, "skipped")
                continue

            try:
                self.write_to_file(job,'data')
            except Exception as e:
                logger.error(f"Failed to write job data for {job.title}: {e}")
                self.write_to_file(job, "failed")
                continue

    def apply_jobs(self):
        logger.debug("Starting the job application process for listed jobs.")
        job_list_elements = self.get_jobs_from_page()

        if not job_list_elements:
            logger.debug("No job elements found on page, skipping applying process.")
            return

        logger.debug(f"Found {len(job_list_elements)} jobs to consider for application.")
        job_list = [Job(*self.extract_job_information_from_tile(job_element)) for job_element in job_list_elements]

        for job in job_list:
            logger.debug(f"Processing job for application: {job.title} at {job.company}")
            
            if self.is_previously_failed_to_apply(job.link) or \
               self.is_blacklisted(job.title, job.company, job.link, job.location) or \
               self.is_already_applied_to_job(job.title, job.company, job.link) or \
               self.is_already_applied_to_company(job.company):
                self.write_to_file(job, "skipped")
                logger.debug(f"Skipping job due to blacklist/already applied policy: {job.title}")
                continue
            
            # Applicant Threshold Check
            if job.applicants < self.min_applicants or job.applicants > self.max_applicants:
                utils.printyellow(f"Job {job.title} at {job.company} has {job.applicants} applicants, which is outside threshold ({self.min_applicants}-{self.max_applicants}), skipping...")
                self.write_to_file(job, "skipped")
                continue

            try:
                if "easy apply" in job.apply_method.lower():
                    logger.info(f"Attempting to Easy Apply for: {job.title} at {job.company} ({job.applicants} applicants)")
                    self.easy_applier_component.job_apply(job)
                    self.write_to_file(job, "success")
                    logger.debug(f"Successfully applied to job: {job.title} at {job.company}")
            except Exception as e:
                logger.error(f"Failed to apply for {job.title} at {job.company}: {e}")
                self.write_to_file(job, "failed")
                continue

    def write_to_file(self, job, file_name):
        logger.debug(f"Writing job application result to file: {file_name}")
        pdf_path = Path(job.pdf_path).resolve()
        pdf_path = pdf_path.as_uri()
        data = {
            "company": job.company,
            "job_title": job.title,
            "link": job.link,
            "job_recruiter": job.recruiter_link,
            "job_location": job.location,
            "pdf_path": pdf_path
        }
        file_path = self.output_file_directory / f"{file_name}.json"
        if not file_path.exists():
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump([data], f, indent=4)
                logger.debug(f"Job data written to new file: {file_name}")
        else:
            with open(file_path, 'r+', encoding='utf-8') as f:
                try:
                    existing_data = json.load(f)
                except json.JSONDecodeError:
                    logger.error(f"JSON decode error in file: {file_path}")
                    existing_data = []
                existing_data.append(data)
                f.seek(0)
                json.dump(existing_data, f, indent=4)
                f.truncate()
                logger.debug(f"Job data appended to existing file: {file_name}")

    def get_base_search_url(self, parameters):
        logger.debug("Constructing base search URL")
        url_parts = []
        if parameters['remote']:
            url_parts.append("f_CF=f_WRA")
        experience_levels = [str(i + 1) for i, (level, v) in enumerate(parameters.get('experience_level', {}).items()) if
                             v]
        if experience_levels:
            url_parts.append(f"f_E={','.join(experience_levels)}")
        url_parts.append(f"distance={parameters['distance']}")
        job_types = [key[0].upper() for key, value in parameters.get('jobTypes', {}).items() if value]
        if job_types:
            url_parts.append(f"f_JT={','.join(job_types)}")
        date_mapping = {
            "all time": "",
            "month": "&f_TPR=r2592000",
            "week": "&f_TPR=r604800",
            "24 hours": "&f_TPR=r86400"
        }
        date_param = next((v for k, v in date_mapping.items() if parameters.get('date', {}).get(k)), "")
        url_parts.append("f_LF=f_AL")  # Easy Apply
        base_url = "&".join(url_parts)
        full_url = f"?{base_url}{date_param}"
        logger.debug(f"Base search URL constructed: {full_url}")
        return full_url

    def next_job_page(self, position, location, job_page):
        logger.debug(f"Navigating to next job page: {position} in {location}, page {job_page}")
        encoded_position = urllib.parse.quote(position)
        self.driver.get(
            f"https://www.linkedin.com/jobs/search/{self.base_search_url}&keywords={encoded_position}{location}&start={job_page * 25}")

    def extract_job_information_from_tile(self, job_tile):
        # logger.debug("Extracting job information from tile")
        time.sleep(0.15) # Small buffer for LinkedIn UI lag
        
        def get_text_or_default(element, selectors, default=""):
            for selector_type, selector_value in selectors:
                try:
                    found_element = element.find_element(selector_type, selector_value)
                    if found_element and found_element.text.strip():
                        return found_element.text.strip()
                except NoSuchElementException:
                    continue
            return default

        try:
            # 1. Job Title & Link - Stable XPATH
            try:
                job_link_element = job_tile.find_element(By.XPATH, './/a[contains(@href,"/jobs/view/")]')
                job_title = job_link_element.text.strip().split('\n')[0]
                link = job_link_element.get_attribute('href').split('?')[0]
            except NoSuchElementException:
                job_title = ""
                link = ""

            # 2. Company Name - Stable XPATH
            company_selectors = [
                (By.XPATH, './/span[@data-tracking-control-name or contains(@class,"subtitle")]'),
                (By.CSS_SELECTOR, '.job-card-container__primary-description'),
                (By.CSS_SELECTOR, '.job-card-container__company-name')
            ]
            company = get_text_or_default(job_tile, company_selectors, "Unknown Company")
            company = company.replace("with verification", "").strip()

            # 3. Location
            location_selectors = [
                (By.CSS_SELECTOR, 'li.job-card-container__metadata-item'),
                (By.CSS_SELECTOR, '.job-card-container__location'),
                (By.XPATH, ".//*[contains(@class, 'job-card-container__metadata-item')]")
            ]
            job_location = get_text_or_default(job_tile, location_selectors, "Unknown Location")
            job_location = job_location.split('\n')[0].strip()
            
            # 4. Applicants - Used for threshold filtering
            applicants_count = 0
            try:
                # LinkedIn often shows this in a specific metadata item
                applicants_text = get_text_or_default(job_tile, [
                    (By.CSS_SELECTOR, '.job-card-container__applicant-count'),
                    (By.XPATH, ".//span[contains(text(), 'applicant')]")
                ])
                if applicants_text:
                    import re
                    match = re.search(r'(\d+)', applicants_text)
                    if match:
                        applicants_count = int(match.group(1))
            except: pass

            # 5. Apply Method
            apply_method = "Standard Apply"
            try:
                easy_apply_indicators = [
                    (By.XPATH, ".//span[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'easy apply')]"),
                    (By.CLASS_NAME, 'job-card-container__apply-method')
                ]
                for s_type, s_val in easy_apply_indicators:
                    try:
                        if job_tile.find_element(s_type, s_val):
                            apply_method = "Easy Apply"
                            break
                    except NoSuchElementException: continue
            except: pass

            logger.debug(f"Job information extracted: {job_title} at {company} (Method: {apply_method}, Applicants: {applicants_count})")
            return job_title, company, job_location, link, apply_method, applicants_count

        except Exception as e:
            logger.warning(f"Error during tile information extraction: {e}")
            return "", "", "", "", "", 0

    def is_blacklisted(self, job_title, company, link, job_location):
        logger.debug(f"Checking if job is blacklisted: {job_title} at {company} in {job_location}")
        job_title_words = job_title.lower().split(' ')
        title_blacklisted = any(word in job_title_words for word in map(str.lower, self.title_blacklist))
        company_blacklisted = company.strip().lower() in (word.strip().lower() for word in self.company_blacklist)
        location_blacklisted= job_location.strip().lower() in (word.strip().lower() for word in self.location_blacklist)
        link_seen = link in self.seen_jobs
        is_blacklisted = title_blacklisted or company_blacklisted or location_blacklisted or link_seen
        logger.debug(f"Job blacklisted status: {is_blacklisted}")

        return title_blacklisted or company_blacklisted or location_blacklisted or link_seen

    def is_already_applied_to_job(self, job_title, company, link):
        link_seen = link in self.seen_jobs
        if link_seen:
            logger.debug(f"Already applied to job: {job_title} at {company}, skipping...")
        return link_seen

    def is_already_applied_to_company(self, company):
        if not self.apply_once_at_company:
            return False

        output_files = ["success.json"]
        for file_name in output_files:
            file_path = self.output_file_directory / file_name
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    try:
                        existing_data = json.load(f)
                        for applied_job in existing_data:
                            if applied_job['company'].strip().lower() == company.strip().lower():
                                logger.debug(
                                    f"Already applied at {company} (once per company policy), skipping...")
                                return True
                    except json.JSONDecodeError:
                        continue
        return False

    def is_previously_failed_to_apply(self, link):
        file_name = "failed"
        file_path = self.output_file_directory / f"{file_name}.json"

        if not file_path.exists():
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump([], f)
                
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                existing_data = json.load(f)
            except json.JSONDecodeError:
                logger.error(f"JSON decode error in file: {file_path}")
                return False
            
        for data in existing_data:
            data_link = data['link']
            if data_link == link:
                return True
                
        return False
