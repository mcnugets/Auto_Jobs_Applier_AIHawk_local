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
                return yaml.safe_load(stream)
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
            if key not in parameters:
                if key in ['company_blacklist', 'title_blacklist', 'location_blacklist']:
                    parameters[key] = []
                else:
                    raise ConfigError(f"Missing or invalid key '{key}' in config file {config_yaml_path}")
            elif not isinstance(parameters[key], expected_type):
                if key in ['company_blacklist', 'title_blacklist', 'location_blacklist'] and parameters[key] is None:
                    parameters[key] = []
                else:
                    raise ConfigError(f"Invalid type for key '{key}' in config file {config_yaml_path}. Expected {expected_type}.")

        # Validate experience levels, ensure they are boolean
        experience_levels = ['internship', 'entry', 'associate', 'mid-senior level', 'director', 'executive']
        for level in experience_levels:
            if not isinstance(parameters['experienceLevel'].get(level), bool):
                raise ConfigError(f"Experience level '{level}' must be a boolean in config file {config_yaml_path}")

        # Validate job types, ensure they are boolean
        job_types = ['full-time', 'contract', 'part-time', 'temporary', 'internship', 'other', 'volunteer']
        for job_type in job_types:
            if not isinstance(parameters['jobTypes'].get(job_type), bool):
                raise ConfigError(f"Job type '{job_type}' must be a boolean in config file {config_yaml_path}")

        # Validate date filters
        date_filters = ['all time', 'month', 'week', '24 hours']
        for date_filter in date_filters:
            if not isinstance(parameters['date'].get(date_filter), bool):
                raise ConfigError(f"Date filter '{date_filter}' must be a boolean in config file {config_yaml_path}")

        # Validate positions and locations as lists of strings
        if not all(isinstance(pos, str) for pos in parameters['positions']):
            raise ConfigError(f"'positions' must be a list of strings in config file {config_yaml_path}")
        if not all(isinstance(loc, str) for loc in parameters['locations']):
            raise ConfigError(f"'locations' must be a list of strings in config file {config_yaml_path}")

        # Validate distance
        approved_distances = {0, 5, 10, 25, 50, 100}
        if parameters['distance'] not in approved_distances:
            raise ConfigError(f"Invalid distance value in config file {config_yaml_path}. Must be one of: {approved_distances}")

        # Ensure blacklists are lists
        for blacklist in ['company_blacklist', 'title_blacklist','location_blacklist']:
            if not isinstance(parameters.get(blacklist), list):
                raise ConfigError(f"'{blacklist}' must be a list in config file {config_yaml_path}")
            if parameters[blacklist] is None:
                parameters[blacklist] = []

        return parameters

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

def create_and_run_bot(parameters: dict, llm_api_key: str, channel: str):
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
            adapter = LinkedInAdapter(profile, parameters, llm_api_key)
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

@click.command()
@click.option('--channel', type=click.Choice(['telegram', 'linkedin', 'career_website', 'all']), default='linkedin', help="Choose application channel")
@click.option('--resume', type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path), help="Path to the resume PDF file")
@click.option('--collect', is_flag=True, help="Only collects data job information into data.json file")
def main(channel: str, collect: bool, resume: Path = None):
    try:
        data_folder = Path("data_folder")
        secrets_file, config_file, plain_text_resume_file, output_folder = FileManager.validate_data_folder(data_folder)
        
        parameters = ConfigValidator.validate_config(config_file)
        llm_api_key = ConfigValidator.validate_secrets(secrets_file)
        
        parameters['uploads'] = FileManager.file_paths_to_dict(resume, plain_text_resume_file)
        parameters['outputFileDirectory'] = output_folder
        parameters['collectMode'] = collect
        parameters['channel'] = channel
        
        if channel == 'all':
            logger.warning("Running all channels sequentially...")
            for ch in ['linkedin', 'telegram', 'career_website']:
                create_and_run_bot(parameters, llm_api_key, ch)
        else:
            create_and_run_bot(parameters, llm_api_key, channel)
            
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
