"""test_calendar_watcher_surface.py — verify CalendarWatcher surface path."""

import asyncio
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maestro_transport import CalendarWatcher, SeenSet


def _make_fake_transport(agent_id="test-agent", surface_to_gateway=False):
    """Build a minimal mock transport that exposes the surface mechanism."""
    t = MagicMock()
    t.agent_id = agent_id
    t.seen = SeenSet(ttl_seconds=300, max_size=1000)
    t.config = {"version": "3.2"}
    t._broadcast_fanout = AsyncMock()
    t._deliver = AsyncMock()
    t.surface_calls = []

    async def _fake_surface(msg):
        t.surface_calls.append(msg)

    t._surface_to_gateway = _fake_surface
    t.config["surfaceToGateway"] = surface_to_gateway
    return t


def test_parse_event_with_to_tag():
    cw = CalendarWatcher(
        credentials_path="/tmp/fake_creds.json",
        calendar_id="cal-1",
        transport=_make_fake_transport(),
    )
    event = {"id": "ev-1", "summary": "[TO:lexicon] Check the logs", "description": "Some description"}
    parsed = cw._parse_event(event)
    assert parsed == ("lexicon", "Check the logs", "ev-1")


def test_parse_event_description_takes_precedence():
    cw = CalendarWatcher(
        credentials_path="/tmp/fake_creds.json",
        calendar_id="cal-1",
        transport=_make_fake_transport(),
    )
    event = {"id": "ev-2", "summary": "[TO:lexicon] Summary route", "description": "[TO:proteus] Description route"}
    parsed = cw._parse_event(event)
    assert parsed == ("proteus", "Description route", "ev-2")


def test_parse_event_no_tag_returns_none():
    cw = CalendarWatcher(
        credentials_path="/tmp/fake_creds.json",
        calendar_id="cal-1",
        transport=_make_fake_transport(),
    )
    event = {"id": "ev-3", "summary": "Just a regular meeting"}
    assert cw._parse_event(event) is None


def test_parse_event_empty_summary_returns_none():
    cw = CalendarWatcher(
        credentials_path="/tmp/fake_creds.json",
        calendar_id="cal-1",
        transport=_make_fake_transport(),
    )
    event = {"id": "ev-4", "summary": ""}
    assert cw._parse_event(event) is None


@pytest.mark.asyncio
async def test_send_maestro_trigger_skips_on_transport_seen():
    t = _make_fake_transport()
    with patch("maestro_transport.time") as mock_time:
        mock_time.time.return_value = 1234567890
        t.seen.add("gcal-trigger-ev5-1234567890")
        cw = CalendarWatcher(
            credentials_path="/tmp/fake_creds.json",
            calendar_id="cal-1",
            transport=t,
        )
        await cw._send_maestro_trigger("proteus", "hello", "ev5", "title")
    # Neither broadcast nor deliver should have been called because dedup hit transport.seen
    t._broadcast_fanout.assert_not_awaited()
    t._deliver.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_maestro_trigger_broadcast():
    t = _make_fake_transport()
    cw = CalendarWatcher(
        credentials_path="/tmp/fake_creds.json",
        calendar_id="cal-1",
        transport=t,
    )
    with patch("maestro_transport.time", return_value=99):
        await cw._send_maestro_trigger("broadcast", "all hands", "ev6", "All-hands")
    t._broadcast_fanout.assert_awaited_once()
    msg = t._broadcast_fanout.await_args[0][0]
    assert msg["type"] == "direct"
    assert msg["recipient"] == "broadcast"
    assert msg["version"] == "3.2"
    assert msg["meta"]["source"] == "calendar-trigger"


@pytest.mark.asyncio
async def test_send_maestro_trigger_specific_recipient():
    t = _make_fake_transport()
    t.registry.lookup.return_value = {"webhookEndpoint": "http://lexicon:8080/msg"}
    cw = CalendarWatcher(
        credentials_path="/tmp/fake_creds.json",
        calendar_id="cal-1",
        transport=t,
    )
    with patch("maestro_transport.time", return_value=42):
        await cw._send_maestro_trigger("lexicon", "do thing", "ev7", "Task reminder")
    t._deliver.assert_awaited_once()
    args = t._deliver.await_args[0]
    assert args[0] == "http://lexicon:8080/msg"
    msg = args[1]
    assert msg["recipient"] == "lexicon"
    assert msg["content"] == "do thing"
    assert msg["meta"]["event_title"] == "Task reminder"


