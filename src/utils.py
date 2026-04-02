import logging
import os
import random
import sys
import time

from selenium import webdriver
from loguru import logger

from app_config import MINIMUM_LOG_LEVEL

log_file = "app_log.log"


if MINIMUM_LOG_LEVEL in ["DEBUG", "TRACE", "INFO", "WARNING", "ERROR", "CRITICAL"]:
    logger.remove()
    logger.add(sys.stderr, level=MINIMUM_LOG_LEVEL)
else:
    logger.warning(f"Invalid log level: {MINIMUM_LOG_LEVEL}. Defaulting to DEBUG.")
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")

chromeProfilePath = os.path.join(os.getcwd(), "chrome_profile", "linkedin_profile")

def ensure_chrome_profile():
    logger.debug(f"Ensuring Chrome profile exists at path: {chromeProfilePath}")
    profile_dir = os.path.dirname(chromeProfilePath)
    if not os.path.exists(profile_dir):
        os.makedirs(profile_dir)
        logger.debug(f"Created directory for Chrome profile: {profile_dir}")
    if not os.path.exists(chromeProfilePath):
        os.makedirs(chromeProfilePath)
        logger.debug(f"Created Chrome profile directory: {chromeProfilePath}")
    return chromeProfilePath


def is_scrollable(element):
    """
    Checks if an element is scrollable. 
    For body/html, we often want to try scrolling regardless of what Selenium reports.
    """
    try:
        if element.tag_name in ["body", "html"]:
            return True
            
        scroll_height = int(element.get_attribute("scrollHeight") or 0)
        client_height = int(element.get_attribute("clientHeight") or 0)
        offset_height = int(element.get_attribute("offsetHeight") or 0)
        
        # An element is scrollable if its content is larger than its visible area
        scrollable = scroll_height > client_height or scroll_height > offset_height
        logger.debug(f"Element <{element.tag_name}> scrollable check: scrollHeight={scroll_height}, clientHeight={client_height}, offsetHeight={offset_height}, scrollable={scrollable}")
        return scrollable
    except Exception as e:
        logger.debug(f"Error checking scrollability: {e}")
        return True # Default to True to attempt scrolling anyway


def scroll_slow(driver, scrollable_element, start=0, end=3600, step=300, reverse=False):
    logger.debug(f"Starting slow scroll on <{scrollable_element.tag_name}>: start={start}, end={end}, step={step}, reverse={reverse}")

    if reverse:
        start, end = end, start
        step = -step

    if step == 0:
        logger.error("Step value cannot be zero.")
        raise ValueError("Step cannot be zero.")

    try:
        max_scroll_height = int(scrollable_element.get_attribute("scrollHeight") or 0)
        current_scroll_position = int(float(scrollable_element.get_attribute("scrollTop") or 0))
        logger.debug(f"Max scroll height of the element: {max_scroll_height}")
        logger.debug(f"Current scroll position: {current_scroll_position}")

        if not reverse and end > max_scroll_height and max_scroll_height > 0:
            logger.debug(f"End value {end} exceeds the scroll height {max_scroll_height}. Adjusting end.")
            end = max_scroll_height

        if scrollable_element.is_displayed():
            # We attempt scrolling regardless of is_scrollable() for body/html
            # or if it seems scrollable.
            
            position = start
            previous_position = None  # Tracking the previous position to avoid duplicate scrolls
            
            if scrollable_element.tag_name in ["body", "html"]:
                script_scroll_to = "window.scrollTo(0, arguments[1]);"
                get_scroll_pos = "return window.pageYOffset || document.documentElement.scrollTop;"
            else:
                script_scroll_to = "arguments[0].scrollTop = arguments[1];"
                get_scroll_pos = "return arguments[0].scrollTop;"
            
            while (step > 0 and position < end) or (step < 0 and position > end):
                try:
                    driver.execute_script(script_scroll_to, scrollable_element, position)
                    time.sleep(random.uniform(0.3, 0.8))
                    
                    new_position = int(float(driver.execute_script(get_scroll_pos, scrollable_element) or 0))
                    if previous_position is not None and abs(new_position - previous_position) < 5:
                        # If position didn't change after an attempt to scroll, we might have hit the end
                        logger.debug(f"Scroll position hasn't changed ({new_position}), possibly reached end of scrollable area.")
                        break
                    previous_position = new_position
                except Exception as e:
                    logger.error(f"Error during scrolling: {e}")
                    break

                position += step
                # Slightly decrease the step to simulate natural scrolling, but keep it effective
                step = max(50, abs(step) - 5) * (-1 if reverse else 1)

            # Ensure the final scroll position is attempted
            try:
                driver.execute_script(script_scroll_to, scrollable_element, end)
            except:
                pass
            logger.debug(f"Completed scroll attempt to: {end}")
            time.sleep(0.5)
        else:
            logger.warning("The element is not visible, skipping scroll.")
    except Exception as e:
        logger.error(f"Exception occurred during scrolling: {e}")


def chrome_browser_options(headless=False):
    logger.debug("Setting Chrome browser options")
    ensure_chrome_profile()
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("window-size=1200x800")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-translate")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-logging")
    options.add_argument("--disable-autofill")
    options.add_argument("--disable-plugins")
    options.add_argument("--disable-animations")
    options.add_argument("--disable-cache")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])

    prefs = {
        "profile.default_content_setting_values.images": 2,
        "profile.managed_default_content_settings.stylesheets": 2,
    }
    options.add_experimental_option("prefs", prefs)

    if len(chromeProfilePath) > 0:
        initial_path = os.path.dirname(chromeProfilePath)
        profile_dir = os.path.basename(chromeProfilePath)
        options.add_argument('--user-data-dir=' + initial_path)
        options.add_argument("--profile-directory=" + profile_dir)
        logger.debug(f"Using Chrome profile directory: {chromeProfilePath}")
    else:
        options.add_argument("--incognito")
        logger.debug("Using Chrome in incognito mode")

    return options


def printred(text):
    red = "\033[91m"
    reset = "\033[0m"
    logger.debug("Printing text in red: %s", text)
    print(f"{red}{text}{reset}")


def printyellow(text):
    yellow = "\033[93m"
    reset = "\033[0m"
    logger.debug("Printing text in yellow: %s", text)
    print(f"{yellow}{text}{reset}")


def is_message_popup_open(driver) -> bool:
    """Detect if a LinkedIn message thread is in focus"""
    from selenium.webdriver.common.by import By
    popups = driver.find_elements(
        By.XPATH,
        "//div[contains(@class, 'msg-overlay-conversation-bubble')]"
    )
    return len(popups) > 0


def safe_click(driver, element):
    """Only click if no message popup is open"""
    if is_message_popup_open(driver):
        logger.warning("Message popup detected — skipping click to avoid employer spam")
        return False
    element.click()
    return True
