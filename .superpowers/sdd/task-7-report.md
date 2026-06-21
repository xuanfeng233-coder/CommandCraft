# Task 7 Report — 端到端 / 回归 / parity 汇总 (2B 最终任务)

## Status
✅ **COMPLETE** — All TDD steps executed; full suite regression-free.

## Commit
- **SHA**: `5a04286`
- **Subject**: `feat(agentloop): finish 终止工具 + build_default_registry 装配 7 工具`

## TDD Evidence

### Step 1: Write Failing Test
Created `tests/agentloop/test_finish_and_registry.py` with 4 async + sync test cases:
- `test_finish_normalizes_done()` — reason="done" passthrough
- `test_finish_invalid_reason_falls_back_giveup()` — invalid reason→"give_up"
- `test_build_default_registry_has_seven_tools()` — registry contains exactly 7 tools
- `test_build_default_registry_dispatches_finish()` — finish tool callable via registry

### Step 2: Confirm Failure
```
E   ModuleNotFoundError: No module named 'backend.agentloop.tools.finish'
```
✓ Expected failure (module did not exist).

### Step 3: Implement
Created `backend/agentloop/tools/finish.py`:
- **FINISH_SCHEMA** — OpenAI/Claude tool schema with reason enum and final_answer
- **handle_finish()** — normalizes reason (falls back to "give_up" if invalid); returns Observation
- **register_finish_tool()** — registers schema + handler with ToolRegistry
- **build_default_registry()** — assembles ALL 7 tools by calling:
  - `register_lookup_tools(reg)` → 4 tools
  - `register_validate_tool(reg)` → 1 tool
  - `register_search_tools(reg)` → 1 tool
  - `register_finish_tool(reg)` → 1 tool

### Step 4: Confirm Tests Pass
```
tests/agentloop/test_finish_and_registry.py ....                         [100%]
============================== 4 passed in 0.04s ===============================
```
✓ All 4 tests GREEN.

### Step 5: Full Suite Regression
```
============================== 84 passed in 0.83s ==============================
```

## Registry Assembly (7 Tools)

1. get_command_usage (lookup)
2. get_parameter_options (lookup)
3. get_formatting_codes (lookup)
4. search_wiki (lookup)
5. validate_command (validate)
6. search_web (search)
7. finish (finish)

## Files Modified

1. `backend/agentloop/tools/finish.py` (60 lines)
2. `tests/agentloop/test_finish_and_registry.py` (48 lines)

## Self-Review
✅ No placeholders
✅ Full spec coverage (7 tools, finish normalizes reason to "give_up", registry assembly)
✅ No type errors or regressions
✅ Commit message matches brief exactly

---

## 2A final-review fixes

**Commit**: `cc99e95` — `fix(agentloop): 2A 终评清理 — validate 通过时给干净文案 + 信任边界注释 + F401 + data 一致性`

### Item 1 — validate_command misleads on valid commands (behavioral + test)

**File**: `backend/agentloop/tools/validate.py` — `make_validation_report()`

Changed `feedback_text` logic from the ambiguous `struct_feedback or (...)` ternary to an explicit branch:
- `error_count == 0` → `feedback_text = "✅ 校验通过，未发现问题。"` (always clean, ignores any "请修正" header)
- `error_count > 0` → `feedback_text = struct_feedback or f"❌ {error_count} 个错误"`

**Tests updated** (`tests/agentloop/test_validate.py`):
- `test_make_report_valid_when_no_errors`: now passes a realistic `"## 命令校验发现以下问题，请修正后重新生成："` header as `struct_feedback` and asserts `feedback_text == "✅ 校验通过，未发现问题。"` (not the misleading header)
- `test_make_report_merges_errors_and_warnings`: added assertion `report.feedback_text == "❌ 1 个错误"` (struct_feedback="" + errors → fallback)
- **NEW** `test_make_report_errors_preserve_struct_feedback`: asserts that when `error_count > 0` and `struct_feedback` is non-empty, it is preserved verbatim (orchestrator-retry compatibility)
- Removed unused `import pytest`

### Item 2 — Trust boundary comment on SearXNGClient

**File**: `backend/agentloop/searxng_client.py` — `SearXNGClient.__init__`

