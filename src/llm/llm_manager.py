import json
import os
import re
import textwrap
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from typing import Union, Any

import httpx
from Levenshtein import distance
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage
from langchain_core.messages.ai import AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompt_values import StringPromptValue
from langchain_core.prompts import ChatPromptTemplate

import src.strings as strings
from loguru import logger

load_dotenv()


class AIModel(ABC):
    @abstractmethod
    def invoke(self, prompt: str) -> str:
        pass


class OpenAIModel(AIModel):
    def __init__(self, api_key: str, llm_model: str):
        from langchain_openai import ChatOpenAI
        self.model = ChatOpenAI(model_name=llm_model, openai_api_key=api_key,
                                temperature=0.4)

    def invoke(self, prompt: str) -> BaseMessage:
        logger.debug("Invoking OpenAI API")
        response = self.model.invoke(prompt)
        return response


class ClaudeModel(AIModel):
    def __init__(self, api_key: str, llm_model: str):
        from langchain_anthropic import ChatAnthropic
        self.model = ChatAnthropic(model=llm_model, api_key=api_key,
                                   temperature=0.4)

    def invoke(self, prompt: str) -> BaseMessage:
        response = self.model.invoke(prompt)
        logger.debug("Invoking Claude API")
        return response


class OllamaModel(AIModel):
    def __init__(self, llm_model: str, llm_api_url: str):
        from langchain_ollama import ChatOllama

        if len(llm_api_url) > 0:
            logger.debug(f"Using Ollama with API URL: {llm_api_url}")
            self.model = ChatOllama(model=llm_model, base_url=llm_api_url)
        else:
            self.model = ChatOllama(model=llm_model)

    def invoke(self, prompt: str) -> BaseMessage:
        response = self.model.invoke(prompt)
        return response

#gemini doesn't seem to work because API doesn't rstitute answers for questions that involve answers that are too short
class GeminiModel(AIModel):
    def __init__(self, api_key: str, llm_model: str):
        # Handle multiple API keys for rotation
        if isinstance(api_key, str) and ',' in api_key:
            self.api_keys = [k.strip() for k in api_key.split(',')]
        else:
            self.api_keys = [api_key]
        
        self.current_key_index = 0
        
        # Parse potential list of models
        if isinstance(llm_model, str) and ',' in llm_model:
            self.model_list = [m.strip() for m in llm_model.split(',')]
        elif isinstance(llm_model, list):
            self.model_list = llm_model
        else:
            self.model_list = [llm_model]
        
        self.current_model_index = 0
        self._init_model()

    def _init_model(self):
        from langchain_google_genai import ChatGoogleGenerativeAI, HarmBlockThreshold, HarmCategory
        model_name = self.model_list[self.current_model_index]
        api_key = self.api_keys[self.current_key_index]
        
        logger.debug(f"Initializing Gemini with model: {model_name} (Key index: {self.current_key_index})")
        # Set max_retries=0 to ensure our custom rotation logic triggers immediately on 429
        self.model = ChatGoogleGenerativeAI(
            model=model_name, 
            google_api_key=api_key, 
            max_retries=0,
            safety_settings={
                HarmCategory.HARM_CATEGORY_UNSPECIFIED: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DEROGATORY: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_TOXICITY: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_VIOLENCE: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUAL: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_MEDICAL: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE
            }
        )

    def invoke(self, prompt: str, combinations_tried: int = 0) -> BaseMessage:
        # Prevent infinite recursion if all combinations fail
        max_combinations = len(self.api_keys) * len(self.model_list)
        if combinations_tried >= max_combinations:
            logger.critical("All Gemini API key and model combinations failed.")
            raise RuntimeError("Gemini API quota exceeded for all models across all provided keys.")

        try:
            return self.model.invoke(prompt)
        except Exception as e:
            error_msg = str(e)
            
            # 1. Check for Quota/Auth errors (429, ResourceExhausted, 401)
            if "429" in error_msg or "ResourceExhausted" in error_msg or "401" in error_msg:
                # Try next MODEL in the list first for the current API KEY
                if self.current_model_index < len(self.model_list) - 1:
                    old_model = self.model_list[self.current_model_index]
                    self.current_model_index += 1
                    new_model = self.model_list[self.current_model_index]
                    logger.warning(f"Model {old_model} quota reached on Key #{self.current_key_index + 1}. Trying next model: {new_model}")
                else:
                    # All models exhausted for this key, rotate to next API KEY and reset model index
                    if len(self.api_keys) > 1:
                        old_key_index = self.current_key_index
                        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
                        self.current_model_index = 0
                        logger.warning(f"All models exhausted for Key #{old_key_index + 1}. Rotating to API Key #{self.current_key_index + 1} and resetting model sequence.")
                    else:
                        # Only one key provided and all models for it are exhausted
                        logger.critical(f"All configured models exhausted for the only available API Key. Error: {error_msg}")
                        raise e
                
                self._init_model()
                # Small sleep to let the gateway settle
                time.sleep(1)
                return self.invoke(prompt, combinations_tried + 1)
            
            # 2. Check for Model not found errors (404)
            if "404" in error_msg or "not found" in error_msg.lower():
                if self.current_model_index < len(self.model_list) - 1:
                    old_model = self.model_list[self.current_model_index]
                    self.current_model_index += 1
                    new_model = self.model_list[self.current_model_index]
                    logger.warning(f"Gemini model {old_model} not found. Skipping to next model: {new_model}")
                    self._init_model()
                    return self.invoke(prompt, combinations_tried + 1)
            
            # If we reached here, it's a different kind of error
            logger.error(f"Gemini execution error: {error_msg}")
            raise e

