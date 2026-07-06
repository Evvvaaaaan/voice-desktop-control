import pytest
import yaml
import os

@pytest.fixture
def default_config_dict():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


@pytest.fixture(autouse=True)
def _reset_last_capture_rect():
    """actions.screen caches the rect of the most recent screenshot at
    module scope (see last_capture_rect) so a click can be mapped against
    exactly what the model was shown, even across separate dispatch() calls
    in production. That persistence would otherwise leak between tests —
    whichever test happens to run first and take a screenshot would set the
    rect for every later test's click/move dispatch, regardless of what
    active_screen_rect() they mock."""
    import actions.screen as screen
    screen._last_capture_rect = None
    yield
    screen._last_capture_rect = None
