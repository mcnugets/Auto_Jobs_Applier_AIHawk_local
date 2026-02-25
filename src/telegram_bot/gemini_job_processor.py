"""Gemini-based job message processing to extract and clean job data."""
import logging
import json
from typing import Optional, Dict, List
from pydantic import BaseModel, Field, ValidationError
import google.generativeai as genai

from .config import GEMINI_API_KEY, GEMINI_MODEL, PYTHON_KEYWORDS

logger = logging.getLogger(__name__)


class ProcessedJobData(BaseModel):
    """Structured output for processed job data."""
    is_python_job: bool = Field(description="Whether this is a Python-related job")
    matched_keywords: List[str] = Field(description="List of Python keywords found in the job")
    job_title: str = Field(description="Extracted and cleaned job title (max 100 characters)")
    contact_info: Optional[str] = Field(description="Extracted contact information (Telegram handle preferred, e.g., @username). Only include if explicitly mentioned as a contact method, not just any @ mention.")
    requires_website_application: bool = Field(description="Whether job requires applying via website")
    cleaned_description: str = Field(description="Cleaned job description (removed metadata, greetings, etc.)")
    reason: str = Field(default="", description="Brief reason/notes about the processing")


class JobBatchItem(BaseModel):
    """Single job item in a batch."""
    job_id: str = Field(description="Unique job identifier")
    raw_message: str = Field(description="Raw job posting message text")
    source_channel: str = Field(description="Source channel name")


class BatchJobResponse(BaseModel):
    """Response containing batch of processed jobs."""
    jobs: List[ProcessedJobData] = Field(description="List of processed job data in the same order as input")


_gemini_configured = False

def setup_gemini():
    """Setup Gemini API (only once)."""
    global _gemini_configured
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is required in .env file")
    if not _gemini_configured:
        genai.configure(api_key=GEMINI_API_KEY)
        _gemini_configured = True

_current_model_index = 0

def get_gemini_models():
    """Get list of available Gemini models from config."""
    if not GEMINI_MODEL:
        return []
    if isinstance(GEMINI_MODEL, str) and ',' in GEMINI_MODEL:
        return [m.strip() for m in GEMINI_MODEL.split(',')]
    return [GEMINI_MODEL]

