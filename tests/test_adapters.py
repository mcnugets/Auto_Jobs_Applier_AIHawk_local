import pytest
import sys
from unittest.mock import Mock, patch, mock_open, MagicMock
from pathlib import Path

# Mock external dependencies for tests to avoid import errors
sys.modules['telethon'] = MagicMock()
sys.modules['telethon.errors'] = MagicMock()
sys.modules['telethon.tl.types'] = MagicMock()
sys.modules['google.generativeai'] = MagicMock()
sys.modules['pydantic_ai'] = MagicMock()

from src.adapters.linkedin_adapter import LinkedInAdapter
from src.adapters.telegram_adapter import TelegramAdapter
from src.adapters.career_website_adapter import CareerWebsiteAdapter
from src.job_application_profile import JobApplicationProfile

@pytest.fixture
def mock_profile():
    profile = Mock(spec=JobApplicationProfile)
    return profile

@pytest.fixture
def mock_parameters():
    return {
        "uploads": {"plainTextResume": "dummy_path"},
        "llm_model": "gpt-4",
        "llm_model_type": "openai",
        "collectMode": False
    }

def test_career_website_adapter(mock_profile, mock_parameters):
    adapter = CareerWebsiteAdapter(mock_profile, mock_parameters, "dummy_key")
    assert adapter.login() is False
    assert adapter.search_jobs() == []
    assert adapter.apply_to_job({}) is False

@patch("src.adapters.telegram_adapter.validate_telegram_config")
@patch("src.adapters.telegram_adapter.JobDatabase")
@patch("src.adapters.telegram_adapter.asyncio")
@patch("src.adapters.telegram_adapter.run_monitor")
@patch("src.adapters.telegram_adapter.run_applier")
@patch("src.adapters.telegram_adapter.GPTAnswerer")
@patch("src.adapters.telegram_adapter.Resume")
@patch("src.adapters.telegram_adapter.StyleManager")
@patch("src.adapters.telegram_adapter.FacadeManager")
@patch("src.adapters.telegram_adapter.ResumeGenerator")
def test_telegram_adapter_run_apply_mode(mock_res_gen, mock_facade, mock_style, mock_resume, mock_gpt, mock_run_applier, mock_run_monitor, mock_asyncio, mock_JobDatabase, mock_validate_telegram_config, mock_profile, mock_parameters):
    # Ensure profile string is mocked for Resume initialization
    mock_profile.yaml_str = "dummy_yaml"
    
    adapter = TelegramAdapter(mock_profile, mock_parameters, "dummy_key")
    adapter.run()
    
    mock_validate_telegram_config.assert_called_once()
    mock_JobDatabase.assert_called_once()
    assert mock_asyncio.run.call_count == 2 # monitor and applier runs

@patch("src.adapters.telegram_adapter.validate_telegram_config")
@patch("src.adapters.telegram_adapter.JobDatabase")
@patch("src.adapters.telegram_adapter.asyncio")
@patch("src.adapters.telegram_adapter.run_monitor")
@patch("src.adapters.telegram_adapter.run_applier")
def test_telegram_adapter_run_collect_mode(mock_run_applier, mock_run_monitor, mock_asyncio, mock_JobDatabase, mock_validate_telegram_config, mock_profile, mock_parameters):
    mock_params = dict(mock_parameters)
    mock_params['collectMode'] = True
    adapter = TelegramAdapter(mock_profile, mock_params, "dummy_key")
    adapter.run()
    
    mock_validate_telegram_config.assert_called_once()
    mock_JobDatabase.assert_called_once()
    assert mock_asyncio.run.call_count == 1 # only monitor runs
    mock_run_applier.assert_not_called()


@patch("src.adapters.linkedin_adapter.init_browser")
@patch("src.adapters.linkedin_adapter.AIHawkBotFacade")
@patch("src.adapters.linkedin_adapter.FacadeManager")
@patch("src.adapters.linkedin_adapter.AIHawkAuthenticator")
@patch("src.adapters.linkedin_adapter.AIHawkJobManager")
@patch("src.adapters.linkedin_adapter.GPTAnswerer")
@patch("src.adapters.linkedin_adapter.open", new_callable=mock_open, read_data="resume content")
@patch("src.adapters.linkedin_adapter.Resume")
def test_linkedin_adapter_run_apply(mock_resume, mock_open, mock_gpt, mock_job_manager, mock_auth, mock_facade_manager, mock_bot_facade, mock_init_browser, mock_profile, mock_parameters):
    adapter = LinkedInAdapter(mock_profile, mock_parameters, "dummy_key")
    adapter.run()
    
    # Assert init routines were called
    mock_init_browser.assert_called_once()
    mock_facade_manager.return_value.choose_style.assert_called_once()
    
    # Verify bot initialization
    mock_bot_facade.return_value.start_login.assert_called_once()
    mock_bot_facade.return_value.start_apply.assert_called_once()
    mock_bot_facade.return_value.start_collect_data.assert_not_called()

@patch("src.adapters.linkedin_adapter.init_browser")
@patch("src.adapters.linkedin_adapter.AIHawkBotFacade")
@patch("src.adapters.linkedin_adapter.FacadeManager")
@patch("src.adapters.linkedin_adapter.AIHawkAuthenticator")
@patch("src.adapters.linkedin_adapter.AIHawkJobManager")
@patch("src.adapters.linkedin_adapter.GPTAnswerer")
@patch("src.adapters.linkedin_adapter.open", new_callable=mock_open, read_data="resume content")
@patch("src.adapters.linkedin_adapter.Resume")
def test_linkedin_adapter_run_collect(mock_resume, mock_open, mock_gpt, mock_job_manager, mock_auth, mock_facade_manager, mock_bot_facade, mock_init_browser, mock_profile, mock_parameters):
    mock_params = dict(mock_parameters)
    mock_params['collectMode'] = True
    adapter = LinkedInAdapter(mock_profile, mock_params, "dummy_key")
    adapter.run()
    
    # Verify bot initialization calls collect mode
    mock_bot_facade.return_value.start_login.assert_called_once()
    mock_bot_facade.return_value.start_collect_data.assert_called_once()
    mock_bot_facade.return_value.start_apply.assert_not_called()