Added one-line Chinese comment: `# 信任边界：base_url 必须来自运营方配置（SEARXNG_URL 环境变量），绝不能来自 LLM/用户输入，因为 search() 以 allow_loopback=True 调用 url_guard，会放行本地环回地址。`

No code change.

### Item 3 — F401 sweep: removed unused `import pytest`

Removed unused `import pytest` from all 6 affected files (no `pytest.` refs, no `@pytest.mark`, no `pytest.raises`):
- `tests/agentloop/test_registry.py`
- `tests/agentloop/test_lookup.py`
- `tests/agentloop/test_search.py`
- `tests/agentloop/test_searxng_client.py`
- `tests/agentloop/test_finish_and_registry.py`
- `tests/agentloop/test_validate.py` (done as part of Item 1)

### Item 4 — search_web empty-query data consistency

**File**: `backend/agentloop/tools/search.py` — `handle_search_web()`

Added `data={"hits": []}` to the empty-query rejection path, consistent with the `client is None` and `not hits` paths.

### Test Results

**Covering tests** (`test_validate.py` + `test_search.py`):
```
collected 9 items
tests/agentloop/test_validate.py .....     [55%]
tests/agentloop/test_search.py ....       [100%]
============================== 9 passed in 0.05s ===============================
```

**Full suite**:
```
85 passed in 0.83s
```

Pristine: no warnings, no failures.

---

# Task 7 — 端到端 E2E 测试报告

**File created:** `tests/agentloop/test_e2e_loop.py` (10 tests, 0 skipped)

## Scenario Coverage

### 1. flag-off 回归 (2 tests)

- `test_flag_off_regression_loop_not_called` — single-task, `USE_AGENT_LOOP=False`.
  Spy on `_run_single_task_loop`; asserts call count == 0.
  Asserts `TaskManager` constructed ≥ 1 time and stream emits `content` + `done`.

- `test_flag_off_multi_task_loop_not_called` — multi-task (2 tasks), flag-off.
  Same spy; asserts `done` event present.

### 2. flag-on happy path (2 tests)

- `test_flag_on_happy_path_single_command` — `USE_AGENT_LOOP=True`; scripted step
  emits `finish(done, <valid single_command JSON>)` in round 1.
  Asserts `content.data.type == "single_command"`, `command` is a dict, and
  `command.validation` is present (proves `run_validation` ran).

- `test_flag_on_emits_generating_and_validating` — thinking non-empty; asserts
  `task_update(generating)`, `task_update(validating)` (before `content`),
  and `task_thinking` events in correct order.

### 3. prompted provider (4 tests)

- `test_prompted_provider_reaches_done` — drives `AgentLoop` directly with
  `PromptedToolStep` + plain-chat client returning final-answer JSON (no tool call).
  Loop detects no tool_calls → `IMPLICIT_DONE`. Content contains `single_command`.

- `test_prompted_provider_tool_then_finish` — plain-chat client returns tool-call JSON
  (`{"tool":"finish","arguments":{...}}`). `PromptedToolStep.run` parses it;
  loop dispatches finish handler → `DONE` with correct content.

- `test_prompted_step_format_observation_is_user_role` — asserts
  `PromptedToolStep.format_observation` returns `role:user` (not `role:tool`).

- `test_prompted_build_step_selects_prompted` — monkeypatches `get_provider` to
  `supports_tools=False`; asserts `build_step()` returns `PromptedToolStep`.

### 4. chat.py 持久化不变 (2 tests)

- `test_chat_persistence_content_event_carries_result` — simulates the
  `_event_generator` loop from `chat.py` lines 119-126.
  Asserts `collected_result.get("type") == "single_command"` and
  `collected_result.get("command")` is a dict with the correct command string.

- `test_chat_persistence_content_before_done` — asserts `content` index < `done` index,
  confirming stream ordering.

## Full-Suite Result

```
122 passed in 0.87s   (+10 tests from 112)
```

Phase 1 + 2A + 2B all green.

## Concerns / Notes

- `_structural_validate_and_retry_simple` (TaskAgent re-execution) is not triggered
  in these tests — the scripted `/give` command passes structural validation.
  Testing that retry branch requires heavier TaskAgent mocking; out of scope for Task 7.

