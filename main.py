#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path
import yaml
import click
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException
from lib_resume_builder_AIHawk import Resume, FacadeManager, ResumeGenerator, StyleManager
from src.utils import chrome_browser_options
from src.llm.llm_manager import GPTAnswerer
from src.aihawk_authenticator import AIHawkAuthenticator
from src.aihawk_bot_facade import AIHawkBotFacade
from src.aihawk_job_manager import AIHawkJobManager
from src.job_application_profile import JobApplicationProfile
from loguru import logger

# Suppress stderr only during specific operations
original_stderr = sys.stderr

import logging

class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

def setup_logging():
    # Remove default handler
    logger.remove()
    # Add a cleaner terminal handler
    logger.add(
        sys.stdout, 
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
        colorize=True,
        level="INFO" # Default to INFO for terminal unless debugging
    )
    # Intercept standard logging
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    
    # Mute noisy libraries
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("webdriver_manager").setLevel(logging.WARNING)

setup_logging()

class ConfigError(Exception):
    pass

class ConfigValidator:
    @staticmethod
    def validate_email(email: str) -> bool:
        return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email) is not None
    
    @staticmethod
    def validate_yaml_file(yaml_path: Path) -> dict:
        try:
            with open(yaml_path, 'r') as stream:
                return yaml.safe_load(stream) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Error reading file {yaml_path}: {exc}")
        except FileNotFoundError:
            raise ConfigError(f"File not found: {yaml_path}")

    @staticmethod
    def validate_config(config_yaml_path: Path) -> dict:
        parameters = ConfigValidator.validate_yaml_file(config_yaml_path)
        required_keys = {
            'remote': bool,
            'experienceLevel': dict,
            'jobTypes': dict,
            'date': dict,
            'positions': list,
            'locations': list,
            'location_blacklist': list,
            'distance': int,
            'company_blacklist': list,
            'title_blacklist': list,
            'llm_model_type': str,
            'llm_model': str,
            'headless': bool
        }

        for key, expected_type in required_keys.items():
            if key not in parameters or parameters[key] is None:
                if key == 'positions' or key == 'locations':
                    raise ConfigError(f"Missing or empty required key '{key}' in config file {config_yaml_path}. You must provide at least one.")
                if expected_type == list:
                    parameters[key] = []
                elif expected_type == dict:
                    parameters[key] = {}
                elif key == 'remote':
                    parameters[key] = False
                elif key == 'headless':
                    parameters[key] = False
                elif key == 'distance':
                    parameters[key] = 100
                elif key == 'llm_model_type':
                    parameters[key] = 'openai'
                elif key == 'llm_model':
                    parameters[key] = 'gpt-4o-mini'
                elif key == 'easy_apply_xpath_cache':
                    parameters[key] = None
                else:
                    parameters[key] = expected_type() # Default constructor for other types
            elif not isinstance(parameters[key], expected_type):
                raise ConfigError(f"Invalid type for key '{key}' in config file {config_yaml_path}. Expected {expected_type.__name__}.")

        # Validate positions and locations as lists of strings
        if not parameters['positions'] or not all(isinstance(pos, str) for pos in parameters['positions']):
            raise ConfigError(f"'positions' must be a non-empty list of strings in config file {config_yaml_path}")
        if not parameters['locations'] or not all(isinstance(loc, str) for loc in parameters['locations']):
            raise ConfigError(f"'locations' must be a non-empty list of strings in config file {config_yaml_path}")

        # Validate distance
        approved_distances = {0, 5, 10, 25, 50, 100}
        if parameters['distance'] not in approved_distances:
            logger.warning(f"Invalid distance value {parameters['distance']}. Defaulting to 100.")
            parameters['distance'] = 100

        # Ensure apply_once_at_company exists
        if 'apply_once_at_company' not in parameters:
            parameters['apply_once_at_company'] = False
        elif not isinstance(parameters['apply_once_at_company'], bool):
            parameters['apply_once_at_company'] = False
        
        # Add learned_easy_apply_xpath if it doesn't exist
        if 'learned_easy_apply_xpath' not in parameters or parameters['learned_easy_apply_xpath'] is None:
            parameters['learned_easy_apply_xpath'] = None
        elif not isinstance(parameters['learned_easy_apply_xpath'], str):
            raise ConfigError(f"Invalid type for key 'learned_easy_apply_xpath' in config file {config_yaml_path}. Expected str or None.")

        # Add learned_job_description_xpath if it doesn't exist
        if 'learned_job_description_xpath' not in parameters or parameters['learned_job_description_xpath'] is None:
            parameters['learned_job_description_xpath'] = None
        elif not isinstance(parameters['learned_job_description_xpath'], str):
            raise ConfigError(f"Invalid type for key 'learned_job_description_xpath' in config file {config_yaml_path}. Expected str or None.")

        # Add learned_scrollable_element_xpath if it doesn't exist
        if 'learned_scrollable_element_xpath' not in parameters or parameters['learned_scrollable_element_xpath'] is None:
            parameters['learned_scrollable_element_xpath'] = None
        elif not isinstance(parameters['learned_scrollable_element_xpath'], str):
            raise ConfigError(f"Invalid type for key 'learned_scrollable_element_xpath' in config file {config_yaml_path}. Expected str or None.")

        # Add learned_job_list_container_xpath if it doesn't exist
        if 'learned_job_list_container_xpath' not in parameters or parameters['learned_job_list_container_xpath'] is None:
            parameters['learned_job_list_container_xpath'] = None
        elif not isinstance(parameters['learned_job_list_container_xpath'], str):
            raise ConfigError(f"Invalid type for key 'learned_job_list_container_xpath' in config file {config_yaml_path}. Expected str or None.")

        # Add learned_primary_button_xpath if it doesn't exist
        if 'learned_primary_button_xpath' not in parameters or parameters['learned_primary_button_xpath'] is None:
            parameters['learned_primary_button_xpath'] = None
        elif not isinstance(parameters['learned_primary_button_xpath'], str):
            raise ConfigError(f"Invalid type for key 'learned_primary_button_xpath' in config file {config_yaml_path}. Expected str or None.")

        return parameters


    @staticmethod
    def save_config(config_data: dict, config_yaml_path: Path) -> None:
        try:
            # Safety check: ensure we are not saving an empty or corrupted config
            if not config_data or 'positions' not in config_data or not config_data['positions']:
                logger.error("Attempted to save an empty or invalid configuration. Aborting save to protect config file.")
                return

            # Define keys that are safe and intended to be persisted in config.yaml
            persistable_keys = [
                'remote', 'experienceLevel', 'jobTypes', 'date', 'positions', 'locations',
                'location_blacklist', 'distance', 'company_blacklist', 'title_blacklist',
                'llm_model_type', 'llm_model', 'headless', 'apply_once_at_company',
                'job_applicants_threshold', 'learned_easy_apply_xpath', 'learned_job_description_xpath',
                'learned_scrollable_element_xpath', 'learned_job_list_container_xpath',
                'learned_primary_button_xpath'
            ]
            serializable_config = {}
            for key in persistable_keys:
                if key in config_data:
                    val = config_data[key]
                    # Convert Path objects to strings for YAML serialization
                    if isinstance(val, Path):
                        serializable_config[key] = str(val)
                    else:
                        serializable_config[key] = val

            with open(config_yaml_path, 'w') as stream:
                yaml.safe_dump(serializable_config, stream, indent=4, sort_keys=False)
            logger.debug(f"Configuration successfully saved to {config_yaml_path}")
        except Exception as e:
            logger.error(f"Failed to save configuration to {config_yaml_path}: {e}")
            # We don't raise here to avoid crashing the bot just because config saving failed

    @staticmethod
    def validate_secrets(secrets_yaml_path: Path) -> str:
        secrets = ConfigValidator.validate_yaml_file(secrets_yaml_path)
        mandatory_secrets = ['llm_api_key']

        for secret in mandatory_secrets:
            if secret not in secrets:
                raise ConfigError(f"Missing secret '{secret}' in file {secrets_yaml_path}")

        if not secrets['llm_api_key']:
            raise ConfigError(f"llm_api_key cannot be empty in secrets file {secrets_yaml_path}.")
        return secrets['llm_api_key']