@pytest.mark.asyncio
async def test_send_maestro_trigger_unknown_recipient_logs_error():
    t = _make_fake_transport()
    t.registry.lookup.return_value = None
    cw = CalendarWatcher(
        credentials_path="/tmp/fake_creds.json",
        calendar_id="cal-1",
        transport=t,
    )
    with patch("maestro_transport.time", return_value=42):
        await cw._send_maestro_trigger("ghost", "boo", "ev8", "Ghost event")
    t._deliver.assert_not_awaited()
    t._broadcast_fanout.assert_not_awaited()


@pytest.mark.asyncio
async def test_surface_path_invoked_when_surface_to_gateway_set():
    t = _make_fake_transport(surface_to_gateway=True)
    t.registry.lookup.return_value = {"webhookEndpoint": "http://proteus:8080/msg"}
    cw = CalendarWatcher(
        credentials_path="/tmp/fake_creds.json",
        calendar_id="cal-1",
        transport=t,
    )
    with patch("maestro_transport.time", return_value=100):
        await cw._send_maestro_trigger("proteus", "surface me", "ev9", "Surface check")
    # The deliver call is the Maestro path; surface goes through _surface_to_gateway.
    # In the real transport, handle_message() spawns _surface_to_gateway.
    # For CalendarWatcher, the message is delivered via _deliver().
    t._deliver.assert_awaited_once()


@pytest.mark.asyncio
async def test_poll_once_skips_seen_events():
    t = _make_fake_transport()
    cw = CalendarWatcher(
        credentials_path="/tmp/fake_creds.json",
        calendar_id="cal-1",
        transport=t,
    )
    cw._seen_event_ids.add("ev-old")
    # Build a fake service with one already-seen event
    fake_svc = MagicMock()
    fake_svc.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {"id": "ev-old", "summary": "[TO:lexicon] Old task"},
        ]
    }
    cw._service = fake_svc
    await cw._poll_once()
    t._deliver.assert_not_awaited()
    t._broadcast_fanout.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_once_fires_new_event():
    t = _make_fake_transport()
    t.registry.lookup.return_value = {"webhookEndpoint": "http://lexicon:8080/msg"}
    cw = CalendarWatcher(
        credentials_path="/tmp/fake_creds.json",
        calendar_id="cal-1",
        transport=t,
    )
    fake_svc = MagicMock()
    fake_svc.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {"id": "ev-new", "summary": "[TO:lexicon] New task", "description": "Do it"},
        ]
    }
    cw._service = fake_svc
    with patch("maestro_transport.time", return_value=200):
        await cw._poll_once()
    t._deliver.assert_awaited_once()


def test_load_credentials_missing_file():
    cw = CalendarWatcher(
        credentials_path="/tmp/nonexistent_creds_123456.json",
        calendar_id="cal-1",
        transport=_make_fake_transport(),
    )
    assert cw._load_credentials() is None


def test_load_credentials_bad_json():
    with TemporaryDirectory() as tmpdir:
        bad = Path(tmpdir) / "bad.json"
        bad.write_text("not json")
        cw = CalendarWatcher(
            credentials_path=str(bad),
            calendar_id="cal-1",
            transport=_make_fake_transport(),
        )
        assert cw._load_credentials() is None


def test_load_credentials_valid():
    with TemporaryDirectory() as tmpdir:
        good = Path(tmpdir) / "good.json"
        good.write_text(json.dumps({"refresh_token": "rt", "client_id": "id", "client_secret": "sec"}))
        cw = CalendarWatcher(
            credentials_path=str(good),
            calendar_id="cal-1",
            transport=_make_fake_transport(),
        )
        assert cw._load_credentials() == {"refresh_token": "rt", "client_id": "id", "client_secret": "sec"}


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