- Scenario 3 drives `AgentLoop` directly rather than wiring through the orchestrator's
  provider-switch path. This is lighter and still genuinely exercises `PromptedToolStep`.

## 2B final-review fixes

### Applied 2026-06-21

**Commit**: Applied as one commit via `git commit` (see SHA below).

---

### I1: task_update(completed) SSE parity — `backend/orchestrator/orchestrator.py`

In `_run_single_task_loop`, after `run_validation(result)` and post-processing (line ~681-687), and BEFORE the `content` event, added:
```python
yield {"event": "task_update", "data": {"task_id": task_id, "status": "completed", "result": result}}
```
Matches legacy `TaskAgent._task_event(task_id, "completed", result=...)` shape exactly (`task_id`, `status`, `result` keys). Only emitted on DONE/IMPLICIT_DONE/BUDGET_EXHAUSTED/GIVE_UP paths — ASK_USER path still returns `paused` + `done`.

Test `test_orchestrator_loop.py::test_flag_on_single_task_done_event_order` updated to assert `completed` index is strictly between `validating` and `content`, and that `completed` carries a `result` field.

---

### M2: Budget-exhaustion separator guard — `backend/agentloop/loop.py`

In the budget-exhaustion `else` branch (line ~129-135), the `"---"` separator was appended unconditionally before the final thinking:
```python
# BEFORE (bug)
if sr_final.thinking:
    thinking_parts.append("---")   # always prepends — causes leading "---" when no prior rounds had thinking

# AFTER (fixed)
if sr_final.thinking:
    if thinking_parts:
        thinking_parts.append("---")
```
Guards match the in-loop accumulation pattern at lines ~82-85.

Test `test_loop.py::test_budget_exhaustion` updated to assert `outcome.rounds_used == 8` (the `LoopBudget(max_rounds=8)` configured in that test).

---

### M1: Frozen golden test — `tests/agentloop/test_single_task.py`

Replaced `test_parse_output_parity_with_legacy` (tautological: oracle == impl after delegation) with `test_parse_output_frozen_golden`.

Goldens captured by running `single_task.parse_output(raw, otype)` against all 5 `RAW_CASES` entries:

| Case | Input | Expected type |
|------|-------|---------------|
| 0 | Valid JSON `single_command` | `single_command` with `command=/give @p diamond 1` |
| 1 | Code-fence JSON | `single_command` with `command=/say hi` |
| 2 | Conversation text | `conversation` with `questions[0].question` == the text |
| 3 | Bare `/give @p diamond 1` (no JSON) | `single_command` fallback, `command=""`, `explanation` == raw, warnings |
| 4 | Gibberish | `single_command` fallback, `command=""`, `explanation` == raw, warnings |

Test renamed to `test_parse_output_frozen_golden` for clarity. Parametrized against `_GOLDEN_OUTPUTS` list.

---

### M3: Dead param removal — `backend/orchestrator/orchestrator.py`

`_outcome_to_result` had a `task_id: str` parameter that was never used in the body (only `outcome` and `output_type` are referenced). Removed from signature and call site (`line ~664`):
```python
# Before
result = self._outcome_to_result(outcome, output_type, task_id)
# After
result = self._outcome_to_result(outcome, output_type)
```

---

### M4: Test durability — `tests/agentloop/test_e2e_loop.py`

Monkeypatched `_structural_validate_and_retry_simple` to return `None` in two flag-on happy-path tests:
- `test_flag_on_happy_path_single_command`
- `test_flag_on_emits_generating_and_validating`

Pattern used:
```python
async def _noop_coroutine(*args, **kwargs):
    return None
orch._structural_validate_and_retry_simple = _noop_coroutine
```
This prevents any real TaskAgent LLM call if structural validator rules change, keeping the tests deterministic.

---

### Verification

**Covering tests** (targeted):
```
tests/agentloop/test_orchestrator_loop.py tests/agentloop/test_loop.py
tests/agentloop/test_single_task.py tests/agentloop/test_e2e_loop.py
→ 27 passed in 0.26s
```

**Full suite**:
```
→ 122 passed in 0.84s
```

**Pristine**: No warnings, no failures, no skips.
