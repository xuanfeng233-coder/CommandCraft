from backend.agents.planner_schemas import Decomposition, TaskDef
from backend.build.agents.reader_agent import reader_agent
from backend.build.plan_adapter import decomposition_to_project_md


def _decomp(n=2, **kw):
    tasks = [TaskDef(id=str(i), title=f"步骤{i}标题", instruction=f"做第{i}件事",
                     recommended_commands=["/say hi"]) for i in range(1, n + 1)]
    return Decomposition(project_name="测试项目", overview="总览说明", tasks=tasks, **kw)


def test_roundtrip_step_count_and_order():
    d = _decomp(3)
    md = decomposition_to_project_md(d, "造个东西")
    steps = reader_agent.parse_plan(md)
    assert len(steps) == 3
    assert [s.title for s in steps] == [t.title for t in d.tasks]


def test_steps_pending_and_indexed():
    md = decomposition_to_project_md(_decomp(2), "x")
    steps = reader_agent.parse_plan(md)
    assert all(s.status == "pending" for s in steps)
    assert [s.index for s in steps] == [1, 2]


def test_overview_present_without_title_line():
    md = decomposition_to_project_md(_decomp(1), "x")
    ov = reader_agent.get_overview(md)
    assert "总览说明" in ov
    assert "测试项目" not in ov  # # title 行被 get_overview 截掉


def test_requirement_approach_nonempty():
    md = decomposition_to_project_md(_decomp(1), "x")
    step = reader_agent.get_step(md, 1)
    assert step is not None
    # 字段名以 reader_agent 源为准；断言能取到非空需求/思路
    raw = step.raw_content if hasattr(step, "raw_content") else str(step)
    assert "做第1件事" in raw


def test_title_with_brackets_and_stars_sanitized():
    d = Decomposition(project_name="P", overview="O",
                      tasks=[TaskDef(id="1", title="标题[含]**符号**", instruction="思路**粗**")])
    md = decomposition_to_project_md(d, "x")
    steps = reader_agent.parse_plan(md)
    assert len(steps) == 1  # 未被破坏


def test_empty_tasks_no_crash():
    md = decomposition_to_project_md(Decomposition(project_name="P", overview="O", tasks=[]), "x")
    assert reader_agent.parse_plan(md) == []


def test_empty_recommended_commands():
    d = Decomposition(project_name="P", overview="O",
                      tasks=[TaskDef(id="1", title="t", instruction="i", recommended_commands=[])])
    steps = reader_agent.parse_plan(decomposition_to_project_md(d, "x"))
    assert len(steps) == 1
