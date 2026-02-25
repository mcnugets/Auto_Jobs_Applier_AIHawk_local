from abc import ABC, abstractmethod
from typing import List, Any
from src.job_application_profile import JobApplicationProfile

class BaseJobAdapter(ABC):
    def __init__(self, profile: JobApplicationProfile, parameters: dict, llm_api_key: str):
        self.profile = profile
        self.parameters = parameters
        self.llm_api_key = llm_api_key

    @abstractmethod
    def login(self) -> bool:
        """Log into the target platform (LinkedIn, Telegram, etc.)"""
        pass

    @abstractmethod
    def search_jobs(self, keywords: List[str] = None) -> List[Any]:
        """Return a list of jobs found on the platform."""
        pass

    @abstractmethod
    def apply_to_job(self, job_data: Any) -> bool:
        """Execute the logic to apply for a single job."""
        pass
    
    @abstractmethod
    def run(self) -> None:
        """Main execution loop for this adapter."""
        pass
