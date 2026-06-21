"""Tests for typed predecessor context: TaskResult, render_predecessor_block,
task_result_from_legacy, and build_single_task_messages integration.

Golden strings are derived directly from orchestrator._inject_predecessor_context
(backend/orchestrator/orchestrator.py lines ~243-300).
"""

import pytest
from backend.agents.task_result import TaskResult, render_predecessor_block, task_result_from_legacy
from backend.agentloop.single_task import build_single_task_messages


# ---------------------------------------------------------------------------
# render_predecessor_block — single_command with explanation
# ---------------------------------------------------------------------------

def test_single_command_block_matches_legacy_golden():
    """Golden: mirrors legacy single_command branch (orchestrator lines ~278-282)."""
    tr = TaskResult("1", "建场地", "single_command", ["/fill ~ ~ ~ ~ ~ ~ stone"], explanation="铺地")
    block = render_predecessor_block([tr])

    # exact golden strings from the source
    expected_cmd_line = "前置任务 1（建场地）已生成命令：/fill ~ ~ ~ ~ ~ ~ stone"
    expected_exp_line = "说明：铺地"
    assert expected_cmd_line in block
    assert expected_exp_line in block
    assert block == f"{expected_cmd_line}\n{expected_exp_line}"


def test_single_command_no_explanation():
    """No explanation → only the 已生成命令 line, no 说明 line."""
    tr = TaskResult("2", "传送玩家", "single_command", ["/tp @a 0 64 0"])
    block = render_predecessor_block([tr])
    assert block == "前置任务 2（传送玩家）已生成命令：/tp @a 0 64 0"
    assert "说明" not in block


# ---------------------------------------------------------------------------
# render_predecessor_block — user_answer (resumed conversation predecessor)
# ---------------------------------------------------------------------------

def test_user_answer_block():
    """Golden: mirrors legacy user_answer branch (orchestrator lines ~269-272)."""
    tr = TaskResult("1", "确认", "conversation", [], user_answer="要钻石剑")
    block = render_predecessor_block([tr])
    expected_line = "用户在前置任务 1（确认）中的回答：要钻石剑"
    assert block == expected_line


def test_user_answer_with_commands_both_present():
    """Both user_answer AND single_command: answer line appears before command line."""
    tr = TaskResult("3", "选择武器", "single_command", ["/give @s diamond_sword"],
                    explanation="钻石剑", user_answer="钻石剑")
    block = render_predecessor_block([tr])
    lines = block.split("\n")
    assert lines[0] == "用户在前置任务 3（选择武器）中的回答：钻石剑"
    assert lines[1] == "前置任务 3（选择武器）已生成命令：/give @s diamond_sword"
    assert lines[2] == "说明：钻石剑"


# ---------------------------------------------------------------------------
# render_predecessor_block — project multi-block ordering
# ---------------------------------------------------------------------------

def test_project_block_order():
    """Golden: mirrors legacy project branch join with '; ' (orchestrator lines ~283-294)."""
    tr = TaskResult(
        "2", "建城堡", "project",
        ["/fill 0 0 0 10 0 10 stone", "/fill 0 1 0 10 5 10 air", "/setblock 5 5 5 beacon"],
    )
    block = render_predecessor_block([tr])
    expected = (
        "前置任务 2（建城堡）已生成命令："
        "/fill 0 0 0 10 0 10 stone; /fill 0 1 0 10 5 10 air; /setblock 5 5 5 beacon"
    )
    assert block == expected


def test_project_empty_commands():
    """Project with no commands still produces the 已生成命令 line (empty join)."""
    tr = TaskResult("5", "空项目", "project", [])
    block = render_predecessor_block([tr])
    assert block == "前置任务 5（空项目）已生成命令："


def test_multiple_predecessors_ordering():
    """Multiple predecessors: parts joined with \\n in iteration order."""
    tr1 = TaskResult("1", "A", "single_command", ["/say a"])
    tr2 = TaskResult("2", "B", "single_command", ["/say b"], explanation="B说明")
    block = render_predecessor_block([tr1, tr2])
    lines = block.split("\n")
    assert lines[0] == "前置任务 1（A）已生成命令：/say a"
    assert lines[1] == "前置任务 2（B）已生成命令：/say b"
    assert lines[2] == "说明：B说明"


# ---------------------------------------------------------------------------
# task_result_from_legacy
# ---------------------------------------------------------------------------

