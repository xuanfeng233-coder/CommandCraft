"""Tests for backend/api/build.py — edition threading + clarify flag-on guard.

Uses a minimal FastAPI app with the build router (no lifespan/RAG),
monkeypatching the heavy singletons:
  - build_orchestrator  (async generator methods)
  - project_manager     (project CRUD)
  - session_db          (history writes)
  - subscription_db     (limit checks + usage increment)
  - auth.dependencies   (get_owner_context, get_current_user)
  - llm_context         (is_build_client_ready, is_subscription_client_ready)

Pattern adapted from tests/llm/test_settings_models_api.py.
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.build as build_module
from backend.auth.dependencies import OwnerContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_sse(text: str) -> list[dict[str, Any]]:
    """Parse an SSE response body into a list of {event, data} dicts."""
    events = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("event:"):
            current["event"] = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current["data"] = line[len("data:"):].strip()
        elif line == "" and current:
            if "data" in current:
                try:
                    current["data"] = json.loads(current["data"])
                except Exception:
                    pass
            events.append(dict(current))
            current = {}
    return events


async def _gen_flag_on(*events):
    """Async generator that yields SSE-style dicts for flag-on start_build."""
    for ev in events:
        yield ev


def _make_app(monkeypatch) -> FastAPI:
    """Build a minimal FastAPI app with the build router, all heavy deps patched."""
    # 1. Patch auth — always allow (device_fp = "testdevice")
    mock_owner = OwnerContext(device_fp="testdevice", user_id=None)
    monkeypatch.setattr(
        "backend.api.build.get_owner_context",
        AsyncMock(return_value=mock_owner),
    )
    monkeypatch.setattr(
        "backend.auth.dependencies.auth_db.validate_token",
        AsyncMock(return_value=None),
    )

    # 2. Patch subscription limits — always allowed
    mock_limits = {"allowed": True, "plan": "pro", "build_used": 1, "build_limit": 10}
    monkeypatch.setattr(
        "backend.api.build.subscription_db.check_build_limits",
        AsyncMock(return_value=mock_limits),
    )
    monkeypatch.setattr(
        "backend.api.build.subscription_db.increment_build_usage",
        AsyncMock(),
    )

    # 3. Patch session_db
    monkeypatch.setattr(
        "backend.api.build.session_db.create_session",
        AsyncMock(return_value="sess-001"),
    )
    monkeypatch.setattr(
        "backend.api.build.session_db.add_message",
        AsyncMock(),
    )

    # 4. Patch LLM context (no real clients needed)
    monkeypatch.setattr("backend.api.build.is_build_client_ready", lambda: False)
    monkeypatch.setattr("backend.api.build.is_subscription_client_ready", lambda: False)

    app = FastAPI()
    app.include_router(build_module.router)
    return app


# ---------------------------------------------------------------------------
# 1. flag-on: POST /api/build/start → build_plan + done
# ---------------------------------------------------------------------------

def test_start_build_flag_on_returns_build_plan(monkeypatch):
    """flag-on: /start returns SSE stream containing build_plan and done events."""
    app = _make_app(monkeypatch)

    async def fake_start_build(**kwargs):
        yield {"event": "build_phase", "data": {"phase": "planning", "project_id": "p1"}}
        yield {"event": "thinking", "data": {"text": "规划中...\n"}}
        yield {"event": "build_plan", "data": {"markdown_content": "# 计划\n- 步骤1"}}
        yield {"event": "build_phase", "data": {"phase": "reviewing", "project_id": "p1"}}
        yield {"event": "done", "data": {"project_id": "p1"}}

    monkeypatch.setattr(
        "backend.api.build.build_orchestrator.start_build",
        fake_start_build,
    )
    monkeypatch.setattr("backend.api.build.BUILD_USE_AGENT_LOOP", True)

    client = TestClient(app)
    resp = client.post(
        "/api/build/start",
        json={"message": "建一个红石门"},
        headers={"X-Device-Fp": "testdevice", "X-MC-Edition": "bedrock"},
    )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    event_names = [e.get("event") for e in events]
    assert "build_plan" in event_names, f"Expected build_plan in events: {event_names}"
    assert "done" in event_names, f"Expected done in events: {event_names}"
    assert "build_clarify" not in event_names, "build_clarify should NOT appear flag-on"


# ---------------------------------------------------------------------------
# 2. flag-off: POST /api/build/start → clarify or plan flow
# ---------------------------------------------------------------------------

def test_start_build_flag_off_normal_flow(monkeypatch):
    """flag-off: /start returns SSE (clarify or plan sequence); 200."""
    app = _make_app(monkeypatch)

    async def fake_start_build(**kwargs):
        yield {"event": "build_phase", "data": {"phase": "planning", "project_id": "p2"}}
        yield {"event": "thinking", "data": {"text": "分析需求...\n"}}
        yield {"event": "build_plan", "data": {"markdown_content": "# 方案"}}
        yield {"event": "build_phase", "data": {"phase": "reviewing", "project_id": "p2"}}
        yield {"event": "done", "data": {"project_id": "p2"}}

    monkeypatch.setattr(
        "backend.api.build.build_orchestrator.start_build",
        fake_start_build,
    )
    monkeypatch.setattr("backend.api.build.BUILD_USE_AGENT_LOOP", False)

    client = TestClient(app)
    resp = client.post(
        "/api/build/start",
        json={"message": "建一个红石门"},
        headers={"X-Device-Fp": "testdevice"},
    )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    event_names = [e.get("event") for e in events]
    assert "done" in event_names


# ---------------------------------------------------------------------------
# 3. edition flows from X-MC-Edition header → start_build → BuildState
# ---------------------------------------------------------------------------

def test_edition_threaded_from_header(monkeypatch):
    """X-MC-Edition header value reaches start_build as edition kwarg."""
    app = _make_app(monkeypatch)

    captured_kwargs: dict = {}

    async def fake_start_build(**kwargs):
        captured_kwargs.update(kwargs)
        yield {"event": "build_plan", "data": {"markdown_content": "# ok"}}
        yield {"event": "done", "data": {"project_id": "p3"}}

    monkeypatch.setattr(
        "backend.api.build.build_orchestrator.start_build",
        fake_start_build,
    )
    monkeypatch.setattr("backend.api.build.BUILD_USE_AGENT_LOOP", False)

    client = TestClient(app)
    client.post(
        "/api/build/start",
        json={"message": "测试 edition 传递"},
        headers={"X-Device-Fp": "testdevice", "X-MC-Edition": "java"},
    )

    assert captured_kwargs.get("edition") == "java", (
        f"Expected edition='java', got: {captured_kwargs}"
    )


def test_edition_defaults_to_bedrock_when_header_absent(monkeypatch):
    """When X-MC-Edition is not sent, edition defaults to 'bedrock'."""
    app = _make_app(monkeypatch)

    captured_kwargs: dict = {}

    async def fake_start_build(**kwargs):
        captured_kwargs.update(kwargs)
        yield {"event": "done", "data": {"project_id": "p4"}}

    monkeypatch.setattr(
        "backend.api.build.build_orchestrator.start_build",
        fake_start_build,
    )
    monkeypatch.setattr("backend.api.build.BUILD_USE_AGENT_LOOP", False)

    client = TestClient(app)
    client.post(
        "/api/build/start",
        json={"message": "默认版本"},
        headers={"X-Device-Fp": "testdevice"},
    )

    assert captured_kwargs.get("edition") == "bedrock", (
        f"Expected edition='bedrock', got: {captured_kwargs}"
    )


# ---------------------------------------------------------------------------
# 4. BuildState.edition is set by start_build orchestrator param
# ---------------------------------------------------------------------------

async def test_orchestrator_start_build_sets_state_edition(monkeypatch):
    """BuildOrchestrator.start_build sets state.edition from the edition param."""
    from backend.build.build_orchestrator import BuildOrchestrator

    async def collect(gen):
        events = []
        async for ev in gen:
            events.append(ev)
        return events

    orch = BuildOrchestrator()

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", False),
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.clarify_agent") as mock_ca,
        patch("backend.build.build_orchestrator.write_agent") as mock_wa,
        patch("backend.build.build_orchestrator.reader_agent") as mock_ra,
    ):
        mock_pm.create_project = AsyncMock(return_value="state-proj-001")
        mock_pm.update_status = AsyncMock()
        mock_ca.analyze = AsyncMock(
            return_value=MagicMock(
                needs_clarification=False,
                needs_search=False,
                requirements_summary="ok",
                search_queries=[],
            )
        )
        mock_wa.create_plan = AsyncMock(return_value="# 计划\n## 步骤 1: 测试 [ ]\n完成")
        mock_ra.parse_plan = MagicMock(return_value=["step1"])

        await collect(orch.start_build(
            user_input="test",
            device_fp="dev",
            edition="java",
        ))

        state = orch.get_build_state("state-proj-001")
        assert state is not None
        assert state.edition == "java", f"Expected java, got {state.edition}"


# ---------------------------------------------------------------------------
# 5. /{id}/clarify flag-on → benign done SSE (no error)
# ---------------------------------------------------------------------------

def test_clarify_flag_on_returns_done(monkeypatch):
    """flag-on: /{id}/clarify returns a benign done SSE (not 404)."""
    app = _make_app(monkeypatch)
    monkeypatch.setattr("backend.api.build.BUILD_USE_AGENT_LOOP", True)

    client = TestClient(app)
    resp = client.post(
        "/api/build/proj-999/clarify",
        json={"answers": {"q-0": "some answer"}},
        headers={"X-Device-Fp": "testdevice"},
    )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    event_names = [e.get("event") for e in events]
    assert "done" in event_names, f"Expected done event, got: {event_names}"


# ---------------------------------------------------------------------------
# 6. /{id}/clarify flag-off → normal route (404 on unknown project)
# ---------------------------------------------------------------------------

def test_clarify_flag_off_still_routable(monkeypatch):
    """flag-off: /{id}/clarify still routes correctly (returns 404 if no project)."""
    app = _make_app(monkeypatch)
    monkeypatch.setattr("backend.api.build.BUILD_USE_AGENT_LOOP", False)
    # project_manager.get_project returns None → 404
    monkeypatch.setattr(
        "backend.api.build.project_manager.get_project",
        AsyncMock(return_value=None),
    )

    client = TestClient(app)
    resp = client.post(
        "/api/build/nonexistent-proj/clarify",
        json={"answers": {"q-0": "answer"}},
        headers={"X-Device-Fp": "testdevice"},
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 7. _check_build_access: limit exceeded → 429
# ---------------------------------------------------------------------------

def test_build_access_limit_exceeded(monkeypatch):
    """_check_build_access raises 429 when build_limit reason is returned."""
    app = _make_app(monkeypatch)
    monkeypatch.setattr("backend.api.build.BUILD_USE_AGENT_LOOP", False)
    monkeypatch.setattr(
        "backend.api.build.subscription_db.check_build_limits",
        AsyncMock(return_value={"allowed": False, "reason": "build_limit"}),
    )

    client = TestClient(app)
    resp = client.post(
        "/api/build/start",
        json={"message": "test"},
        headers={"X-Device-Fp": "testdevice"},
    )

    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# 8. _check_build_access: no subscription → 403
# ---------------------------------------------------------------------------

def test_build_access_no_subscription(monkeypatch):
    """_check_build_access raises 403 when no_subscription reason is returned."""
    app = _make_app(monkeypatch)
    monkeypatch.setattr("backend.api.build.BUILD_USE_AGENT_LOOP", False)
    monkeypatch.setattr(
        "backend.api.build.subscription_db.check_build_limits",
        AsyncMock(return_value={"allowed": False, "reason": "no_subscription"}),
    )

    client = TestClient(app)
    resp = client.post(
        "/api/build/start",
        json={"message": "test"},
        headers={"X-Device-Fp": "testdevice"},
    )

    assert resp.status_code == 403