class HuggingFaceModel(AIModel):
    def __init__(self, api_key: str, llm_model: str):
        from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace
        self.model = HuggingFaceEndpoint(repo_id=llm_model, huggingfacehub_api_token=api_key,
                                   temperature=0.4)
        self.chatmodel=ChatHuggingFace(llm=self.model)

    def invoke(self, prompt: str) -> BaseMessage:
        response = self.chatmodel.invoke(prompt)
        logger.debug("Invoking Model from Hugging Face API")
        print(response,type(response))
        return response

class AIAdapter:
    def __init__(self, config: dict, api_key: str):
        self.model = self._create_model(config, api_key)

    def _create_model(self, config: dict, api_key: str) -> AIModel:
        llm_model_type = config.get('llm_model_type', 'openai')
        llm_model = config.get('llm_model', 'gpt-4o-mini')

        llm_api_url = config.get('llm_api_url', "")

        logger.debug(f"Using {llm_model_type} with {llm_model}")

        if llm_model_type == "openai":
            return OpenAIModel(api_key, llm_model)
        elif llm_model_type == "claude":
            return ClaudeModel(api_key, llm_model)
        elif llm_model_type == "ollama":
            return OllamaModel(llm_model, llm_api_url)
        elif llm_model_type in ["gemini", "google"]:
            return GeminiModel(api_key, llm_model)
        elif llm_model_type == "huggingface":
            return HuggingFaceModel(api_key, llm_model)        
        else:
            raise ValueError(f"Unsupported model type: {llm_model_type}")

    def invoke(self, prompt: str) -> str:
        return self.model.invoke(prompt)


