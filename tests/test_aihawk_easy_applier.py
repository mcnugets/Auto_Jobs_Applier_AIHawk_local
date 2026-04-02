import pytest
from unittest import mock
from pathlib import Path
from src.aihawk_easy_applier import AIHawkEasyApplier


@pytest.fixture
def mock_driver():
    """Fixture to mock Selenium WebDriver."""
    driver = mock.Mock()
    driver.find_elements.return_value = []
    driver.page_source = "<html></html>"
    return driver


@pytest.fixture
def mock_gpt_answerer():
    """Fixture to mock GPT Answerer."""
    return mock.Mock()


@pytest.fixture
def mock_resume_generator_manager():
    """Fixture to mock Resume Generator Manager."""
    return mock.Mock()


@pytest.fixture
def easy_applier(mock_driver, mock_gpt_answerer, mock_resume_generator_manager):
    """Fixture to initialize AIHawkEasyApplier with mocks."""
    return AIHawkEasyApplier(
        driver=mock_driver,
        resume_dir="/path/to/resume",
        set_old_answers=[('Question 1', 'Answer 1', 'Type 1')],
        gpt_answerer=mock_gpt_answerer,
        resume_generator_manager=mock_resume_generator_manager,
        parameters={},
        config_yaml_path=Path("/path/to/config.yaml")
    )


def test_initialization(mocker, easy_applier):
    """Test that AIHawkEasyApplier is initialized correctly."""
    # Mock os.path.exists to return True
    mocker.patch('os.path.exists', return_value=True)

    mock_drv = mocker.Mock()
    mock_drv.find_elements.return_value = []
    mock_drv.page_source = "<html></html>"

    easy_applier = AIHawkEasyApplier(
        driver=mock_drv,
        resume_dir="/path/to/resume",
        set_old_answers=[('Question 1', 'Answer 1', 'Type 1')],
        gpt_answerer=mocker.Mock(),
        resume_generator_manager=mocker.Mock(),
        parameters={},
        config_yaml_path=Path("/path/to/config.yaml")
    )

    assert easy_applier.resume_path == "/path/to/resume"
    assert len(easy_applier.set_old_answers) == 1
    assert easy_applier.gpt_answerer is not None
    assert easy_applier.resume_generator_manager is not None


def test_apply_to_job_success(mocker, easy_applier):
    """Test successfully applying to a job."""
    mock_job = mock.Mock()

    # Mock job_apply so we don't actually try to apply
    mocker.patch.object(easy_applier, 'job_apply')

    easy_applier.apply_to_job(mock_job)
    easy_applier.job_apply.assert_called_once_with(mock_job)


def test_apply_to_job_failure(mocker, easy_applier):
    """Test failure while applying to a job."""
    mock_job = mock.Mock()
    mocker.patch.object(easy_applier, 'job_apply',
                        side_effect=Exception("Test error"))

    with pytest.raises(Exception, match="Test error"):
        easy_applier.apply_to_job(mock_job)

    easy_applier.job_apply.assert_called_once_with(mock_job)


def test_check_for_premium_redirect_no_redirect(mocker, easy_applier):
    """Test that check_for_premium_redirect works when there's no redirect."""
    mock_job = mock.Mock()
    easy_applier.driver.current_url = "https://www.linkedin.com/jobs/view/1234"

    easy_applier.check_for_premium_redirect(mock_job)
    easy_applier.driver.get.assert_not_called()


def test_check_for_premium_redirect_with_redirect(mocker, easy_applier):
    """Test that check_for_premium_redirect handles AIHawk Premium redirects."""
    mock_job = mock.Mock()
    easy_applier.driver.current_url = "https://www.linkedin.com/premium"
    mock_job.link = "https://www.linkedin.com/jobs/view/1234"

    with pytest.raises(Exception, match="Redirected to AIHawk Premium page and failed to return"):
        easy_applier.check_for_premium_redirect(mock_job)

    # Verify that it attempted to return to the job page 3 times
    assert easy_applier.driver.get.call_count == 3


def test_job_apply_calls_fill_application_form(mocker, easy_applier):
    """Test that job_apply calls _fill_application_form."""
    mock_job = mock.Mock()
    mock_job.link = "http://test.com"
    mocker.patch.object(easy_applier.driver, 'get')
    mocker.patch.object(easy_applier, 'check_for_premium_redirect')
    mocker.patch.object(easy_applier, '_find_easy_apply_button')
    mocker.patch.object(easy_applier, '_get_job_description', return_value="Job Description")
    mocker.patch.object(easy_applier, '_get_job_recruiter', return_value="Recruiter Link")
    mocker.patch.object(easy_applier, '_fill_application_form')
    
    # Mocking external ActionChains to avoid selenium errors during test
    mocker.patch('selenium.webdriver.ActionChains.perform')
    mocker.patch('selenium.webdriver.ActionChains.move_to_element', return_value=mocker.Mock())
    mocker.patch('selenium.webdriver.ActionChains.click', return_value=mocker.Mock())

    easy_applier.job_apply(mock_job)
    
    easy_applier._fill_application_form.assert_called_once_with(mock_job)


def test_fill_application_form_loop(mocker, easy_applier):
    """Test that _fill_application_form iterates through pages until submitted."""
    mock_job = mock.Mock()
    mocker.patch.object(easy_applier, 'fill_up')
    # Mock _next_or_submit to return False twice then True (simulating 3 pages)
    mocker.patch.object(easy_applier, '_next_or_submit', side_effect=[False, False, True])
    mocker.patch('time.sleep') # Skip sleep during tests

    easy_applier._fill_application_form(mock_job)
    
    assert easy_applier.fill_up.call_count == 3
    assert easy_applier._next_or_submit.call_count == 3
