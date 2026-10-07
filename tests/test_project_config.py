import pytest

from modules.project.config import ProductionConfig


def test_production_config_derives_minimum_words_from_duration():
    config = ProductionConfig(target_duration_seconds=360, minimum_duration_seconds=300)
    assert config.minimum_word_count == 700


def test_production_config_rejects_invalid_duration_order():
    with pytest.raises(ValueError, match="minimum_duration_seconds"):
        ProductionConfig(target_duration_seconds=300, minimum_duration_seconds=360)


def test_production_config_exposes_validatable_hook_quality_weights():
    config = ProductionConfig(
        hook_quality_weights={"curiosity": 0.7, "open_loop": 0.3}
    )
    assert config.hook_quality_weights == {"curiosity": 0.7, "open_loop": 0.3}

    with pytest.raises(ValueError, match="unsupported dimensions"):
        ProductionConfig(hook_quality_weights={"unrecognized": 1.0})

    with pytest.raises(ValueError, match="at least one positive"):
        ProductionConfig(hook_quality_weights={"curiosity": 0.0})

    with pytest.raises(ValueError, match="topic-independent dimension"):
        ProductionConfig(hook_quality_weights={"modern_relevance": 1.0})