class LLMLogger:

    def __init__(self, llm: Union[OpenAIModel, OllamaModel, ClaudeModel, GeminiModel]):
        self.llm = llm
        logger.debug(f"LLMLogger successfully initialized with LLM: {llm}")

    @staticmethod
    def log_request(prompts, parsed_reply: Dict[str, Dict]):
        logger.debug("Starting log_request method")
        logger.debug(f"Prompts received: {prompts}")
        logger.debug(f"Parsed reply received: {parsed_reply}")

        try:
            calls_log = os.path.join(
                Path("data_folder/output"), "open_ai_calls.json")
            logger.debug(f"Logging path determined: {calls_log}")
        except Exception as e:
            logger.error(f"Error determining the log path: {str(e)}")
            raise

        if isinstance(prompts, StringPromptValue):
            logger.debug("Prompts are of type StringPromptValue")
            prompts = prompts.text
            logger.debug(f"Prompts converted to text: {prompts}")
        elif isinstance(prompts, list):
            logger.debug("Prompts are of type list")
            try:
                prompts = {
                    f"prompt_{i + 1}": prompt.content if hasattr(prompt, 'content') else str(prompt)
                    for i, prompt in enumerate(prompts)
                }
                logger.debug(f"Prompts converted to dictionary: {prompts}")
            except Exception as e:
                logger.error(f"Error converting prompts list to dictionary: {str(e)}")
                raise
        elif hasattr(prompts, 'messages'):
            logger.debug("Prompts have 'messages' attribute")
            try:
                prompts = {
                    f"prompt_{i + 1}": prompt.content if hasattr(prompt, 'content') else str(prompt)
                    for i, prompt in enumerate(prompts.messages)
                }
                logger.debug(f"Prompts converted to dictionary: {prompts}")
            except Exception as e:
                logger.error(f"Error converting prompts.messages to dictionary: {str(e)}")
                raise
        else:
            logger.debug("Prompts are of unknown type, attempting fallback string conversion")
            prompts = {"prompt_1": str(prompts)}

        try:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.debug(f"Current time obtained: {current_time}")
        except Exception as e:
            logger.error(f"Error obtaining current time: {str(e)}")
            raise

        try:
            token_usage = parsed_reply["usage_metadata"]
            output_tokens = token_usage["output_tokens"]
            input_tokens = token_usage["input_tokens"]
            total_tokens = token_usage["total_tokens"]
            logger.debug(f"Token usage - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}")
        except KeyError as e:
            logger.error(f"KeyError in parsed_reply structure: {str(e)}")
            raise

        try:
            model_name = parsed_reply["response_metadata"]["model_name"]
            logger.debug(f"Model name: {model_name}")
        except KeyError as e:
            logger.error(f"KeyError in response_metadata: {str(e)}")
            raise

        try:
            prompt_price_per_token = 0.00000015
            completion_price_per_token = 0.0000006
            total_cost = (input_tokens * prompt_price_per_token) + \
                (output_tokens * completion_price_per_token)
            logger.debug(f"Total cost calculated: {total_cost}")
        except Exception as e:
            logger.error(f"Error calculating total cost: {str(e)}")
            raise

        try:
            log_entry = {
                "model": model_name,
                "time": current_time,
                "prompts": prompts,
                "replies": parsed_reply["content"],
                "total_tokens": total_tokens,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_cost": total_cost,
            }
            logger.debug(f"Log entry created: {log_entry}")
        except KeyError as e:
            logger.error(f"Error creating log entry: missing key {str(e)} in parsed_reply")
            raise

        try:
            with open(calls_log, "a", encoding="utf-8") as f:
                json_string = json.dumps(
                    log_entry, ensure_ascii=False, indent=4)
                f.write(json_string + "\n")
                logger.debug(f"Log entry written to file: {calls_log}")
        except Exception as e:
            logger.error(f"Error writing log entry to file: {str(e)}")
            raise


