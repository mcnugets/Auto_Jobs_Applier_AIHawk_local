
import logging
from unittest.mock import MagicMock
import pytest
from src.llm.llm_manager import GeminiModel

def test_gemini_rotation_mock():
    # Setup mock API keys
    api_keys = "key1,key2"
    model_name = "gemini-pro"
    
    # Create GeminiModel instance
    # We mock _init_model to avoid real API calls
    GeminiModel._init_model = MagicMock()
    gemini = GeminiModel(api_keys, model_name)
    
    # Verify initialization
    assert len(gemini.api_keys) == 2
    assert gemini.current_key_index == 0
    
    # Mock the internal model's invoke to raise a 429 on the first call
    mock_response = MagicMock()
    mock_response.content = "Success with key 2"
    
    gemini.model = MagicMock()
    # First call raises 429, second call succeeds
    gemini.model.invoke.side_effect = [Exception("ResourceExhausted: 429 quota exceeded"), mock_response]
    
    # Execute invoke
    result = gemini.invoke("test prompt")
    
    # Verify rotation happened
    assert gemini.current_key_index == 1
    assert result.content == "Success with key 2"
    assert gemini.model.invoke.call_count == 2
    print("\n✅ Rotation test passed: Key rotated on 429 error.")

if __name__ == "__main__":
    test_gemini_rotation_mock()
