import pytest
from unittest import mock
from pathlib import Path
from src.aihawk_job_manager import AIHawkJobManager
from src.job import Job

@pytest.fixture
def mock_job():
    return Job(
        title="Software Engineer",
        company="Tech Corp",
        location="London",
        link="https://www.linkedin.com/jobs/view/123",
        apply_method="Easy Apply"
    )

def test_apply_loop_integration(mocker, tmp_path):
    """
    Test the high-level integration between JobManager and EasyApplier.
    This ensures that when JobManager finds a job, it correctly triggers the apply flow.
    """
    # 1. Setup mocks
    mock_driver = mocker.Mock()
    job_manager = AIHawkJobManager(mock_driver)
    
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    
    params = {
        'remote': True,
        'experienceLevel': {'entry': True},
        'jobTypes': {'full-time': True},
        'date': {'all time': True},
        'positions': ['Engineer'],
        'locations': ['London'],
        'location_blacklist': [],
        'distance': 50,
        'company_blacklist': [],
        'title_blacklist': [],
        'apply_once_at_company': False,
        'uploads': {'resume': '/path/to/resume'},
        'outputFileDirectory': str(output_dir),
        'llm_model_type': 'openai',
        'llm_model': 'gpt-4o'
    }
    config_path = tmp_path / "config.yaml"
    
    # 2. Set parameters
    job_manager.set_parameters(params, config_path)
    
    # 3. Mock dependencies
    mocker.patch.object(job_manager, 'get_jobs_from_page')
    mocker.patch.object(job_manager, 'extract_job_information_from_tile')
    mocker.patch.object(job_manager, 'write_to_file')
    
    # Mock EasyApplier
    mock_applier = mocker.Mock()
    mocker.patch('src.aihawk_job_manager.AIHawkEasyApplier', return_value=mock_applier)
    
    # Simulate finding one job
    mock_job_element = mocker.Mock()
    job_manager.get_jobs_from_page.return_value = [mock_job_element]
    job_manager.extract_job_information_from_tile.return_value = (
        "Software Engineer", "Tech Corp", "London", "https://link.com", "Easy Apply"
    )
    
    # 4. Run application logic
    # We need to manually initialize the easy_applier_component as start_applying would do
    job_manager.start_applying = mocker.Mock(side_effect=lambda: setattr(job_manager, 'easy_applier_component', mock_applier))
    job_manager.start_applying()
    
    job_manager.apply_jobs()
    
    # 5. Assertions
    # Verify that EasyApplier.job_apply was called with a Job object
    mock_applier.job_apply.assert_called_once()
    called_job = mock_applier.job_apply.call_args[0][0]
    assert isinstance(called_job, Job)
    assert called_job.title == "Software Engineer"
    assert called_job.company == "Tech Corp"
    
    # Verify that it attempted to write to success file
    job_manager.write_to_file.assert_called_with(mock.ANY, "success")
