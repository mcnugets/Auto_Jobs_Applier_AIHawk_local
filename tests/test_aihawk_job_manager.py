from src.job import Job
from unittest import mock
from pathlib import Path
import os
import pytest
from src.aihawk_job_manager import AIHawkJobManager
from selenium.common.exceptions import NoSuchElementException
from loguru import logger


@pytest.fixture
def job_manager(mocker):
    """Fixture to create a AIHawkJobManager instance with mocked driver."""
    mock_driver = mocker.Mock()
    return AIHawkJobManager(mock_driver)


def test_initialization(job_manager):
    """Test AIHawkJobManager initialization."""
    assert job_manager.driver is not None
    assert job_manager.set_old_answers == set()
    assert job_manager.easy_applier_component is None


def test_set_parameters(mocker, job_manager):
    """Test setting parameters for the AIHawkJobManager."""
    # Mocking os.path.exists to return True for the resume path
    mocker.patch('pathlib.Path.exists', return_value=True)

    params = {
        'company_blacklist': ['Company A', 'Company B'],
        'title_blacklist': ['Intern', 'Junior'],
        'positions': ['Software Engineer', 'Data Scientist'],
        'locations': ['New York', 'San Francisco'],
        'apply_once_at_company': True,
        'uploads': {'resume': '/path/to/resume'},  # Resume path provided here
        'outputFileDirectory': '/path/to/output',
        'job_applicants_threshold': {
            'min_applicants': 5,
            'max_applicants': 50
        },
        'remote': False,
        'distance': 50,
        'date': {'all time': True}
    }

    job_manager.set_parameters(params, Path("/path/to/config.yaml"))

    # Normalize paths to handle platform differences (e.g., Windows vs Unix-like systems)
    assert str(job_manager.resume_path) == os.path.normcase(os.path.normpath('/path/to/resume'))
    assert str(job_manager.output_file_directory) == os.path.normcase(os.path.normpath(
        '/path/to/output'))


def next_job_page(self, position, location, job_page):
    logger.debug(f"Navigating to next job page: {position} in {location}, page {job_page}")
    self.driver.get(
        f"https://www.linkedin.com/jobs/search/{self.base_search_url}&keywords={position}&location={location}&start={job_page * 25}")


def test_get_jobs_from_page_no_jobs(mocker, job_manager):
    """Test get_jobs_from_page when no jobs are found."""
    mocker.patch.object(job_manager, '_find_and_scroll_job_list_container')
    mock_container = mocker.Mock()
    mock_container.find_elements.return_value = []
    job_manager._find_and_scroll_job_list_container.return_value = mock_container
    
    # Also mock fallback driver.find_elements
    job_manager.driver.find_elements.return_value = []

    jobs = job_manager.get_jobs_from_page()
    assert jobs == []


def test_get_jobs_from_page_with_jobs(mocker, job_manager):
    """Test get_jobs_from_page when job elements are found."""
    mock_container = mocker.Mock()
    mock_job = mocker.Mock()
    # Ensure find_elements returns a list so len() works
    mock_container.find_elements.return_value = [mock_job]
    
    mocker.patch.object(job_manager, '_find_and_scroll_job_list_container', return_value=mock_container)

    jobs = job_manager.get_jobs_from_page()
    assert len(jobs) == 1
    assert jobs[0] == mock_job


def test_apply_jobs_with_no_jobs(mocker, job_manager):
    """Test apply_jobs when no jobs are found."""
    mocker.patch.object(job_manager, 'get_jobs_from_page', return_value=[])

    # Call apply_jobs and ensure no exceptions are raised
    job_manager.apply_jobs()

    # Ensure it attempted to find jobs
    job_manager.get_jobs_from_page.assert_called_once()


def test_apply_jobs_with_jobs(mocker, job_manager):
    """Test apply_jobs when jobs are present."""
    mock_job_element = mocker.Mock()
    mocker.patch.object(job_manager, 'get_jobs_from_page', return_value=[mock_job_element, mock_job_element])

    # Mock the extract_job_information_from_tile method to return sample job info
    # (title, company, location, link, apply_method, applicants)
    mocker.patch.object(job_manager, 'extract_job_information_from_tile', return_value=(
        "Title", "Company", "Location", "https://link.com", "Easy Apply", 10))

    # Initialize threshold attributes
    job_manager.min_applicants = 0
    job_manager.max_applicants = 100

    # Mock other methods
    mocker.patch.object(job_manager, 'is_previously_failed_to_apply', return_value=False)
    mocker.patch.object(job_manager, 'is_blacklisted', return_value=False)
    mocker.patch.object(job_manager, 'is_already_applied_to_job', return_value=False)
    mocker.patch.object(job_manager, 'is_already_applied_to_company', return_value=False)

    # Mock the AIHawkEasyApplier component
    job_manager.easy_applier_component = mocker.Mock()

    # Mock the output_file_directory as a valid Path object
    job_manager.output_file_directory = Path("/mocked/path/to/output")

    # Mock Path.exists() and open()
    mocker.patch.object(Path, 'exists', return_value=True)
    mock_open = mocker.mock_open(read_data='[]')
    mocker.patch('builtins.open', mock_open)
    mocker.patch('json.load', return_value=[])
    mocker.patch('json.dump')

    # Run the apply_jobs method
    job_manager.apply_jobs()

    # Assertions
    assert job_manager.get_jobs_from_page.call_count == 1
    assert job_manager.extract_job_information_from_tile.call_count == 2
    assert job_manager.easy_applier_component.job_apply.call_count == 2
