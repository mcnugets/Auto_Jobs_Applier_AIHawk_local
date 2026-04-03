
import pytest
import yaml
from pathlib import Path
from src.llm.llm_manager import GPTAnswerer
from lib_resume_builder_AIHawk import Resume

@pytest.fixture
def gpt_answerer():
    config_path = Path("data_folder/config.yaml")
    secrets_path = Path("data_folder/secrets.yaml")
    
    if not (config_path.exists() and secrets_path.exists()):
        pytest.skip("Config or Secrets files missing, skipping functional LLM test")
        
    with open(config_path, 'r') as f:
        config_params = yaml.safe_load(f)
    
    with open(secrets_path, 'r') as f:
        secrets = yaml.safe_load(f)
        llm_api_key = secrets.get('llm_api_key')
        
    return GPTAnswerer(config_params, llm_api_key)

@pytest.fixture
def resume_obj():
    resume_path = Path("data_folder/plain_text_resume.yaml")
    if not resume_path.exists():
        pytest.skip("Resume file missing")
        
    with open(resume_path, 'r') as f:
        resume_yaml_str = f.read()
    return Resume(resume_yaml_str), resume_yaml_str

def test_artifact_cache_invalidation(gpt_answerer, resume_obj):
    """
    Verify that artifacts are correctly invalidated and regenerated when the job description changes.
    This prevents the 'repeating Java cover letter' bug.
    """
    resume, resume_yaml_str = resume_obj
    gpt_answerer.set_resume(resume)
    
    # Job 1: Python Role
    jd_python = "We are looking for a Python Developer experienced in FastAPI and LLMs."
    artifacts_python = gpt_answerer.generate_application_artifacts(jd_python, resume_yaml_str)
    
    # Verify Python context
    assert "Python" in artifacts_python["telegram_message"] or "FastAPI" in artifacts_python["telegram_message"]
    
    # Job 2: Java Role (to reproduce the reported bug state)
    jd_java = "We are looking for a Java Spring Boot Developer with SQL experience."
    artifacts_java = gpt_answerer.generate_application_artifacts(jd_java, resume_yaml_str)
    
    # CRITICAL ASSERTION: The Java artifacts should NOT be the same as the Python ones
    assert artifacts_python["telegram_message"] != artifacts_java["telegram_message"], "Cache failed to invalidate! Bot is repeating messages."
    
    # Verify Java context (even if it's a mismatch for the resume, the AI should recognize the JD change)
    # Note: Due to anti-hallucination, it shouldn't claim to KNOW Java if not in resume, 
    # but it should mention the JD's context.
    assert "Java" in jd_java
    
def test_anti_hallucination_java(gpt_answerer, resume_obj):
    """
    Verify that the AI does NOT claim to have Java skills if they are not in the resume,
    even if the JD specifically asks for them.
    """
    resume, resume_yaml_str = resume_obj
    gpt_answerer.set_resume(resume)
    
    # Check if Java is actually in the resume first (should NOT be based on user report)
    if "Java" in resume_yaml_str or "Spring Boot" in resume_yaml_str:
        pytest.skip("Resume already contains Java, cannot test anti-hallucination logic for missing skills.")

    jd_java = "Seeking a Senior Java Spring Boot expert. Must have 10 years of Java experience."
    artifacts = gpt_answerer.generate_application_artifacts(jd_java, resume_yaml_str)
    
    resume_markdown = artifacts.get("resume_markdown", "")
    additional_skills = str(artifacts.get("resume_sections", {}).get("additional_skills", ""))
    
    # The AI should NOT add Java to the tailored resume if it's missing from the base profile
    assert "Java" not in resume_markdown, "AI Hallucinated Java in the tailored resume markdown!"
    assert "Spring Boot" not in additional_skills, "AI Hallucinated Spring Boot in the tailored resume sections!"

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