def test_legacy_single_command_extraction():
    completed = {
        "type": "single_command",
        "command": {
            "command": "/fill ~ ~ ~ ~10 ~ ~10 stone",
            "explanation": "填充地面",
        },
    }
    tr = task_result_from_legacy("42", completed)
    assert tr.task_id == "42"
    assert tr.result_type == "single_command"
    assert tr.commands == ["/fill ~ ~ ~ ~10 ~ ~10 stone"]
    assert tr.explanation == "填充地面"
    assert tr.user_answer == ""


def test_legacy_project_extraction_order():
    """Commands flattened in phase → task → block order (matches legacy lines ~285-291)."""
    completed = {
        "type": "project",
        "phases": [
            {
                "tasks": [
                    {
                        "command_blocks": [
                            {"command": "/say phase1-task1-block1"},
                            {"command": "/say phase1-task1-block2"},
                        ]
                    },
                    {
                        "command_blocks": [
                            {"command": "/say phase1-task2-block1"},
                        ]
                    },
                ]
            },
            {
                "tasks": [
                    {
                        "command_blocks": [
                            {"command": "/say phase2-task1-block1"},
                        ]
                    },
                ]
            },
        ],
    }
    tr = task_result_from_legacy("7", completed)
    assert tr.result_type == "project"
    assert tr.commands == [
        "/say phase1-task1-block1",
        "/say phase1-task1-block2",
        "/say phase1-task2-block1",
        "/say phase2-task1-block1",
    ]


def test_legacy_project_skips_empty_command():
    completed = {
        "type": "project",
        "phases": [{"tasks": [{"command_blocks": [{"command": ""}, {"command": "/say ok"}]}]}],
    }
    tr = task_result_from_legacy("8", completed)
    assert tr.commands == ["/say ok"]


def test_legacy_with_user_answer():
    completed = {"type": "single_command", "command": {"command": "/say hi", "explanation": ""}}
    tr = task_result_from_legacy("9", completed, user_answer="用户说了这个")
    assert tr.user_answer == "用户说了这个"


def test_legacy_unknown_type_becomes_conversation():
    tr = task_result_from_legacy("10", {"type": "unknown"})
    assert tr.result_type == "conversation"
    assert tr.commands == []


# ---------------------------------------------------------------------------
# build_single_task_messages — regression: predecessors=None identical to no-arg
# ---------------------------------------------------------------------------

def test_predecessors_none_is_regression_identical():
    """predecessors=None must produce byte-identical output to omitting the param."""
    a = build_single_task_messages("x", "simple_command", "（目录）")
    b = build_single_task_messages("x", "simple_command", "（目录）", predecessors=None)
    assert a == b


def test_predecessors_empty_list_leaves_user_message_unchanged():
    """Empty predecessors list: render_predecessor_block('') → no header appended."""
    a = build_single_task_messages("hello", "simple_command", "dir")
    b = build_single_task_messages("hello", "simple_command", "dir", predecessors=[])
    # render_predecessor_block([]) returns "" → no header appended
    assert a == b


# ---------------------------------------------------------------------------
# build_single_task_messages — predecessors=[...] appends header
# ---------------------------------------------------------------------------

def test_predecessors_appended():
    """Non-empty predecessors: user message must contain '## 前置任务结果'."""
    tr = TaskResult("1", "d", "single_command", ["/say hi"])
    msgs = build_single_task_messages("x", "simple_command", "", predecessors=[tr])
    assert any("## 前置任务结果" in m["content"] for m in msgs)


def test_predecessors_user_message_exact_suffix():
    """The user message ends with the full predecessor block including header."""
    tr = TaskResult("1", "建场地", "single_command", ["/fill ~ ~ ~ ~5 ~5 ~5 stone"], explanation="铺地板")
    msgs = build_single_task_messages("我的请求", "simple_command", "dir", predecessors=[tr])
    user_msg = next(m["content"] for m in msgs if m["role"] == "user")
    expected_suffix = (
        "\n\n## 前置任务结果\n"
        "前置任务 1（建场地）已生成命令：/fill ~ ~ ~ ~5 ~5 ~5 stone\n"
        "说明：铺地板"
    )
    assert user_msg.endswith(expected_suffix)


def test_predecessors_system_message_unchanged():
    """Adding predecessors must not change the system message."""
    tr = TaskResult("1", "d", "single_command", ["/say hi"])
    without = build_single_task_messages("req", "simple_command", "dir")
    with_pred = build_single_task_messages("req", "simple_command", "dir", predecessors=[tr])
    sys_without = next(m["content"] for m in without if m["role"] == "system")
    sys_with = next(m["content"] for m in with_pred if m["role"] == "system")
    assert sys_without == sys_with
