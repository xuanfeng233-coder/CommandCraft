from backend.llm.curated_models import CURATED_MODELS, curated_models_for


def test_known_providers_present():
    for pid in ("deepseek", "qwen", "glm", "kimi", "openai", "gemini"):
        assert pid in CURATED_MODELS
        assert curated_models_for(pid), f"{pid} 应有非空 curated 列表"


def test_unknown_provider_returns_empty():
    assert curated_models_for("nope") == []


def test_no_known_dead_models():
    # 显式确认已剔除已知过时项
    flat = [m for lst in CURATED_MODELS.values() for m in lst]
    assert "gemini-2.5-flash-preview-05-20" not in flat


def test_deepseek_has_chat_and_reasoner():
    ds = curated_models_for("deepseek")
    assert "deepseek-chat" in ds
    assert "deepseek-reasoner" in ds
