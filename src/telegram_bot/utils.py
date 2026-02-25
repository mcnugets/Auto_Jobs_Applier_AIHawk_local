"""Utility functions for job parsing and message formatting."""
import re
from typing import List, Optional, Tuple
from jinja2 import Template

def match_python_keywords(text: str, keywords: List[str]) -> List[str]:
    """Check if text contains any Python-related keywords.
    
    Args:
        text: Text to search in (case-insensitive)
        keywords: List of keywords to match
        
    Returns:
        List of matched keywords
    """
    text_lower = text.lower()
    matched = []
    
    for keyword in keywords:
        # Use word boundaries to avoid partial matches
        pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
        if re.search(pattern, text_lower):
            matched.append(keyword)
    
    return matched

def extract_contact_info(text: str) -> Optional[str]:
    """Extract contact information from job description.
    
    Looks for:
    - Telegram handles (@username) - prioritized
    - Phone numbers
    - Email addresses
    
    Args:
        text: Job description text
        
    Returns:
        First found contact info (preferring Telegram), or None if not found
    """
    # Improved pattern for Telegram handles (@username)
    # Telegram usernames: 5-32 chars, letters, numbers, underscores only
    # Match @username that's not part of email address
    telegram_pattern = r'(?<![a-zA-Z0-9])@[a-zA-Z0-9_]{5,32}(?![a-zA-Z0-9@])'
    telegram_matches = re.findall(telegram_pattern, text)
    
    if telegram_matches:
        # Clean up matches (remove trailing non-word chars)
        cleaned = [match.rstrip('.,;:!?)]}>') for match in telegram_matches]
        # Prefer Telegram handles mentioned after common contact keywords
        contact_keywords = ['контакт', 'contact', 'написать', 'write', 'telegram', 
                           'телеграм', 'пишите', 'dm', 'напишите', 'связаться']
        
        text_lower = text.lower()
        for keyword in contact_keywords:
            keyword_pos = text_lower.find(keyword.lower())
            if keyword_pos != -1:
                # Look for @username near the keyword (within 50 chars)
                for match in cleaned:
                    match_pos = text.find(match)
                    if match_pos != -1 and abs(match_pos - keyword_pos) < 50:
                        return match
        
        # Return first Telegram handle found
        return cleaned[0]
    
    # Pattern for email addresses
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    email_matches = re.findall(email_pattern, text)
    if email_matches:
        return email_matches[0]  # Return first email
    
    # Pattern for phone numbers (various formats)
    phone_patterns = [
        r'\+?7\s?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{2}[-.\s]?\d{2}',  # Russian format
        r'\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # US format
        r'\+?[\d\s\-\(\)]{10,}',  # General international format
    ]
    
    for pattern in phone_patterns:
        phone_matches = re.findall(pattern, text)
        if phone_matches:
            return phone_matches[0].strip()  # Return first phone number
    
    return None

def has_website_application(text: str) -> bool:
    """Check if job requires applying through a website.
    
    Args:
        text: Job description text
        
    Returns:
        True if job requires website application, False otherwise
    """
    text_lower = text.lower()
    
    # Patterns that indicate website application required
    website_patterns = [
        r'https?://[^\s]+',  # Any HTTP/HTTPS URL
        r'www\.[^\s]+',  # www. URLs
        r'apply\s+(?:on|at|via|through)\s+[^\s]+',  # "apply on website"
        r'application\s+(?:on|at|via|through)\s+[^\s]+',  # "application via website"
    ]
    
    # Keywords that suggest website application
    website_keywords = [
        'apply online', 'apply on website', 'apply via website',
        'application form', 'online application', 'apply at',
        'подать заявку', 'заявка на сайте', 'подача на сайте',
        'отправить резюме на', 'резюме на сайте', 'заполнить форму'
    ]
    
    # Check for URL patterns
    for pattern in website_patterns:
        if re.search(pattern, text_lower):
            return True
    
    # Check for website keywords
    for keyword in website_keywords:
        if keyword in text_lower:
            return True
    
    return False

