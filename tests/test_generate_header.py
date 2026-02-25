import logging
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts.base import BasePromptTemplate  # Ensure correct import based on your langchain version

# Mock classes and data for testing
class MockResume:
    def __init__(self):
        self.personal_information = "John Doe, johndoe@example.com, +123456789"
        self.job_description = "Software Engineer at XYZ Corp"
        self.education_details = "B.Sc. in Computer Science from ABC University"
        # Add other necessary attributes if needed

class MockStrings:
    prompt_header = """
Generate a resume header for the following personal information and job description:
Personal Information: {personal_information}
Job Description: {job_description}
"""

    prompt_education = """
Generate the education section for the following education details and job description:
Education Details: {education_details}
Job Description: {job_description}
"""

class MockLLM:
    def __call__(self, prompt_str: str):
        """
        MockLLM's __call__ method to handle formatted prompt strings.
        It extracts the necessary variables from the prompt and returns a simulated response.
        """
        # Debugging: Print the prompt string
        print(f"MockLLM received prompt:\n{prompt_str}\n")
        
        # Simple parsing to extract relevant information
        personal_information = "N/A"
        job_description = "N/A"
        education_details = "N/A"
        
        for line in prompt_str.split('\n'):
            if line.startswith("Personal Information:"):
                personal_information = line.split("Personal Information:")[1].strip()
            elif line.startswith("Job Description:"):
                job_description = line.split("Job Description:")[1].strip()
            elif line.startswith("Education Details:"):
                education_details = line.split("Education Details:")[1].strip()
        
        # Simulate the language model response based on the prompt
        if "header" in prompt_str.lower():
            return f"Header: {personal_information} - {job_description}"
        elif "education section" in prompt_str.lower():
            return f"Education: {education_details} related to {job_description}"
        else:
            return "Unknown section"

# Function to test generate_header
def test_generate_header():
    logging.basicConfig(level=logging.DEBUG)

    # Mock objects
    resume = MockResume()
    strings = MockStrings()
    llm_cheap = MockLLM()

    # Generate header
    header_prompt_template = strings.prompt_header
    logging.debug(f"Header template: {header_prompt_template}")
    print(f"Header template:\n{header_prompt_template}\n")

    prompt = ChatPromptTemplate.from_template(header_prompt_template)
    logging.debug(f"Prompt: {prompt}")
    print(f"Prompt: {prompt}\n")

    # Format the prompt with input_data
    input_data = {
        "personal_information": resume.personal_information,
        "job_description": resume.job_description
    }
    logging.debug(f"Input data for the chain: {input_data}")
    print(f"Input data for the chain: {input_data}\n")

    try:
        # Explicitly format the prompt
        filled_prompt = prompt.format(**input_data)
        logging.debug(f"Filled prompt:\n{filled_prompt}\n")
        print(f"Filled prompt:\n{filled_prompt}\n")
        
        # Pass the filled prompt to llm_cheap
        llm_output = llm_cheap(filled_prompt)
        logging.debug(f"LLM invocation result: {llm_output}")
        print(f"LLM invocation result: {llm_output}\n")
        
        # Parse the output
        parsed_output = StrOutputParser().parse(llm_output)
        logging.debug(f"Parsed output: {parsed_output}")
        print(f"Parsed output: {parsed_output}\n")
    except Exception as e:
        logging.error(f"Error during chain invocation: {e}")
        print(f"Error during chain invocation: {e}\n")
        return None

    logging.debug("Header section generation completed")
    print("Header section generation completed\n")
    return parsed_output

# Function to test generate_education_section (Duplicated from generate_header)
def test_generate_education_section():
    logging.basicConfig(level=logging.DEBUG)

    # Mock objects
    resume = MockResume()
    strings = MockStrings()
    llm_cheap = MockLLM()

    # Generate education section
    education_prompt_template = strings.prompt_education
    logging.debug(f"Education template: {education_prompt_template}")
    print(f"Education template:\n{education_prompt_template}\n")

    prompt = ChatPromptTemplate.from_template(education_prompt_template)
    logging.debug(f"Prompt: {prompt}")
    print(f"Prompt: {prompt}\n")

    # Format the prompt with input_data
    input_data = {
        "education_details": resume.education_details,
        "job_description": resume.job_description
    }
    logging.debug(f"Input data for the chain: {input_data}")
    print(f"Input data for the chain: {input_data}\n")

    try:
        # Explicitly format the prompt
        filled_prompt = prompt.format(**input_data)
        logging.debug(f"Filled prompt:\n{filled_prompt}\n")
        print(f"Filled prompt:\n{filled_prompt}\n")
        
        # Pass the filled prompt to llm_cheap
        llm_output = llm_cheap(filled_prompt)
        logging.debug(f"LLM invocation result: {llm_output}")
        print(f"LLM invocation result: {llm_output}\n")
        
        # Parse the output
        parsed_output = StrOutputParser().parse(llm_output)
        logging.debug(f"Parsed output: {parsed_output}")
        print(f"Parsed output: {parsed_output}\n")
    except Exception as e:
        logging.error(f"Error during chain invocation: {e}")
        print(f"Error during chain invocation: {e}\n")
        return None

    logging.debug("Education section generation completed")
    print("Education section generation completed\n")
    return parsed_output

if __name__ == "__main__":
    print("----- Testing generate_header -----")
    header_result = test_generate_header()
    print(f"Generated Header: {header_result}\n")

    print("----- Testing generate_education_section -----")
    education_result = test_generate_education_section()
    print(f"Generated Education Section: {education_result}\n")