import pytest

from backend.agentloop import single_task

# 冻结语料：覆盖 合法JSON / 代码围栏JSON / 中文对话 / 纯命令 / 垃圾
RAW_CASES = [
    ('{"type":"single_command","command":{"command":"/give @p diamond 1","explanation":"给钻石"}}', "simple_command"),
    ('```json\n{"type":"single_command","command":{"command":"/say hi","explanation":"说"}}\n```', "simple_command"),
    ("你想要钻石剑还是铁剑呢？请告诉我具体需求。", "simple_command"),
    ("/give @p diamond 1", "simple_command"),
    ("这是一段没有结构的废话", "simple_command"),
]


@pytest.mark.parametrize("raw,otype", RAW_CASES)
def test_parse_output_parity_with_legacy(raw, otype):
    # 老实现（委托前的等价路径）：用 TaskAgent 实例方法作为 oracle
    from backend.agents.task_agent import TaskAgent
    legacy = TaskAgent.__new__(TaskAgent)  # 不跑 __init__，仅借纯函数方法
    expected = legacy._parse_output(raw, otype)
    got = single_task.parse_output(raw, otype)
    assert got == expected


def test_looks_like_conversation_truth_table():
    assert single_task.parse_output("你需要我帮你确认哪个版本？", "simple_command").get("type") == "conversation"
    assert single_task.parse_output("/give @p stone", "simple_command").get("type") != "conversation"


def test_build_messages_java_template():
    msgs = single_task.build_single_task_messages("造个传送", "simple_command", "（命令目录）", edition="java")
    joined = " ".join(m["content"] for m in msgs)
    assert "Java" in joined or "java" in joined


def test_build_messages_ambiguous_hint():
    base = single_task.build_single_task_messages("x", "simple_command", "", ambiguous=False)
    amb = single_task.build_single_task_messages("x", "simple_command", "", ambiguous=True)
    assert len("".join(m["content"] for m in amb)) > len("".join(m["content"] for m in base))


def test_run_validation_mutates_in_place():
    data = {"type": "single_command", "command": {"command": "/give @p diamond 1", "explanation": ""}}
    out = single_task.run_validation(data)
    assert out is None
    assert "validation" in data["command"]