class LoggerChatModel:

    def __init__(self, llm: Union[OpenAIModel, OllamaModel, ClaudeModel, GeminiModel]):
        self.llm = llm
        logger.debug(f"LoggerChatModel successfully initialized with LLM: {llm}")

    def __call__(self, messages: List[Dict[str, str]]) -> str:
        return self.invoke(messages)

    def invoke(self, input_data: Union[str, List[Dict[str, str]], Any]) -> AIMessage:
        logger.debug(f"Entering invoke method with input: {input_data}")
        
        # Convert input to a format the adapter expects (adapter.invoke expects a string or list)
        # But adapter calls model.invoke, which for Langchain models handles ChatPromptValue, list of messages, etc.
        
        while True:
            try:
                logger.debug("Attempting to call the LLM")

                # Handle Langchain ChatPromptValue or individual strings
                if hasattr(input_data, 'to_messages'):
                    messages = input_data.to_messages()
                else:
                    messages = input_data

                reply = self.llm.invoke(messages)
                logger.debug(f"LLM response received: {reply}")

                # If the reply is an AIMessage, we must return it for LCEL chains to work with StrOutputParser
                # If it's a string, we wrap it
                if isinstance(reply, str):
                    logger.warning("LLM returned string instead of AIMessage in LoggerChatModel. Wrapping.")
                    reply_message = AIMessage(content=reply)
                else:
                    reply_message = reply

                parsed_reply = self.parse_llmresult(reply_message)
                logger.debug(f"Parsed LLM reply: {parsed_reply}")

                LLMLogger.log_request(
                    prompts=messages, parsed_reply=parsed_reply)
                logger.debug("Request successfully logged")

                return reply_message

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTPStatusError encountered: {str(e)}")
                if e.response.status_code == 429:
                    retry_after = e.response.headers.get('retry-after')
                    retry_after_ms = e.response.headers.get('retry-after-ms')

                    if retry_after:
                        wait_time = int(retry_after)
                        logger.warning(
                            f"Rate limit exceeded. Waiting for {wait_time} seconds before retrying (extracted from 'retry-after' header)...")
                        time.sleep(wait_time)
                    elif retry_after_ms:
                        wait_time = int(retry_after_ms) / 1000.0
                        logger.warning(
                            f"Rate limit exceeded. Waiting for {wait_time} seconds before retrying (extracted from 'retry-after-ms' header)...")
                        time.sleep(wait_time)
                    else:
                        wait_time = 30
                        logger.warning(
                            f"'retry-after' header not found. Waiting for {wait_time} seconds before retrying (default)...")
                        time.sleep(wait_time)
                else:
                    logger.error(f"HTTP error occurred with status code: {e.response.status_code}, waiting 30 seconds before retrying")
                    time.sleep(30)

            except Exception as e:
                logger.error(f"Unexpected error occurred: {str(e)}")
                logger.info(
                    "Waiting for 30 seconds before retrying due to an unexpected error.")
                time.sleep(30)
                continue

    def parse_llmresult(self, llmresult: AIMessage) -> Dict[str, Dict]:
        logger.debug(f"Parsing LLM result: {llmresult}")

        try:
            if hasattr(llmresult, 'usage_metadata'):
                content = llmresult.content
                response_metadata = llmresult.response_metadata
                id_ = llmresult.id
                usage_metadata = llmresult.usage_metadata

                parsed_result = {
                    "content": content,
                    "response_metadata": {
                        "model_name": response_metadata.get("model_name", ""),
                        "system_fingerprint": response_metadata.get("system_fingerprint", ""),
                        "finish_reason": response_metadata.get("finish_reason", ""),
                        "logprobs": response_metadata.get("logprobs", None),
                    },
                    "id": id_,
                    "usage_metadata": {
                        "input_tokens": usage_metadata.get("input_tokens", 0),
                        "output_tokens": usage_metadata.get("output_tokens", 0),
                        "total_tokens": usage_metadata.get("total_tokens", 0),
                    },
                }
            else :  
                content = llmresult.content
                response_metadata = llmresult.response_metadata
                id_ = llmresult.id
                token_usage = response_metadata['token_usage']

                parsed_result = {
                    "content": content,
                    "response_metadata": {
                        "model_name": response_metadata.get("model", ""),
                        "finish_reason": response_metadata.get("finish_reason", ""),
                    },
                    "id": id_,
                    "usage_metadata": {
                        "input_tokens": token_usage.prompt_tokens,
                        "output_tokens": token_usage.completion_tokens,
                        "total_tokens": token_usage.total_tokens,
                    },
                }                  
            logger.debug(f"Parsed LLM result successfully: {parsed_result}")
            return parsed_result

        except KeyError as e:
            logger.error(
                f"KeyError while parsing LLM result: missing key {str(e)}")
            raise

        except Exception as e:
            logger.error(
                f"Unexpected error while parsing LLM result: {str(e)}")
            raise


