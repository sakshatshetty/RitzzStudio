import pytest

from modules.project.config import ProductionConfig


def test_production_config_derives_minimum_words_from_duration():
    config = ProductionConfig(target_duration_seconds=360, minimum_duration_seconds=300)
    assert config.minimum_word_count == 700


def test_production_config_rejects_invalid_duration_order():
    with pytest.raises(ValueError, match="minimum_duration_seconds"):
        ProductionConfig(target_duration_seconds=300, minimum_duration_seconds=360)