def format_message(template: str, job_title: Optional[str] = None) -> str:
    """Format the application message template using Jinja2.
    
    Args:
        template: Message template string (Jinja2 template)
        job_title: Optional job title to include in message
        
    Returns:
        Formatted message string
    """
    try:
        # Render template with Jinja2
        jinja_template = Template(template)
        message = jinja_template.render(job_title=job_title or '')
        return message.strip()
    except Exception as e:
        # Fallback to simple string replacement if Jinja2 fails
        message = template
        if job_title:
            message = message.replace('{{ job_title }}', job_title)
            message = message.replace('{job_title}', job_title)
        return message.strip()

def is_title_incorrect(title: str, description: str) -> bool:
    """Check if a job title is likely incorrect.
    
    A title is considered incorrect if:
    - It's too long (likely contains description)
    - It contains URLs or email addresses
    - It contains common non-title patterns
    - It's very short (less than 5 chars)
    - It starts with description-like phrases (Looking for, We are, etc.)
    - It has unmatched parentheses (incomplete extraction)
    - It's just hashtags or metadata
    
    Args:
        title: Current job title
        description: Full job description
        
    Returns:
        True if title is likely incorrect, False otherwise
    """
    if not title or not title.strip():
        return True
    
    title = title.strip()
    title_lower = title.lower()
    
    # Too short (probably incomplete)
    if len(title) < 5:
        return True
    
    # Too long (probably contains description text)
    if len(title) > 120:
        return True
    
    # Contains URLs (shouldn't be in title)
    if 'http://' in title_lower or 'https://' in title_lower or 'www.' in title_lower:
        return True
    
    # Contains email addresses (shouldn't be in title)
    if '@' in title and '.' in title and not title.startswith('@'):  # Allow @username
        return True
    
    # Starts with description-like phrases (these are descriptions, not titles)
    description_starters = [
        'looking for', 'we are looking', 'we\'re looking', 'we need',
        'collaborating with', 'working with', 'developing', 'building',
        'designing', 'greetings from', 'we are', 'we\'re', 'we seek',
        'ищем', 'ищется', 'требуется', 'нужен', 'нужны', 'нужна',
        'hello, everyone', 'hello everyone', 'hi,', 'greetings,',
        'typical responsibilities', 'responsibilities:', 'обязанности:'
    ]
    if any(title_lower.startswith(starter) for starter in description_starters):
        return True
    
    # Contains greeting phrases anywhere
    greeting_phrases = ['hello, everyone', 'hello everyone', 'hi everyone', 'greetings,', 'привет,']
    if any(phrase in title_lower for phrase in greeting_phrases):
        return True
    
    # Contains metadata patterns (not job titles)
    metadata_patterns = [
        'формат:', 'компания:', 'location:', 'format:', 'company:',
        'зп:', 'зарплата:', 'salary:', 'payment:', 'локция:', 'location:',
        'название:', 'названиe:', 'name:', 'title:', 'author:', 'автор:',
        'typical responsibilities', 'responsibilities:', 'обязанности:'
    ]
    if any(pattern in title_lower for pattern in metadata_patterns):
        return True
    
    # Only hashtags (not a proper title)
    if title.startswith('#'):
        # Check if it's mostly/all hashtags
        words = title.split()
        hashtag_count = sum(1 for word in words if word.startswith('#'))
        # If more than 2 hashtags or all words are hashtags, it's not a title
        if hashtag_count >= 2 or (len(words) > 0 and hashtag_count == len(words)):
            return True
    
    # Contains common non-title patterns
    bad_patterns = [
        'требования:', 'requirements:', 'обязанности:', 'responsibilities:',
        'условия:', 'conditions:', 'задачи:', 'tasks:', 'опыт:', 'experience:',
        'контакт:', 'contact:', 'написать:', 'write:', 'отправить:', 'send:',
        '•', '·', '---', '===', '___', 'author:', 'автор:'
    ]
    if any(pattern in title_lower for pattern in bad_patterns):
        return True
    
    # Has unmatched parentheses (incomplete extraction)
    open_paren = title.count('(')
    close_paren = title.count(')')
    if open_paren > close_paren:
        return True
    
    open_bracket = title.count('[')
    close_bracket = title.count(']')
    if open_bracket > close_bracket:
        return True
    
    # If title is exactly the first N chars of description (likely truncated)
    if description and title == description[:len(title)].strip():
        if len(description) > len(title) + 10:  # Description is significantly longer
            return True
    
    # Check if title contains job-related keywords (if not, might be wrong)
    job_keywords = ['python', 'developer', 'engineer', 'programmer', 'specialist',
                   'analyst', 'manager', 'lead', 'architect', 'designer', 'backend',
                   'frontend', 'fullstack', 'full-stack', 'devops', 'qa', 'test',
                   'вакансия', 'vacancy', 'работа', 'job', 'позиция', 'position',
                   'разработчик', 'инженер', 'аналитик']
    
    has_job_keyword = any(keyword in title_lower for keyword in job_keywords)
    
    # If title is long but has no job keywords, might be wrong
    if len(title) > 40 and not has_job_keyword:
        return True
    
    return False

