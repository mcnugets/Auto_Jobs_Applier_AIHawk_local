import pytest
from pathlib import Path
import yaml
import os
from main import ConfigValidator, ConfigError

@pytest.fixture
def temp_config_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    return config_path

def test_config_validation_full_valid(temp_config_file):
    valid_config = {
        'remote': True,
        'experienceLevel': {'entry': True},
        'jobTypes': {'full-time': True},
        'date': {'24 hours': True},
        'positions': ['Software Engineer'],
        'locations': ['London'],
        'location_blacklist': [],
        'distance': 50,
        'company_blacklist': [],
        'title_blacklist': [],
        'llm_model_type': 'openai',
        'llm_model': 'gpt-4o',
        'headless': True
    }
    with open(temp_config_file, 'w') as f:
        yaml.dump(valid_config, f)
    
    validated = ConfigValidator.validate_config(temp_config_file)
    assert validated['remote'] is True
    assert validated['distance'] == 50
    assert validated['llm_model'] == 'gpt-4o'

def test_config_validation_missing_optional_keys(temp_config_file):
    # Minimal config with only strictly required keys
    minimal_config = {
        'llm_model_type': 'openai',
        'llm_model': 'gpt-4o',
        'positions': ['Software Engineer'],
        'locations': ['London']
    }
    with open(temp_config_file, 'w') as f:
        yaml.dump(minimal_config, f)
    
    validated = ConfigValidator.validate_config(temp_config_file)
    # Check if defaults are applied correctly for OPTIONAL keys
    assert validated['remote'] is False
    assert validated['headless'] is False
    assert validated['distance'] == 100
    assert validated['company_blacklist'] == []

def test_config_validation_none_values(temp_config_file):
    # Config where optional keys are null, but required ones are present
    none_config = {
        'remote': None,
        'positions': ['Engineer'],
        'locations': ['Global'],
        'experienceLevel': None,
        'llm_model_type': 'openai',
        'llm_model': 'gpt-4o'
    }
    with open(temp_config_file, 'w') as f:
        yaml.dump(none_config, f)
    
    validated = ConfigValidator.validate_config(temp_config_file)
    assert validated['remote'] is False
    assert validated['positions'] == ['Engineer']
    assert isinstance(validated['experienceLevel'], dict)

def test_config_validation_llm_defaults(temp_config_file):
    # Missing LLM keys, but having required search criteria
    config = {
        'positions': ['Tester'],
        'locations': ['Spain']
    }
    with open(temp_config_file, 'w') as f:
        yaml.dump(config, f)
    
    validated = ConfigValidator.validate_config(temp_config_file)
    assert validated['llm_model_type'] == 'openai'
    assert validated['llm_model'] == 'gpt-4o-mini'

def test_config_validation_invalid_type(temp_config_file):
    invalid_config = {
        'positions': ['Dev'],
        'locations': ['UK'],
        'distance': "very far" # Should be int
    }
    with open(temp_config_file, 'w') as f:
        yaml.dump(invalid_config, f)
    
    with pytest.raises(ConfigError, match="Invalid type for key 'distance'"):
        ConfigValidator.validate_config(temp_config_file)

def test_config_validation_missing_search_criteria(temp_config_file):
    # Missing required positions
    invalid_config = {
        'locations': ['UK']
    }
    with open(temp_config_file, 'w') as f:
        yaml.dump(invalid_config, f)
    
    with pytest.raises(ConfigError, match="Missing or empty required key 'positions'"):
        ConfigValidator.validate_config(temp_config_file)
