import importlib


def test_flags_default(monkeypatch):
    for k in ("USE_AGENT_LOOP", "AGENT_LOOP_MAX_ROUNDS", "AGENT_LOOP_MAX_TOKENS"):
        monkeypatch.delenv(k, raising=False)
    import backend.config as cfg
    importlib.reload(cfg)
    assert cfg.USE_AGENT_LOOP is False
    assert cfg.AGENT_LOOP_MAX_ROUNDS == 8
    assert cfg.AGENT_LOOP_MAX_TOKENS == cfg.TASK_AGENT_MAX_TOKENS


def test_use_agent_loop_truthy(monkeypatch):
    monkeypatch.setenv("USE_AGENT_LOOP", "true")
    import backend.config as cfg
    importlib.reload(cfg)
    assert cfg.USE_AGENT_LOOP is True
    monkeypatch.setenv("USE_AGENT_LOOP", "0")
    importlib.reload(cfg)
    assert cfg.USE_AGENT_LOOP is False
    # reload 收尾，避免污染其它测试
    monkeypatch.delenv("USE_AGENT_LOOP", raising=False)
    importlib.reload(cfg)