def extract_job_title(text: str) -> str:
    """Smart job title extraction using heuristics.
    
    Args:
        text: Job description text
        
    Returns:
        Extracted title or first 100 characters
    """
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    if not lines:
        return text[:100].strip()
    
    # Job-related keywords that indicate a title line
    job_keywords = ['python', 'developer', 'engineer', 'programmer', 'specialist', 
                   'analyst', 'manager', 'lead', 'architect', 'designer', 'backend', 
                   'frontend', 'fullstack', 'full-stack', 'devops', 'qa', 'test',
                   'разработчик', 'инженер', 'аналитик', 'специалист']
    
    # Common prefixes that indicate a title (remove these and extract what follows)
    title_prefixes = ['вакансия:', 'vacancy:', 'ищем:', 'looking for', 'position:', 
                     'должность:', 'hiring:', 'требуется:', 'нужен:', 'needed:',
                     'we are looking for', 'we\'re looking for']
    
    # Skip lines that are clearly not titles
    skip_patterns = [
        'author:', 'автор:', 'message:', 'сообщение:', 'location:', 'локция:',
        'format:', 'формат:', 'company:', 'компания:', 'salary:', 'зп:', 'зарплата:',
        'profile:', 'профиль:', 'payment:', 'оплата:', 'название:', 'name:',
        'typical responsibilities', 'responsibilities:', 'обязанности:', 'задачи:',
        'hello, everyone', 'hello everyone', 'greetings,', 'привет,'
    ]
    
    # Score each potential title line
    candidates = []
    for i, line in enumerate(lines[:8]):  # Check first 8 lines
        if not line:
            continue
        
        original_line = line
        line_lower = line.lower()
        line_len = len(line)
        
        # Skip lines that are clearly metadata
        if any(line_lower.startswith(pattern) for pattern in skip_patterns):
            continue
        
        # Skip lines that are only/mostly hashtags
        words = line.split()
        hashtag_count = sum(1 for word in words if word.startswith('#'))
        if len(words) > 0 and (hashtag_count >= 2 or hashtag_count == len(words)):
            continue
        
        # Handle description starters - extract the actual job title from them
        extracted_from_description = False
        for prefix in sorted(title_prefixes, key=len, reverse=True):  # Try longest first
            if line_lower.startswith(prefix.lower()):
                # Extract title after prefix
                line = line[len(prefix):].strip()
                line_len = len(line)
                extracted_from_description = True
                # If it's a long sentence, try to extract just the job title part
                # Usually format is: "Looking for [Job Title] to [do something]"
                if ' to ' in line_lower or ' для ' in line_lower:
                    # Split and take first meaningful part
                    parts = re.split(r'\s+to\s+|\s+для\s+', line, flags=re.IGNORECASE)
                    if len(parts) > 1 and len(parts[0].strip()) > 5:
                        line = parts[0].strip()
                        line_len = len(line)
                break
        
        # Skip if line became empty after prefix removal
        if not line:
            continue
            
        score = 0
        
        # Prefer earlier lines (titles usually come first)
        score += (8 - i) * 3
        
        # Bonus if extracted from description starter (it's likely the title)
        if extracted_from_description:
            score += 25
        
        # Good length for titles (10-100 chars is typical)
        if 10 <= line_len <= 100:
            score += 10
        elif line_len < 10:
            score -= 10  # Too short
        elif line_len > 120:
            score -= 15  # Too long, probably description
        
        # Contains job-related keywords (strong indicator)
        keyword_matches = sum(1 for keyword in job_keywords if keyword in line_lower)
        if keyword_matches > 0:
            score += 15 * keyword_matches
        
        # Starts with capital letter (common for titles)
        if line and line[0].isupper():
            score += 5
        
        # Penalize lines with common non-title patterns
        bad_patterns = ['http://', 'https://', 'www.', 'author:', 'location:',
                       'требования:', 'requirements:', 'обязанности:', 'responsibilities:',
                       'условия:', 'conditions:', 'задачи:', 'tasks:', 'опыт:', 'experience:',
                       'компания:', 'company:', 'формат:', 'format:', 'collaborating with',
                       'working with', 'developing', 'building', 'designing']
        if any(pattern in line_lower for pattern in bad_patterns):
            score -= 25
        
        # Penalize lines that are URLs
        if line.startswith(('http://', 'https://', 'www.')):
            score -= 30
        
        # Penalize lines that are all caps and long (often headers/separators)
        if line.isupper() and line_len > 15:
            score -= 10
        
        # Penalize lines with too many hashtags
        hashtag_count = line.count('#')
        if hashtag_count > 2:
            score -= 15
        
        # Bonus for lines with common job title patterns
        title_patterns = [
            r'\b(?:Python|Django|Flask|FastAPI|React|Vue|Node|Java|Go|PHP)\s+[A-Z]?[a-z]+\s*(?:Developer|Engineer|Programmer|Specialist)?\b',
            r'\b(?:Senior|Middle|Junior|Lead|Team Lead)\s+[A-Z][a-z]+\s+(?:Developer|Engineer)\b',
            r'\b[A-Z][a-z]+\s+(?:Developer|Engineer|Programmer|Specialist|Analyst|Manager|Architect)\b',
            r'\b[A-Z][a-z]+(?:-|\s)?(?:разработчик|инженер|аналитик|специалист)\b',
        ]
        for pattern in title_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                score += 15
                break
        
        # Skip if score is too negative
        if score < -20:
            continue
        
        candidates.append((score, line, original_line))
    
    # Return highest scoring candidate
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_title = candidates[0][1]
        
        # Clean up the title
        # Remove trailing punctuation but keep parentheses if matched
        best_title = best_title.strip('.,;:!?')
        
        # Fix unmatched opening parentheses by removing them if description doesn't continue
        if best_title.count('(') > best_title.count(')'):
            # Remove the last unmatched opening paren and everything after it
            last_open = best_title.rfind('(')
            if last_open > 0:
                # Check if there's content before the paren that looks complete
                before_paren = best_title[:last_open].strip()
                if len(before_paren) > 5:  # If there's substantial content before, use that
                    best_title = before_paren
        
        # Limit length
        return best_title[:100]  # Limit to 100 chars for cleaner titles
    
    # Fallback: try to extract from first sentence if it's description-like
    first_line = lines[0]
    first_lower = first_line.lower()
    
    # If first line starts with "Looking for" or similar, try to extract job title
    for prefix in ['looking for', 'we are looking for', 'we\'re looking for', 'ищем', 'требуется']:
        if first_lower.startswith(prefix):
            # Extract what comes after
            extracted = first_line[len(prefix):].strip()
            # Remove "to [verb]" or similar continuations
            if ' to ' in extracted.lower():
                extracted = extracted.split(' to ')[0].strip()
            if len(extracted) > 5 and len(extracted) < 100:
                return extracted[:100]
    
    # Final fallback: return first line if it's reasonable
    if 10 <= len(first_line) <= 100:
        return first_line[:100]
    
    # Last resort: first 80 characters
    return text[:80].strip()