async def process_job_batch(batch: List[Dict], retry_count: int = 0) -> List[ProcessedJobData]:
    """Process a batch of job messages using Gemini with model rotation fallback.
    
    Args:
        batch: List of job dictionaries with 'job_id', 'raw_message', 'source_channel'
        retry_count: Internal counter for model rotation retries
        
    Returns:
        List of ProcessedJobData objects (same order as input batch)
    """
    global _current_model_index
    
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not configured. Cannot use Gemini for processing.")
        return []
    
    if not batch:
        return []
    
    models = get_gemini_models()
    if not models:
        logger.warning("No Gemini models configured.")
        return []
        
    model_name = models[_current_model_index % len(models)]
    
    try:
        setup_gemini()
        model = genai.GenerativeModel(model_name)
        
        # Format jobs for prompt
        jobs_text = "\n\n".join([
            f"[Job {i+1} - ID: {job['job_id']}]\n"
            f"Channel: {job.get('source_channel', 'Unknown')}\n"
            f"Message:\n{job['raw_message'][:1500]}"  # Limit message length
            for i, job in enumerate(batch)
        ])
        
        # Create schema for structured output
        schema = BatchJobResponse.model_json_schema()
        
        # List of Python keywords for context
        python_keywords_str = ", ".join(PYTHON_KEYWORDS)
        
        prompt = f"""Analyze these {len(batch)} job postings and extract structured information for each.

{jobs_text}

Python Keywords to look for: {python_keywords_str}

For EACH job posting, extract:

1. **is_python_job**: True if this job is related to Python development (check for keywords: {python_keywords_str})
2. **matched_keywords**: List of Python keywords found in the job posting
3. **job_title**: Extract the actual job title (clean it):
   - Remove greetings (Hello, everyone, Hi, etc.)
   - Remove hashtags from title (e.g., #python #backend)
   - Remove metadata from title (Format:, Company:, Location:, etc.)
   - Title should be max 100 characters
   - Example: "Python Developer", "Senior Backend Engineer"

4. **contact_info**: Extract contact information, BUT BE CAREFUL:
   - ONLY extract @username if it's explicitly mentioned as a CONTACT METHOD
   - Look for context like: 
     * English: "contact @username", "write to @username", "telegram: @username", "DM @username", "send to @username", "apply to @username"
     * Russian: "напишите @username", "контакт @username", "присылать @username", "отправлять @username", 
       "в личку @username", "написать @username", "писать @username", "отправить @username",
       "прислать @username", "отправьте @username", "напиши @username", "пишите @username",
       "отправляйте @username", "присылайте @username", "можно присылать @username",
       "можно отправлять @username", "присылайте cv @username", "отправляйте резюме @username"
   - DO NOT extract @username if it's just mentioned casually (could be a Telegram group/channel mention)
   - DO NOT extract @username if it's in author/author information
   - Prefer Telegram handles (@username) if available as contact, otherwise email/phone
   - If no clear contact method is mentioned, extract closest contact possible that does not have suffix or prefix "bot" in the username
5. **requires_website_application**: True if job requires applying via website (look for URLs, "apply online", "apply via website", etc.)
6. **cleaned_description**: Clean the description:
   - Remove metadata headers (Format:, Company:, Location:, Author:, etc.)
   - Remove greetings at the start
   - Keep job requirements, responsibilities, and details
   - Keep hashtags if they're relevant job tags
7. **reason**: Brief reason or notes about the processing (REQUIRED field):
   - Examples: "Valid Python job with Telegram contact", "No contact found", "Website application required", "Not a Python job", "Contact extracted from explicit instruction"

CRITICAL CONTACT EXTRACTION RULES:
- Only extract @username if there's explicit instruction to contact/write/DM/send to that username
- Common patterns include: "send to @username", "write to @username", "DM @username", 
  "присылать @username", "отправлять @username", "в личку @username", "написать @username"
- Skip @username if it appears in "Author:" or similar metadata fields
- Skip @username if it's clearly a group/channel mention without contact context
- If job says "contact @john" or "write to @john" or "присылать @john" or "в личку @john" → extract @john
- If job just mentions "@some_group" without contact context → DO NOT extract it

Return JSON array with results in the SAME ORDER as input jobs (Job 1 → first result, Job 2 → second result, etc.).

Return ONLY valid JSON matching this schema:
{json.dumps(schema, indent=2)}

Return ONLY valid JSON, no markdown, no code blocks, just the JSON object."""
        
        logger.info(f"Processing batch of {len(batch)} jobs with Gemini model: {model_name}...")
        
        response = await model.generate_content_async(prompt)
        response_text = response.text.strip()
        
        # Extract JSON from response (in case it's wrapped in markdown code blocks)
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        elif response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        # Parse JSON and validate with Pydantic
        result_data = json.loads(response_text)
        batch_response = BatchJobResponse(**result_data)
        
        if batch_response.jobs and len(batch_response.jobs) == len(batch):
            logger.info(f"Successfully processed {len(batch_response.jobs)} jobs using {model_name}")
            return batch_response.jobs
        else:
            logger.warning(f"Gemini ({model_name}) returned {len(batch_response.jobs) if batch_response.jobs else 0} jobs, expected {len(batch)}")
            return batch_response.jobs if batch_response.jobs else []
    
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response from Gemini ({model_name}): {str(e)}")
        logger.debug(f"Response was: {response_text[:500] if 'response_text' in locals() else 'N/A'}")
        return []
    except ValidationError as e:
        logger.error(f"Validation error processing job batch ({model_name}): {str(e)}")
        return []
    except Exception as e:
        error_msg = str(e)
        if ("429" in error_msg or "ResourceExhausted" in error_msg) and retry_count < len(models) - 1:
            _current_model_index += 1
            new_model = models[_current_model_index % len(models)]
            logger.warning(f"Quota reached for {model_name}. Switching to next model: {new_model}")
            return await process_job_batch(batch, retry_count + 1)
            
        logger.error(f"Error processing job batch with Gemini ({model_name}): {str(e)}", exc_info=True)
        return []


async def process_job_message(message_text: str) -> Optional[ProcessedJobData]:
    """Process a single job message using Gemini (legacy function for backward compatibility).
    
    Args:
        message_text: Raw job posting message text
        
    Returns:
        ProcessedJobData if successful, None if processing fails
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not configured. Cannot use Gemini for processing.")
        return None
    
    if not message_text or not message_text.strip():
        return None
    
    # Use batch processing with single item
    batch = [{'job_id': 'single', 'raw_message': message_text, 'source_channel': 'unknown'}]
    results = await process_job_batch(batch)
    
    return results[0] if results else None
