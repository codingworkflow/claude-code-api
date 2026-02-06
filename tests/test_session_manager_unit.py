"""Unit tests for session manager behaviors."""

import json
import types
from datetime import timedelta

import pytest

from claude_code_api.core import session_manager as sm_module
from claude_code_api.core.session_manager import SessionInfo, SessionManager
from claude_code_api.utils.time import utc_now


@pytest.mark.asyncio
async def test_get_session_from_db(monkeypatch):
    manager = SessionManager()

    fake_db_session = types.SimpleNamespace(
        id="sess1",
        project_id="proj",
        model="claude",
        system_prompt=None,
        created_at=utc_now(),
        updated_at=utc_now(),
        message_count=2,
        total_tokens=10,
        total_cost=0.01,
        is_active=True,
    )

    async def fake_get_session(_session_id):
        return fake_db_session

    monkeypatch.setattr(sm_module.db_manager, "get_session", fake_get_session)

    session = await manager.get_session("sess1")
    assert session is not None
    assert session.session_id == "sess1"
    assert session.total_tokens == 10

    await manager.cleanup_all()


@pytest.mark.asyncio
async def test_cleanup_expired_sessions(monkeypatch):
    manager = SessionManager()
    session = SessionInfo(session_id="sess", project_id="proj", model="claude")
    session.updated_at = utc_now() - timedelta(minutes=60)
    manager.active_sessions["sess"] = session

    async def fake_deactivate(_session_id):
        return None

    monkeypatch.setattr(sm_module.db_manager, "deactivate_session", fake_deactivate)

    await manager.cleanup_expired_sessions()
    assert "sess" not in manager.active_sessions
    await manager.cleanup_all()


@pytest.mark.asyncio
async def test_session_stats():
    manager = SessionManager()
    s1 = SessionInfo(session_id="s1", project_id="p1", model="m1")
    s1.total_tokens = 5
    s1.total_cost = 1.5
    s1.message_count = 2

    s2 = SessionInfo(session_id="s2", project_id="p1", model="m2")
    s2.total_tokens = 3
    s2.total_cost = 0.5
    s2.message_count = 1

    manager.active_sessions["s1"] = s1
    manager.active_sessions["s2"] = s2

    stats = manager.get_session_stats()
    assert stats["active_sessions"] == 2
    assert stats["total_tokens"] == 8
    assert stats["total_cost"] == 2.0
    assert stats["total_messages"] == 3
    assert set(stats["models_in_use"]) == {"m1", "m2"}
    await manager.cleanup_all()


@pytest.mark.asyncio
async def test_persist_cli_session_map_writes_expected_payload(tmp_path):
    manager = SessionManager()
    manager.session_map_path = str(tmp_path / "maps" / "session_map.json")
    manager.cli_session_index = {"cli-1": "api-1"}

    manager._persist_cli_session_map()

    with open(manager.session_map_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["cli_to_api"]["cli-1"] == "api-1"
    assert list((tmp_path / "maps").glob("session_map_*.tmp")) == []

    await manager.cleanup_all()
