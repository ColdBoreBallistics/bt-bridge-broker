"""Unit tests for the full TemplateRegistry."""
from __future__ import annotations

import json
import pathlib
import pytest

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


def test_caret_requires_resolves_when_satisfied(tmpdir_path):
    # A device that requires ^1.0.0 of a display that IS installed at 1.2.0 must NOT be quarantined.
    dep = make_display_template("builtin.dep", "1.2.0")
    main = make_device_template("builtin.main", "1.0.0")
    main["requires"] = {"builtin.dep": "^1.0.0"}
    write_template(tmpdir_path, "dep.json", dep)
    write_template(tmpdir_path, "main.json", main)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()  # must NOT raise InvalidSpecifier
    assert not tr.is_quarantined("builtin.main", "1.0.0")
    ids = [m["id"] for m in tr.manifest()]
    assert "builtin.main" in ids


def test_caret_requires_quarantines_when_out_of_range(tmpdir_path):
    # require ^1.0.0 but only 2.0.0 installed -> out of range -> quarantined.
    dep = make_display_template("builtin.dep", "2.0.0")
    main = make_device_template("builtin.main", "1.0.0")
    main["requires"] = {"builtin.dep": "^1.0.0"}
    write_template(tmpdir_path, "dep.json", dep)
    write_template(tmpdir_path, "main.json", main)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert tr.is_quarantined("builtin.main", "1.0.0")


def test_tilde_requires_resolves_within_minor(tmpdir_path):
    dep = make_display_template("builtin.dep", "1.2.5")
    main = make_device_template("builtin.main", "1.0.0")
    main["requires"] = {"builtin.dep": "~1.2.0"}
    write_template(tmpdir_path, "dep.json", dep)
    write_template(tmpdir_path, "main.json", main)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert not tr.is_quarantined("builtin.main", "1.0.0")


def test_pep440_requires_still_works(tmpdir_path):
    dep = make_display_template("builtin.dep", "1.5.0")
    main = make_device_template("builtin.main", "1.0.0")
    main["requires"] = {"builtin.dep": ">=1.0.0,<2.0.0"}
    write_template(tmpdir_path, "dep.json", dep)
    write_template(tmpdir_path, "main.json", main)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    assert not tr.is_quarantined("builtin.main", "1.0.0")


def test_malformed_requires_quarantines_not_crashes(tmpdir_path):
    dep = make_display_template("builtin.dep", "1.0.0")
    main = make_device_template("builtin.main", "1.0.0")
    main["requires"] = {"builtin.dep": "not-a-version-spec!!!"}
    write_template(tmpdir_path, "dep.json", dep)
    write_template(tmpdir_path, "main.json", main)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()  # must NOT raise
    assert tr.is_quarantined("builtin.main", "1.0.0")


def test_save_draft_rejects_path_traversal_id(tmpdir_path):
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    evil = {
        "schema_version": 1,
        "id": "../../../../tmp/pwned",
        "version": "1.0.0",
        "type": "display",
        "name": "evil",
    }
    with pytest.raises(ValueError):
        tr.save_draft(evil)
    # Nothing was written outside the templates dir.
    import pathlib as _pl
    assert not _pl.Path("/tmp/pwned-display").exists()


def test_save_draft_rejects_bad_version(tmpdir_path):
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    with pytest.raises(ValueError):
        tr.save_draft({"schema_version": 1, "id": "contrib.ok", "version": "../evil", "type": "display", "name": "x"})


def test_save_draft_writes_valid_draft(tmpdir_path):
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    path = tr.save_draft({
        "schema_version": 1, "id": "contrib.my-draft", "version": "0.1.0",
        "type": "display", "name": "My Draft", "notifications": [], "reads": [],
    })
    assert path.exists()
    # The written file is inside the templates dir.
    assert str(path).startswith(str(tmpdir_path))


def test_match_device_variant_signature(tmpdir_path):
    # Device template with variants; match should report the matching variant_id.
    t = {
        "schema_version": 1,
        "id": "builtin.multi",
        "version": "1.0.0",
        "type": "device",
        "name": "Multi",
        "signature": {"service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"]},
        "variants": [
            {"variant_id": "v-a", "name": "A", "signature": {"service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"], "name_prefix": "AA"}},
            {"variant_id": "v-b", "name": "B", "signature": {"service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"], "name_prefix": "BB"}},
        ],
    }
    write_template(tmpdir_path, "multi.json", t)
    tr = TemplateRegistry(templates_dir=tmpdir_path)
    tr.load()
    matches = tr.match_device(["0000abcd-0000-1000-8000-00805f9b34fb"], name_prefix="BB-thing")
    assert len(matches) == 1
    assert matches[0]["variant_id"] == "v-b"