class FileManager:
    @staticmethod
    def validate_data_folder(app_data_folder: Path) -> tuple:
        if not app_data_folder.exists() or not app_data_folder.is_dir():
            raise FileNotFoundError(f"Data folder not found: {app_data_folder}")

        required_files = ['secrets.yaml', 'config.yaml', 'plain_text_resume.yaml']
        missing_files = [file for file in required_files if not (app_data_folder / file).exists()]
        
        if missing_files:
            raise FileNotFoundError(f"Missing files in the data folder: {', '.join(missing_files)}")

        output_folder = app_data_folder / 'output'
        output_folder.mkdir(exist_ok=True)
        return (app_data_folder / 'secrets.yaml', app_data_folder / 'config.yaml', app_data_folder / 'plain_text_resume.yaml', output_folder)

    @staticmethod
    def file_paths_to_dict(resume_file: Path | None, plain_text_resume_file: Path) -> dict:
        if not plain_text_resume_file.exists():
            raise FileNotFoundError(f"Plain text resume file not found: {plain_text_resume_file}")

        result = {'plainTextResume': plain_text_resume_file}

        if resume_file:
            if not resume_file.exists():
                raise FileNotFoundError(f"Resume file not found: {resume_file}")
            result['resume'] = resume_file

        return result

def init_browser(headless: bool = False) -> webdriver.Chrome:
    try:
        options = chrome_browser_options(headless=headless)
        service = ChromeService(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=options)
    except Exception as e:
        raise RuntimeError(f"Failed to initialize browser: {str(e)}")

