from backend.agentloop.loop import AgentLoop
from backend.agentloop.schemas import (
    AgentOutcome, FinishReason, LoopBudget, Observation, StepResult, ToolCall,
)
from backend.agentloop.tools.registry import ToolRegistry


class _ScriptStep:
    """按脚本逐轮返回 StepResult。"""
    def __init__(self, script):
        self._script = script
        self.calls = 0

    async def run(self, messages, tool_schemas):
        sr = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        return sr

    def format_observation(self, call, obs):
        return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}


def _finish_registry(reason="done", answer="/give @p diamond"):
    reg = ToolRegistry()
    async def finish_handler(args, ctx):
        return Observation("finish", True, "finish", data={"reason": args.get("reason", reason), "final_answer": args.get("final_answer", answer)})
    reg.register({"type": "function", "function": {"name": "finish", "description": "d", "parameters": {"type": "object", "properties": {}}}}, finish_handler)
    return reg


async def _collect(loop, messages):
    events = []
    async for ev in loop.run(messages):
        events.append(ev)
    return events, loop.last_outcome


async def test_finish_done_round1():
    step = _ScriptStep([StepResult("", "", [ToolCall("c1", "finish", {"reason": "done", "final_answer": "/give @p diamond"})], {"role": "assistant", "content": ""})])
    loop = AgentLoop(registry=_finish_registry(), step=step, budget=LoopBudget(max_rounds=8), edition="bedrock")
    _, outcome = await _collect(loop, [{"role": "user", "content": "钻石"}])
    assert outcome.reason == FinishReason.DONE
    assert outcome.content == "/give @p diamond"
    assert outcome.rounds_used == 1


async def test_implicit_done():
    step = _ScriptStep([StepResult("最终答案", "", [], {"role": "assistant", "content": "最终答案"})])
    loop = AgentLoop(registry=ToolRegistry(), step=step, budget=LoopBudget(), edition="bedrock")
    _, outcome = await _collect(loop, [{"role": "user", "content": "x"}])
    assert outcome.reason == FinishReason.IMPLICIT_DONE
    assert outcome.content == "最终答案"


async def test_tool_error_becomes_observation_and_continues():
    reg = ToolRegistry()
    async def boom(args, ctx):
        raise RuntimeError("炸")
    reg.register({"type": "function", "function": {"name": "boom", "description": "d", "parameters": {"type": "object", "properties": {}}}}, boom)
    # 第一轮调 boom（出错→observation），第二轮隐式完成
    step = _ScriptStep([
        StepResult("", "", [ToolCall("c1", "boom", {})], {"role": "assistant", "content": ""}),
        StepResult("好了", "", [], {"role": "assistant", "content": "好了"}),
    ])
    loop = AgentLoop(registry=reg, step=step, budget=LoopBudget(), edition="bedrock")
    events, outcome = await _collect(loop, [{"role": "user", "content": "x"}])
    assert outcome.reason == FinishReason.IMPLICIT_DONE  # 未崩
    assert step.calls == 2


async def test_budget_exhaustion():
    # 每轮都调一个无害工具、从不 finish → 耗尽后一次无工具收尾
    reg = ToolRegistry()
    async def noop(args, ctx):
        return Observation("noop", True, "ok")
    reg.register({"type": "function", "function": {"name": "noop", "description": "d", "parameters": {"type": "object", "properties": {}}}}, noop)
    call = StepResult("", "", [ToolCall("c", "noop", {})], {"role": "assistant", "content": ""})
    final = StepResult("收尾", "", [], {"role": "assistant", "content": "收尾"})
    step = _ScriptStep([call] * 8 + [final])
    loop = AgentLoop(registry=reg, step=step, budget=LoopBudget(max_rounds=8, warn_at_round=7), edition="bedrock")
    _, outcome = await _collect(loop, [{"role": "user", "content": "x"}])
    assert outcome.reason == FinishReason.BUDGET_EXHAUSTED
    assert outcome.content == "收尾"
    assert outcome.rounds_used == 8  # M2: must equal budget.max_rounds


async def test_fresh_counters_per_run():
    # 同一 loop 实例跑两次，第二次 search_web 预算应重置（不泄漏）
    reg = ToolRegistry()
    seen = []
    async def sw(args, ctx):
        seen.append(ctx.counters.get("search_web", 0))
        ctx.counters["search_web"] = ctx.counters.get("search_web", 0) + 1
        return Observation("search_web", True, "ok")
    reg.register({"type": "function", "function": {"name": "search_web", "description": "d", "parameters": {"type": "object", "properties": {}}}}, sw)
    step1 = _ScriptStep([StepResult("", "", [ToolCall("c", "search_web", {})], {"role": "assistant", "content": ""}), StepResult("done", "", [], {"role": "assistant", "content": "done"})])
    loop = AgentLoop(registry=reg, step=step1, budget=LoopBudget(), edition="bedrock")
    await _collect(loop, [{"role": "user", "content": "1"}])
    loop._step = _ScriptStep([StepResult("", "", [ToolCall("c", "search_web", {})], {"role": "assistant", "content": ""}), StepResult("done", "", [], {"role": "assistant", "content": "done"})])
    await _collect(loop, [{"role": "user", "content": "2"}])
    assert seen == [0, 0]  # 两次都从 0 开始
