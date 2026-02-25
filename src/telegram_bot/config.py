"""Configuration management for the job application bot."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram API credentials
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
PHONE_NUMBER = os.getenv('PHONE_NUMBER')

# Path to CV file
CV_PATH = os.getenv('CV_PATH', 'cv.pdf')

# Telegram channels to monitor (comma-separated)
CHANNELS_STR = os.getenv('CHANNELS', '')
# Remove @ symbol if present and strip whitespace
CHANNELS = [ch.strip().lstrip('@') for ch in CHANNELS_STR.split(',') if ch.strip()]



# """Hello!

# I came across your job posting and I'm very interested in this opportunity. 

# I believe my skills and experience align well with what you're looking for. Please find my CV attached.

# Looking forward to hearing from you!

# Best regards,
# Sultan"""

# Application message template (uses Jinja2 templating, {{ job_title }} will be replaced)
# This is the static fallback if dynamic LLM generation fails or is disabled
MESSAGE_TEMPLATE = os.getenv(
    'MESSAGE_TEMPLATE',
    default="""Здравствуйте!

Я увидел вашу вакансию {{ job_title }} и очень заинтересован в этой возможности.

Мои навыки и опыт соответствуют требованиям вашей позиции. Пожалуйста, ознакомьтесь с моим резюме в приложении.

Буду рад возможности обсудить детали.

С уважением,
Султан"""
)

# Dynamic prompt template for LLM message generation
TELEGRAM_MESSAGE_PROMPT = os.getenv(
    'TELEGRAM_MESSAGE_PROMPT',
    default="Use the provided job application profile and job description to write a message on telegram to the recruiter applying for this job. Keep it under 150 words. Do not use markdown formatting like bolding or italics. Be enthusiastic and professional. Start with a greeting and end with a sign-off using the candidate's name (Sultangazy)."
)

# Dynamic prompt template for LLM CV generation
CV_GENERATION_PROMPT = os.getenv(
    'CV_GENERATION_PROMPT',
    default="Based on the following job description and my professional profile, optimize my CV to highlight the most relevant skills and experiences. Ensure the tone is professional and the content is concise. Focus on the technologies and responsibilities mentioned in the job posting."
)

# Dynamic prompt template for LLM Cover Letter generation
COVER_LETTER_PROMPT = os.getenv(
    'COVER_LETTER_PROMPT',
    default="Write a compelling cover letter for the following job position. Use my professional profile to tailor the letter to the specific requirements of the role. The letter should be professional, highlight my fit for the company, and express my enthusiasm for the opportunity. Keep it to one page."
)

# Database path
DB_PATH = os.getenv('DB_PATH', 'jobs.db')

# Session file path (Telethon)
SESSION_PATH = os.getenv('SESSION_PATH', 'telegram_session')

# Python keywords to match in job descriptions
PYTHON_KEYWORDS = [
    'python', 'django', 'flask', 'fastapi', 'pandas', 'numpy',
    'scikit-learn', 'tensorflow', 'pytorch', 'opencv', 'selenium',
    'beautifulsoup', 'requests', 'sqlalchemy', 'pytest', 'celery',
    'redis', 'postgresql', 'mysql', 'mongodb', 'docker', 'kubernetes',
    'aws', 'gcp', 'azure', 'api', 'rest', 'graphql', 'microservices'
]

# Gemini API key (optional, for title cleaning)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-pro')

# Validate required configuration
def validate_config():
    """Validate that all required configuration values are present."""
    import yaml
    from pathlib import Path

    # Attempt to read from the master secrets.yaml in AIHawk
    secrets_path = Path("data_folder/secrets.yaml")
    hawk_secrets = {}
    if secrets_path.exists():
        try:
            with open(secrets_path, 'r') as stream:
                hawk_secrets = yaml.safe_load(stream) or {}
        except Exception:
            pass

    # Use globals or fallback to hawk_secrets
    global API_ID, API_HASH, PHONE_NUMBER, GEMINI_API_KEY, TELEGRAM_MESSAGE_PROMPT, MESSAGE_TEMPLATE, CV_PATH, CV_GENERATION_PROMPT, COVER_LETTER_PROMPT, CHANNELS
    
    API_ID = API_ID or hawk_secrets.get('telegram_api_id')
    API_HASH = API_HASH or hawk_secrets.get('telegram_api_hash')
    PHONE_NUMBER = PHONE_NUMBER or hawk_secrets.get('telegram_phone_number')
    GEMINI_API_KEY = GEMINI_API_KEY or hawk_secrets.get('gemini_api_key')
    TELEGRAM_MESSAGE_PROMPT = hawk_secrets.get('telegram_message_prompt', TELEGRAM_MESSAGE_PROMPT)
    MESSAGE_TEMPLATE = hawk_secrets.get('telegram_static_message_template', MESSAGE_TEMPLATE)
    CV_PATH = hawk_secrets.get('telegram_static_cv_path', CV_PATH)
    CV_GENERATION_PROMPT = hawk_secrets.get('cv_generation_prompt', CV_GENERATION_PROMPT)
    COVER_LETTER_PROMPT = hawk_secrets.get('cover_letter_prompt', COVER_LETTER_PROMPT)

    # Allow channels to be defined in secrets.yaml as well
    if 'telegram_channels' in hawk_secrets:
        new_channels_str = hawk_secrets['telegram_channels']
        if isinstance(new_channels_str, list):
            CHANNELS = [str(ch).strip().lstrip('@') for ch in new_channels_str if str(ch).strip()]
        else:
            CHANNELS = [ch.strip().lstrip('@') for ch in str(new_channels_str).split(',') if ch.strip()]

    errors = []
    
    if not API_ID:
        errors.append("API_ID is required in .env file or data_folder/secrets.yaml")
    if not API_HASH:
        errors.append("API_HASH is required in .env file or data_folder/secrets.yaml")
    if not PHONE_NUMBER:
        errors.append("PHONE_NUMBER is required in .env file or data_folder/secrets.yaml")
    if not CHANNELS:
        errors.append("CHANNELS is required in .env file (comma-separated list)")
    if not os.path.exists(CV_PATH):
        logger = logging.getLogger(__name__)
        logger.warning(f"Static CV file not found at {CV_PATH}. Telegram Applier will strictly rely on Dynamic CV Generation.")
    
    if errors:
        raise ValueError("Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))
    
    return True

