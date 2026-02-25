from pathlib import Path
from loguru import logger
from src.adapters.base_adapter import BaseJobAdapter

try:
    from src.llm.llm_manager import GPTAnswerer
    from lib_resume_builder_AIHawk import Resume, StyleManager, FacadeManager, ResumeGenerator
    from src.utils import get_filenames_from_directory
except ImportError:
    GPTAnswerer = None
    Resume = None
    StyleManager = None
    FacadeManager = None
    ResumeGenerator = None

class CareerWebsiteAdapter(BaseJobAdapter):
    def login(self) -> bool:
        logger.warning("Career Website Adapter Login - Not Implemented (Surfing mode)")
        return False

    def search_jobs(self, keywords=None) -> list:
        logger.warning("Career Website Adapter Search - Not Implemented (Surfing mode)")
        return []

    def apply_to_job(self, job_data) -> bool:
        """Surfing logic for external career websites."""
        if not all([GPTAnswerer, Resume]):
            logger.error("Missing AIHawk components for Career Website surfing.")
            return False
            
        # 1. Analysis & Batch Generation
        # (Implementation will follow in the next task phase)
        return False

    def run(self) -> None:
        logger.info("Initializing Career Website Surfing mode...")
        
        # Consistent initialization pattern
        gpt_manager = GPTAnswerer(self.parameters, self.llm_api_key)
        
        try:
            resume_object = Resume(self.profile.yaml_str)
            style_manager = StyleManager()
            resume_generator = ResumeGenerator()
            output_folder = Path(self.parameters.get('outputFileDirectory', "data_folder/output"))

            facade_manager = FacadeManager(
                self.llm_api_key, 
                style_manager, 
                resume_generator, 
                resume_object, 
                output_folder / "resume.log"
            )
            # Set style non-interactively
            selected_style = self.parameters.get("resume_style", "Modern Blue")
            facade_manager.selected_style = selected_style
            logger.info(f"Resume style set to: {selected_style}")
        except Exception as e:
            logger.warning(f"Career Website Adapter dynamic init failed: {e}")
            
        logger.warning("Career Website Applier is under construction. Please use 'telegram' or 'linkedin' mode for now.")
