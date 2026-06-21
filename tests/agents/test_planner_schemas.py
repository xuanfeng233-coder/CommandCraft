import pytest
from pydantic import ValidationError

from backend.agents.planner_schemas import (
    Decomposition, GraphError, TaskDef, to_legacy_decomposition, validate_graph,
)


def _decomp(tasks):
    return Decomposition(tasks=[TaskDef(**t) for t in tasks])


def test_valid_dag_passes_and_maps_legacy_keys():
    d = _decomp([
        {"task_id": "1", "description": "建场地", "user_request": "造平台", "depends_on": []},
        {"task_id": "2", "description": "加机关", "user_request": "放命令方块", "depends_on": ["1"]},
    ])
    assert validate_graph(d) is None
    legacy = to_legacy_decomposition(d, original_input="x")
    assert legacy["tasks"][0]["task_id"] == "1"
    assert legacy["tasks"][0]["user_request"] == "造平台"
    assert legacy["tasks"][1]["depends_on"] == ["1"]


def test_alias_accepts_prompt_json_keys():
    # prompt 产出 legacy 键，model_validate 直接吃
    d = Decomposition.model_validate({"tasks": [{"task_id": "1", "description": "d", "user_request": "u"}]})
    assert d.tasks[0].id == "1" and d.tasks[0].title == "d" and d.tasks[0].instruction == "u"


def test_duplicate_id_raises():
    d = _decomp([{"task_id": "1"}, {"task_id": "1"}])
    with pytest.raises(GraphError) as e:
        validate_graph(d)
    assert "1" in e.value.message


def test_missing_ref_raises_named():
    d = _decomp([{"task_id": "1", "depends_on": ["99"]}])
    with pytest.raises(GraphError) as e:
        validate_graph(d)
    assert "99" in e.value.message


def test_cycle_raises():
    d = _decomp([{"task_id": "1", "depends_on": ["2"]}, {"task_id": "2", "depends_on": ["1"]}])
    with pytest.raises(GraphError) as e:
        validate_graph(d)
    assert "循环" in e.value.message


def test_self_dep_raises():
    d = _decomp([{"task_id": "1", "depends_on": ["1"]}])
    with pytest.raises(GraphError) as e:
        validate_graph(d)
    assert "自依赖" in e.value.message


def test_bad_enum_raises_validation_error():
    with pytest.raises(ValidationError):
        TaskDef(task_id="1", output_type="frobnicate")


def test_empty_tasks_valid():
    assert validate_graph(Decomposition(tasks=[])) is None