class GPTAnswerer:

    def __init__(self, config, llm_api_key):
        self.config = config
        self.ai_adapter = AIAdapter(config, llm_api_key)
        self.llm_cheap = LoggerChatModel(self.ai_adapter)
        self.cached_artifacts = {}
        self.resume = None
        self.job = None
        self._job_description = ""

    @property
    def job_description(self):
        if self.job and getattr(self.job, 'description', None):
            return self.job.description
        return self._job_description or ""

    @job_description.setter
    def job_description(self, value):
        self._job_description = value

    @staticmethod
    def find_best_match(text: str, options: list[str]) -> str:
        logger.debug(f"Finding best match for text: '{text}' in options: {options}")
        distances = [
            (option, distance(text.lower(), option.lower())) for option in options
        ]
        best_option = min(distances, key=lambda x: x[1])[0]
        logger.debug(f"Best match found: {best_option}")
        return best_option

    @staticmethod
    def _remove_placeholders(text: str) -> str:
        logger.debug(f"Removing placeholders from text: {text}")
        text = text.replace("PLACEHOLDER", "")
        return text.strip()

    @staticmethod
    def _preprocess_template_string(template: str) -> str:
        logger.debug("Preprocessing template string")
        return textwrap.dedent(template)

    def set_resume(self, resume):
        logger.debug(f"Setting resume: {resume}")
        self.resume = resume

    def set_job(self, job):
        logger.debug(f"Setting job: {job}")
        self.job = job
        self.job_description = getattr(job, 'description', "")
        self.cached_artifacts = {} # Clear tailoring artifacts
        self.job.set_summarize_job_description(
            self.summarize_job_description(self.job.description))

    def set_job_application_profile(self, job_application_profile):
        logger.debug(f"Setting job application profile: {job_application_profile}")
        self.job_application_profile = job_application_profile

    def summarize_job_description(self, text: str) -> str:
        logger.debug(f"Summarizing job description: {text}")
        strings.summarize_prompt_template = self._preprocess_template_string(
            strings.summarize_prompt_template
        )
        prompt = ChatPromptTemplate.from_template(
            strings.summarize_prompt_template)
        chain = prompt | self.llm_cheap | StrOutputParser()
        output = chain.invoke({"text": text})
        logger.debug(f"Summary generated: {output}")
        return output

    def _create_chain(self, template: str):
        logger.debug(f"Creating chain with template: {template}")
        prompt = ChatPromptTemplate.from_template(template)
        return prompt | self.llm_cheap | StrOutputParser()

    def answer_question_textual_wide_range(self, question: str) -> str:
        logger.debug(f"Answering textual question: {question}")
        # Overridable templates
        coverletter_tpl = self.config.get('cover_letter_prompt', strings.coverletter_template)

        chains = {
            "personal_information": self._create_chain(strings.personal_information_template),
            "self_identification": self._create_chain(strings.self_identification_template),
            "legal_authorization": self._create_chain(strings.legal_authorization_template),
            "work_preferences": self._create_chain(strings.work_preferences_template),
            "education_details": self._create_chain(strings.education_details_template),
            "experience_details": self._create_chain(strings.experience_details_template),
            "projects": self._create_chain(strings.projects_template),
            "availability": self._create_chain(strings.availability_template),
            "salary_expectations": self._create_chain(strings.salary_expectations_template),
            "certifications": self._create_chain(strings.certifications_template),
            "languages": self._create_chain(strings.languages_template),
            "interests": self._create_chain(strings.interests_template),
            "cover_letter": self._create_chain(coverletter_tpl),
        }

        # logger.debug(f"Chains initialized for sections: {list(chains.keys())}")

        section_prompt = """You are assisting a bot designed to automatically apply for jobs on AIHawk. The bot receives various questions about job applications and needs to determine the most relevant section of the resume to provide an accurate response.

        For the following question: '{question}', determine which section of the resume is most relevant. 
        Respond with exactly one of the following options:
        - Personal information
        - Self Identification
        - Legal Authorization
        - Work Preferences
        - Education Details
        - Experience Details
        - Projects
        - Availability
        - Salary Expectations
        - Certifications
        - Languages
        - Interests
        - Cover letter

        Here are detailed guidelines to help you choose the correct section:

        1. **Personal Information**:
        - **Purpose**: Contains your basic contact details and online profiles.
        - **Use When**: The question is about how to contact you or requests links to your professional online presence.
        - **Examples**: Email address, phone number, AIHawk profile, GitHub repository, personal website.

        2. **Self Identification**:
        - **Purpose**: Covers personal identifiers and demographic information.
        - **Use When**: The question pertains to your gender, pronouns, veteran status, disability status, or ethnicity.
        - **Examples**: Gender, pronouns, veteran status, disability status, ethnicity.

        3. **Legal Authorization**:
        - **Purpose**: Details your work authorization status and visa requirements.
        - **Use When**: The question asks about your ability to work in specific countries or if you need sponsorship or visas.
        - **Examples**: Work authorization in EU and US, visa requirements, legally allowed to work.

        4. **Work Preferences**:
        - **Purpose**: Specifies your preferences regarding work conditions and job roles.
        - **Use When**: The question is about your preferences for remote work, in-person work, relocation, and willingness to undergo assessments or background checks.
        - **Examples**: Remote work, in-person work, open to relocation, willingness to complete assessments.

        5. **Education Details**:
        - **Purpose**: Contains information about your academic qualifications.
        - **Use When**: The question concerns your degrees, universities attended, GPA, and relevant coursework.
        - **Examples**: Degree, university, GPA, field of study, exams.

        6. **Experience Details**:
        - **Purpose**: Details your professional work history and key responsibilities.
        - **Use When**: The question pertains to your job roles, responsibilities, and achievements in previous positions.
        - **Examples**: Job positions, company names, key responsibilities, skills acquired.

        7. **Projects**:
        - **Purpose**: Highlights specific projects you have worked on.
        - **Use When**: The question asks about particular projects, their descriptions, or links to project repositories.
        - **Examples**: Project names, descriptions, links to project repositories.

        8. **Availability**:
        - **Purpose**: Provides information on your availability for new roles.
        - **Use When**: The question is about how soon you can start a new job or your notice period.
        - **Examples**: Notice period, availability to start.

        9. **Salary Expectations**:
        - **Purpose**: Covers your expected salary range.
        - **Use When**: The question pertains to your salary expectations or compensation requirements.
        - **Examples**: Desired salary range.

        10. **Certifications**:
            - **Purpose**: Lists your professional certifications or licenses.
            - **Use When**: The question involves your certifications or qualifications from recognized organizations.
            - **Examples**: Certification names, issuing bodies, dates of validity.

        11. **Languages**:
            - **Purpose**: Describes the languages you can speak and your proficiency levels.
            - **Use When**: The question asks about your language skills or proficiency in specific languages.
            - **Examples**: Languages spoken, proficiency levels.

        12. **Interests**:
            - **Purpose**: Details your personal or professional interests.
            - **Use When**: The question is about your hobbies, interests, or activities outside of work.
            - **Examples**: Personal hobbies, professional interests.

        13. **Cover Letter**:
            - **Purpose**: Contains your personalized cover letter or statement.
            - **Use When**: The question involves your cover letter or specific written content intended for the job application.
            - **Examples**: Cover letter content, personalized statements.

        14. **Telegram message**:
            - **Purpose**: A short, professional message to a recruiter or hiring manager.
            - **Use When**: The question asks to write a message, reach out to contact, or introduce yourself for a role.
            - **Examples**: Greeting recruiter, message to contact person.

        Provide only the exact name of the section from the list above with no additional text.
        """
        prompt = ChatPromptTemplate.from_template(section_prompt)
        chain = prompt | self.llm_cheap | StrOutputParser()
        output = chain.invoke({"question": question})

        match = re.search(
            r"(Personal information|Self Identification|Legal Authorization|Work Preferences|Education "
            r"Details|Experience Details|Projects|Availability|Salary "
            r"Expectations|Certifications|Languages|Interests|Cover letter|Telegram message)",
            output, re.IGNORECASE)
        if not match:
            raise ValueError(
                "Could not extract section name from the response.")

        section_name = match.group(1).lower().replace(" ", "_")

        if section_name in ["cover_letter", "telegram_message"]:
            # Check cache first for batched artifacts
            if section_name in self.cached_artifacts:
                logger.debug(f"Using cached {section_name} from batched generation")
                return self.cached_artifacts[section_name]
                
            # If not cached, trigger batched generation
            if self.config.get('smart_master_prompt'):
                resume_yaml = getattr(self.resume, 'yaml_str', None)
                if not resume_yaml and hasattr(self, 'job_application_profile'):
                    resume_yaml = getattr(self.job_application_profile, 'yaml_str', None)
                
                if resume_yaml:
                    self.generate_application_artifacts(self.job_description, resume_yaml)
                
                if section_name in self.cached_artifacts:
                    return self.cached_artifacts[section_name]

            if section_name == "telegram_message":
                # Fallback for telegram_message if smart prompt failed
                return "Hello! I'm interested in this position. Please find my CV attached."

            # Legacy fallback for cover_letter
            chain = chains.get(section_name)
            if not self.resume:
                logger.warning("No resume set on GPTAnswerer, returning empty string for section.")
                return ""
            output = chain.invoke({"resume": self.resume, "job_description": self.job_description})
            return output
        resume_section = getattr(self.resume, section_name, None) or getattr(self.job_application_profile, section_name,
                                                                             None)
        if resume_section is None:
            logger.error(
                f"Section '{section_name}' not found in either resume or job_application_profile.")
            raise ValueError(f"Section '{section_name}' not found in either resume or job_application_profile.")
        chain = chains.get(section_name)
        if chain is None:
            logger.error(f"Chain not defined for section '{section_name}'")
            raise ValueError(f"Chain not defined for section '{section_name}'")
        output = chain.invoke(
            {"resume_section": resume_section, "question": question})
        logger.debug(f"Question answered: {output}")
        return output

    def answer_question_numeric(self, question: str, default_experience: str = 3) -> str:
        logger.debug(f"Answering numeric question: {question}")
        func_template = self._preprocess_template_string(
            strings.numeric_question_template)
        prompt = ChatPromptTemplate.from_template(func_template)
        chain = prompt | self.llm_cheap | StrOutputParser()
        output_str = chain.invoke(
            {"resume_educations": self.resume.education_details, "resume_jobs": self.resume.experience_details,
             "resume_projects": self.resume.projects, "question": question})
        logger.debug(f"Raw output for numeric question: {output_str}")
        try:
            output = self.extract_number_from_string(output_str)
            logger.debug(f"Extracted number: {output}")
        except ValueError:
            logger.warning(
                f"Failed to extract number, using default experience: {default_experience}")
            output = default_experience
        return output

    def extract_number_from_string(self, output_str):
        logger.debug(f"Extracting number from string: {output_str}")
        numbers = re.findall(r"\d+", output_str)
        if numbers:
            logger.debug(f"Numbers found: {numbers}")
            return str(numbers[0])
        else:
            logger.error("No numbers found in the string")
            raise ValueError("No numbers found in the string")

    def answer_question_from_options(self, question: str, options: list[str]) -> str:
        logger.debug(f"Answering question from options: {question}")
        func_template = self._preprocess_template_string(
            strings.options_template)
        prompt = ChatPromptTemplate.from_template(func_template)
        chain = prompt | self.llm_cheap | StrOutputParser()
        output_str = chain.invoke(
            {"resume": self.resume, "question": question, "options": options})
        logger.debug(f"Raw output for options question: {output_str}")
        best_option = self.find_best_match(output_str, options)
        logger.debug(f"Best option determined: {best_option}")
        return best_option

    def resume_or_cover(self, phrase: str) -> str:
        logger.debug(
            f"Determining if phrase refers to resume or cover letter: {phrase}")
        prompt_template = """
                Given the following phrase, respond with only 'resume' if the phrase is about a resume, or 'cover' if it's about a cover letter.
                If the phrase contains only one word 'upload', consider it as 'cover'.
                If the phrase contains 'upload resume', consider it as 'resume'.
                Do not provide any additional information or explanations.

                phrase: {phrase}
                """
        prompt = ChatPromptTemplate.from_template(prompt_template)
        chain = prompt | self.llm_cheap | StrOutputParser()
        response = chain.invoke({"phrase": phrase}).lower()
        logger.debug(f"Response for resume_or_cover: {response}")
        if "resume" in response:
            return "resume"
        elif "cover" in response:
            return "cover"
        else:
            return "resume"

    SMART_MASTER_PROMPT_TEMPLATE = """
You are an expert career coach and recruiter. Analyze the provided resume and job description to generate professional application artifacts.

# Candidate Profile (Resume YAML):
{{ resume_yaml }}

# Job Description:
{{ job_description }}

# Output Requirements (JSON):
Generate a JSON object with the following keys:
1. "telegram_message": A very concise, professional message (50-70 words).
   - IMPORTANT: Use the SAME language as the 'Job Description' provided (e.g., if the job description is in Russian, the message MUST be in Russian).
   - Use 2-3 short, distinct paragraphs (use \n for line breaks). NO walls of text.
   - Strictly NO markdown (no **, no _, no `).
   - End with a professional sign-off (e.g., "Best regards, Sultangazy Yergaliyev" or "С уважением, Султангазы Ергалиев").
2. "cover_letter": A concise 3-paragraph tailored cover letter.
   - IMPORTANT: Use the SAME language as the 'Job Description' provided (e.g., if the job description is in Russian, the cover letter MUST be in Russian).
   - Must end with a professional sign-off (e.g., "Sincerely, Sultangazy Yergaliyev" or "С уважением, Султангазы Ергалиев").
3. "resume_sections": An object containing tailored HTML snippets for each section.
   - IMPORTANT: MUST BE IN ENGLISH REGARDLESS OF THE JOB DESCRIPTION LANGUAGE.
   - Keep the HTML structure clean (use <h3>, <ul>, <li>, <p>). Each snippet should be 1-2 paragraphs or a bullet list.
   - "header": Use the candidate's name and contact info. Create a 2-sentence professional summary tailored to the job.
   - "education": Format education details highlighting relevant courses. IMPORTANT: DO NOT include years or dates.
   - "work_experience": Tailor bullet points to emphasize skills requested in the job description.
   - "side_projects": Highlight projects relevant to the tech stack of the job.
   - "achievements": Select and rephrase achievements that show impact related to the role.
   - "certifications": Relevant certifications.
   - "additional_skills": A categorized list of tech and soft skills matching the job.
   - IMPORTANT: DO NOT hallucinate. Only include skills, languages, or technologies that are actually present or reasonably inferred from the 'Candidate Profile'. If a required skill from the JD is missing in the resume, DO NOT add it to the tailored output.
4. "resume_markdown": "A complete, high-quality Markdown version of the tailored resume. Use professional formatting. Include all contact info and experiences. This is for direct PDF conversion. IMPORTANT: MUST BE IN ENGLISH AND DO NOT include years or dates in the Education section. DO NOT add skills that the candidate doesn't have."

Return ONLY valid JSON.
"""

    BATCH_QUESTIONS_PROMPT_TEMPLATE = """
You are an expert at filling job applications. Use the provided resume to answer a batch of questions from a job application form.

# Candidate Profile (Resume YAML):
{{ resume_yaml }}

# Questions to Answer:
{{ questions_json }}

# Instructions:
1. For each question, provide the most accurate answer based on the resume.
2. If not explicitly found, make a professional inference.
3. Numeric questions: provide ONLY the number.
4. Dropdown/Radio questions: Select the EXACT text from the provided options.
5. Textbox questions: Provide a concise, professional response (max 20 words).

# Output Requirements (JSON):
Return a JSON object where keys are question "id" and values are the "answer".
Return ONLY valid JSON.
"""

    def generate_application_artifacts(self, job_description: str, resume_yaml: str) -> dict:
        # Clear cache if the job description has changed
        if self._job_description != job_description:
            self.cached_artifacts = {}
            self.job_description = job_description

        if self.cached_artifacts:
            logger.debug("Returning cached application artifacts")
            return self.cached_artifacts

        logger.info("🤖 AI is analyzing the job and generating your application artifacts (batched call)...")
        config_template = self.config.get('smart_master_prompt', "")
        
        # If it's a boolean True or empty, use the default template
        if config_template is True or (isinstance(config_template, str) and (config_template.lower() == "true" or not config_template)):
            master_template = self.SMART_MASTER_PROMPT_TEMPLATE
        elif isinstance(config_template, str):
            master_template = config_template
        else:
            logger.warning("Invalid smart_master_prompt format. Using default template.")
            master_template = self.SMART_MASTER_PROMPT_TEMPLATE

        if not master_template:
            logger.warning("No master template available. Returning empty artifacts.")
            return {}

        # Render template
        try:
            from jinja2 import Template
            jinja_template = Template(master_template)
            prompt_text = jinja_template.render(
                resume_yaml=resume_yaml or "",
                job_description=job_description or ""
            )
        except Exception as e:
            logger.error(f"Error rendering master prompt template: {e}")
            # Simple fallback replacement if jinja2 fails
            r_yaml = resume_yaml or ""
            j_desc = job_description or ""
            prompt_text = master_template.replace("{{ resume_yaml }}", r_yaml).replace("{{ job_description }}", j_desc)

        try:
            # Reuse the existing chain logic for consistency with logging
            prompt = ChatPromptTemplate.from_template("{content}")
            chain = prompt | self.llm_cheap | StrOutputParser()
            output = chain.invoke({"content": prompt_text})
            
            # Parse JSON
            # Handle potential markdown code blocks in LLM response
            clean_output = output.strip()
            if clean_output.startswith("```json"):
                clean_output = clean_output[7:].rsplit("```", 1)[0].strip()
            elif clean_output.startswith("```"):
                clean_output = clean_output[3:].rsplit("```", 1)[0].strip()
            
            import json
            artifacts = json.loads(clean_output)
            self.cached_artifacts = artifacts
            logger.info("Successfully generated and parsed application artifacts batch.");
            return artifacts
        except Exception as e:
            logger.error(f"Error generating or parsing LLM artifacts JSON: {e}");
            return {}

    def answer_questions_batch(self, questions: List[Dict[str, Any]]) -> Dict[str, str]:
        """
        Answers a batch of questions in a single LLM call.
        'questions' is a list of dicts: {'id': str, 'text': str, 'type': str, 'options': List[str]}
        """
        if not questions:
            return {}

        logger.info(f"🤖 AI is answering a batch of {len(questions)} application questions...")
        resume_yaml = getattr(self.resume, 'yaml_str', "") or getattr(self.job_application_profile, 'yaml_str', "")
        
        from jinja2 import Template
        template = Template(self.BATCH_QUESTIONS_PROMPT_TEMPLATE)
        prompt_text = template.render(
            resume_yaml=resume_yaml,
            questions_json=json.dumps(questions, indent=2)
        )

        try:
            prompt = ChatPromptTemplate.from_template("{content}")
            chain = prompt | self.llm_cheap | StrOutputParser()
            output = chain.invoke({"content": prompt_text})
            
            clean_output = output.strip()
            if clean_output.startswith("```json"):
                clean_output = clean_output[7:].rsplit("```", 1)[0].strip()
            elif clean_output.startswith("```"):
                clean_output = clean_output[3:].rsplit("```", 1)[0].strip()
            
            answers = json.loads(clean_output)
            logger.info(f"Successfully answered {len(answers)} questions in batch.")
            return answers
        except Exception as e:
            logger.error(f"Error in batch question answering: {e}")
            return {}

