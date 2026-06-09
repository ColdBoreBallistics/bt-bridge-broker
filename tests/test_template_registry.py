"""Unit tests for the full TemplateRegistry."""
from __future__ import annotations

import json
import pathlib
import pytest
import tempfile

from broker.template_registry import TemplateRegistry, SUPPORTED_SCHEMA_VERSIONS


@pytest.fixture
def tmpdir_path(tmp_path):
    return tmp_path


def write_template(directory: pathlib.Path, filename: str, content: dict) -> pathlib.Path:
    p = directory / filename
    p.write_text(json.dumps(content), encoding="utf-8")
    return p


def make_device_template(tid="builtin.test-device", ver="1.0.0"):
    return {
        "schema_version": 1,
        "id": tid,
        "version": ver,
        "type": "device",
        "name": "Test Device",
        "signature": {"service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"]},
        "variants": []
    }


def make_display_template(tid="builtin.test-display", ver="1.0.0"):
    return {
        "schema_version": 1,
        "id": tid,
        "version": ver,
        "type": "display",
        "name": "Test Display",
        "notifications": [],
        "reads": []
    }


def test_load_empty_dir(tmpdir_path):
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.list_all() == []


def test_load_single_template(tmpdir_path):
    write_template(tmpdir_path, "device.json", make_device_template())
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert len(tr.list_all()) == 1


def test_load_multiple_templates(tmpdir_path):
    write_template(tmpdir_path, "device.json", make_device_template())
    write_template(tmpdir_path, "display.json", make_display_template())
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert len(tr.list_all()) == 2


def test_duplicate_id_version_raises(tmpdir_path):
    write_template(tmpdir_path, "device1.json", make_device_template())
    write_template(tmpdir_path, "device2.json", make_device_template())
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    with pytest.raises(RuntimeError, match="Duplicate template"):
        tr.load()


def test_schema_version_too_high_skipped(tmpdir_path):
    t = make_device_template()
    t["schema_version"] = 9999
    write_template(tmpdir_path, "future.json", t)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.list_all() == []


def test_missing_id_skipped(tmpdir_path):
    t = make_device_template()
    del t["id"]
    write_template(tmpdir_path, "bad.json", t)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.list_all() == []


def test_missing_version_skipped(tmpdir_path):
    t = make_device_template()
    del t["version"]
    write_template(tmpdir_path, "bad.json", t)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.list_all() == []


def test_get_by_id_version(tmpdir_path):
    write_template(tmpdir_path, "device.json", make_device_template())
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    t = tr.get("builtin.test-device", "1.0.0")
    assert t is not None
    assert t["id"] == "builtin.test-device"


def test_get_missing_returns_none(tmpdir_path):
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.get("builtin.nonexistent", "1.0.0") is None


def test_list_versions(tmpdir_path):
    write_template(tmpdir_path, "v1.json", make_device_template(ver="1.0.0"))
    write_template(tmpdir_path, "v2.json", make_device_template(ver="2.0.0"))
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    versions = tr.list_versions("builtin.test-device")
    assert set(versions) == {"1.0.0", "2.0.0"}


def test_latest_version(tmpdir_path):
    write_template(tmpdir_path, "v1.json", make_device_template(ver="1.0.0"))
    write_template(tmpdir_path, "v2.json", make_device_template(ver="2.0.0"))
    write_template(tmpdir_path, "v110.json", make_device_template(ver="1.10.0"))
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.latest_version("builtin.test-device") == "2.0.0"


def test_match_device_exact(tmpdir_path):
    t = make_device_template()
    t["signature"] = {"service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"]}
    write_template(tmpdir_path, "device.json", t)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    matches = tr.match_device(["0000abcd-0000-1000-8000-00805f9b34fb"])
    assert len(matches) == 1
    assert matches[0]["confidence"] == "exact"
    assert matches[0]["device_template_id"] == "builtin.test-device"


def test_match_device_no_match(tmpdir_path):
    t = make_device_template()
    t["signature"] = {"service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"]}
    write_template(tmpdir_path, "device.json", t)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    matches = tr.match_device(["0000ffff-0000-1000-8000-00805f9b34fb"])
    assert matches == []


def test_match_device_name_prefix(tmpdir_path):
    t = make_device_template()
    t["signature"] = {
        "service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"],
        "name_prefix": "WF"
    }
    write_template(tmpdir_path, "device.json", t)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.match_device(["0000abcd-0000-1000-8000-00805f9b34fb"], name_prefix="WF-Tactical") != []
    assert tr.match_device(["0000abcd-0000-1000-8000-00805f9b34fb"], name_prefix="Niimbot") == []


def test_manifest_excludes_quarantined(tmpdir_path):
    good = make_device_template("builtin.good", "1.0.0")
    bad = make_device_template("builtin.bad", "1.0.0")
    bad["requires"] = {"builtin.missing": "^1.0.0"}
    write_template(tmpdir_path, "good.json", good)
    write_template(tmpdir_path, "bad.json", bad)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    manifest = tr.manifest()
    ids = [m["id"] for m in manifest]
    assert "builtin.good" in ids
    assert "builtin.bad" not in ids
