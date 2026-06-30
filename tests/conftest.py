import pytest
import yaml
import os

@pytest.fixture
def default_config_dict():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)