def create_and_run_bot(parameters: dict, llm_api_key: str, channel: str, config_file: Path):
    from src.job_application_profile import JobApplicationProfile
    from src.adapters.linkedin_adapter import LinkedInAdapter
    from src.adapters.telegram_adapter import TelegramAdapter
    from src.adapters.career_website_adapter import CareerWebsiteAdapter
    from loguru import logger
    
    try:
        with open(parameters['uploads']['plainTextResume'], "r", encoding='utf-8') as file:
            plain_text_resume = file.read()
            
        profile = JobApplicationProfile(plain_text_resume)
        
        adapter = None
        if channel == 'linkedin':
            adapter = LinkedInAdapter(profile, parameters, llm_api_key, config_file)
        elif channel == 'telegram':
            adapter = TelegramAdapter(profile, parameters, llm_api_key)
        elif channel == 'career_website':
            adapter = CareerWebsiteAdapter(profile, parameters, llm_api_key)
        else:
            raise ValueError(f"Unknown channel: {channel}")
            
        logger.info(f"Running bot for channel: {channel}")
        adapter.run()
        
    except Exception as e:
        raise RuntimeError(f"Error initializing or running bot: {str(e)}")

def prompt_for_channel():
    """Prompts the user to select a channel and returns the choice."""
    channels = {
        '1': 'linkedin',
        '2': 'career_website',
        '3': 'telegram',
        '4': 'all'
    }
    print("Please select the job application mode:")
    print("1: LinkedIn Easy Apply")
    print("2: Career Websites (from LinkedIn)")
    print("3: Telegram")
    print("4: All")

    while True:
        choice = input("Enter the number of your choice: ")
        if choice in channels:
            return channels[choice]
        else:
            print("Invalid choice. Please select a valid number.")

@click.command()
@click.option('--resume', type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path), help="Path to the resume PDF file")
@click.option('--collect', is_flag=True, help="Only collects data job information into data.json file")
def main(collect: bool, resume: Path = None):
    try:
        channel = prompt_for_channel()
        data_folder = Path("data_folder")
        secrets_file, config_file, plain_text_resume_file, output_folder = FileManager.validate_data_folder(data_folder)
        
        parameters = ConfigValidator.validate_config(config_file)
        llm_api_key = ConfigValidator.validate_secrets(secrets_file)
        
        parameters['uploads'] = FileManager.file_paths_to_dict(resume, plain_text_resume_file)
        parameters['outputFileDirectory'] = output_folder
        parameters['collectMode'] = collect
        parameters['channel'] = channel
        
        if channel == 'all':
            import threading
            logger.info("Starting all channels in parallel...")
            threads = []
            # Note: We run them in parallel. 
            # Career Website is under construction, so it will exit quickly.
            # LinkedIn and Telegram will run concurrently.
            for ch in ['linkedin', 'career_website', 'telegram']:
                t = threading.Thread(
                    target=create_and_run_bot, 
                    args=(parameters, llm_api_key, ch, config_file),
                    name=f"Bot-{ch}"
                )
                t.start()
                threads.append(t)
            
            for t in threads:
                t.join()
        else:
            create_and_run_bot(parameters, llm_api_key, channel, config_file)
            
    except ConfigError as ce:
        logger.error(f"Configuration error: {str(ce)}")
        logger.error(f"Refer to the configuration guide for troubleshooting: https://github.com/feder-cr/Auto_Jobs_Applier_AIHawk?tab=readme-ov-file#configuration {str(ce)}")
    except FileNotFoundError as fnf:
        logger.error(f"File not found: {str(fnf)}")
        logger.error("Ensure all required files are present in the data folder.")
    except RuntimeError as re:
        logger.error(f"Runtime error: {str(re)}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {str(e)}")

if __name__ == "__main__":
    main()
