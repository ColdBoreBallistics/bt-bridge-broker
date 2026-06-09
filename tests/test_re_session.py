"""Tests for RE capture session state machine."""
from __future__ import annotations

import pytest
from broker.re_session import ReSession, ReSessionState


def test_initial_state():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    assert s.state == ReSessionState.IDLE
    assert s.session_id == "s1"


def test_start_transitions_to_active():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    s.start()
    assert s.state == ReSessionState.ACTIVE


def test_add_capture_sample():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    s.start()
    s.add_sample(char_uuid="0000ff01-0000-1000-8000-00805f9b34fb", value_hex="55550102aa")
    samples = s.samples_for("0000ff01-0000-1000-8000-00805f9b34fb")
    assert len(samples) == 1
    assert samples[0] == "55550102aa"


def test_analyse_entropy():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    s.start()
    # 5 identical samples — all bytes have zero entropy
    for _ in range(5):
        s.add_sample("0000ff01-0000-1000-8000-00805f9b34fb", "0102030405")
    analysis = s.analyse()
    char_analysis = analysis["0000ff01-0000-1000-8000-00805f9b34fb"]
    assert char_analysis["sample_count"] == 5
    assert char_analysis["byte_count"] == 5
    assert all(b["entropy"] == pytest.approx(0.0) for b in char_analysis["bytes"])


def test_analyse_range():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    s.start()
    s.add_sample("0000ff01-0000-1000-8000-00805f9b34fb", "01")
    s.add_sample("0000ff01-0000-1000-8000-00805f9b34fb", "ff")
    analysis = s.analyse()
    b = analysis["0000ff01-0000-1000-8000-00805f9b34fb"]["bytes"][0]
    assert b["min"] == 1
    assert b["max"] == 255


def test_scaffold_generates_template():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    s.start()
    for _ in range(3):
        s.add_sample("0000ff01-0000-1000-8000-00805f9b34fb", "55aa0102")
    scaffold = s.scaffold(device_name="MyDevice", namespace="contrib")
    assert scaffold["type"] == "display"
    assert scaffold["id"].startswith("contrib.")
    chars = scaffold["notifications"]
    assert any(c["char"] == "0000ff01-0000-1000-8000-00805f9b34fb" for c in chars)


def test_export_tshark_format():
    s = ReSession(session_id="s1", agent_id="agent-001", address="AA:BB:CC:DD:EE:FF")
    s.start()
    s.add_sample("0000ff01-0000-1000-8000-00805f9b34fb", "aabbcc")
    export = s.export_tshark()
    assert export["_bt_bridge_export"] is True
    assert len(export["packets"]) == 1
