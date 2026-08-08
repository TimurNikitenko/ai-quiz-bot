from core.config import get_settings, Settings
from core.constants import DEFAULT_CHEAP_MODEL


def test_core_settings_defaults():
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.llm_cheap_model is not None
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_core_settings_channel_routing():
    settings = Settings(
        channel_id="-1001111111111",
        channel_id_tech="-1002222222222",
        channel_id_simple="-1003333333333",
    )
    assert settings.get_channel_id_for_type("tech") == "-1002222222222"
    assert settings.get_channel_id_for_type("simple") == "-1003333333333"

    settings_fallback = Settings(
        channel_id="-1001111111111",
        channel_id_tech=None,
        channel_id_simple=None,
    )
    assert settings_fallback.get_channel_id_for_type("tech") == "-1001111111111"
    assert settings_fallback.get_channel_id_for_type("simple") == "-1001111111111"
