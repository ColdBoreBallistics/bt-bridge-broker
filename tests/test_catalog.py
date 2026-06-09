"""Unit tests for CatalogClient."""
from __future__ import annotations

import hashlib
import json
import pathlib
import pytest

from broker.catalog import CatalogClient, CatalogError


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def fake_catalog(tmp_path):
    """Build a real on-disk catalog so file:// fetch works end to end."""
    root = tmp_path / "catalog"
    (root / "builtin" / "example").mkdir(parents=True)
    display = {"schema_version": 1, "id": "builtin.example-display", "version": "1.0.0",
               "type": "display", "name": "Example Display", "notifications": [], "reads": []}
    device = {"schema_version": 1, "id": "builtin.example-device", "version": "1.0.0",
              "type": "device", "name": "Example Device",
              "signature": {"service_uuids": ["0000abcd-0000-1000-8000-00805f9b34fb"]},
              "requires": {"builtin.example-display": "^1.0.0"}}
    dpath = root / "builtin" / "example" / "display.json"
    vpath = root / "builtin" / "example" / "device.json"
    dpath.write_text(json.dumps(display))
    vpath.write_text(json.dumps(device))
    index = {
        "index_format_version": 1, "count": 2,
        "templates": [
            {"id": "builtin.example-display", "version": "1.0.0", "type": "display",
             "name": "Example Display", "author": "builtin", "namespace": "builtin",
             "path": "catalog/builtin/example/display.json",
             "sha256": _sha(dpath.read_bytes()), "requires": {}},
            {"id": "builtin.example-device", "version": "1.0.0", "type": "device",
             "name": "Example Device", "author": "builtin", "namespace": "builtin",
             "path": "catalog/builtin/example/device.json",
             "sha256": _sha(vpath.read_bytes()),
             "requires": {"builtin.example-display": "^1.0.0"}},
        ],
    }
    (root / "index.json").write_text(json.dumps(index))
    return tmp_path  # base url = file://{tmp_path}


@pytest.fixture
def client(fake_catalog):
    return CatalogClient(base_url=f"file://{fake_catalog}")


def test_fetch_index_lists_templates(client):
    index = client.fetch_index()
    ids = {t["id"] for t in index["templates"]}
    assert ids == {"builtin.example-display", "builtin.example-device"}


def test_resolve_selection_pulls_dependencies(client):
    # Selecting only the device must pull its display dependency too.
    resolved = client.resolve_selection(["builtin.example-device"])
    ids = {e["id"] for e in resolved}
    assert "builtin.example-device" in ids
    assert "builtin.example-display" in ids


def test_resolve_unknown_id_raises(client):
    with pytest.raises(CatalogError):
        client.resolve_selection(["builtin.does-not-exist"])


def test_install_writes_and_verifies(client, tmp_path):
    dest = tmp_path / "templates"
    written = client.install(["builtin.example-device"], dest_dir=dest)
    assert (dest).exists()
    files = list(dest.rglob("*.json"))
    assert len(files) == 2


def test_install_detects_sha_mismatch(client, tmp_path, monkeypatch):
    # Corrupt the expected sha in the index after fetch → install must refuse.
    orig = client.fetch_index
    def tampered():
        idx = orig()
        idx["templates"][0]["sha256"] = "0" * 64
        return idx
    monkeypatch.setattr(client, "fetch_index", tampered)
    with pytest.raises(CatalogError, match="checksum"):
        client.install(["builtin.example-display"], dest_dir=tmp_path / "t")


def test_file_traversal_path_rejected(tmp_path):
    # An index whose entry path escapes the catalog root must be refused (file:// containment).
    # The base root is tmp_path (the dir that holds catalog/), so the secret must live
    # ABOVE tmp_path and the path must climb past it to genuinely escape.
    import hashlib, json as _json
    root = tmp_path / "catalog"
    (root / "builtin").mkdir(parents=True)
    # a secret file OUTSIDE the base root (one level above tmp_path)
    secret = tmp_path.parent / "secret_escape_target.json"
    secret.write_text('{"stolen": true}')
    sha = hashlib.sha256(secret.read_bytes()).hexdigest()
    index = {
        "index_format_version": 1, "count": 1,
        "templates": [
            {"id": "builtin.evil", "version": "1.0.0", "type": "device", "name": "Evil",
             "namespace": "builtin", "path": "catalog/../../secret_escape_target.json",
             "sha256": sha, "requires": {}},
        ],
    }
    (root / "index.json").write_text(_json.dumps(index))
    c = CatalogClient(base_url=f"file://{tmp_path}")
    with pytest.raises(CatalogError, match="escapes base"):
        c.install(["builtin.evil"], dest_dir=tmp_path / "dest")


def test_malformed_index_missing_templates(tmp_path):
    root = tmp_path / "catalog"
    root.mkdir(parents=True)
    (root / "index.json").write_text('{"index_format_version": 1}')  # no templates list
    c = CatalogClient(base_url=f"file://{tmp_path}")
    with pytest.raises(CatalogError, match="malformed"):
        c.fetch_index()


def test_malformed_index_bad_version(tmp_path):
    import json as _json
    root = tmp_path / "catalog"
    root.mkdir(parents=True)
    index = {"index_format_version": 1, "count": 1, "templates": [
        {"id": "builtin.x", "version": "not-a-version", "type": "device", "name": "X",
         "namespace": "builtin", "path": "catalog/x.json", "sha256": "0"*64, "requires": {}},
    ]}
    (root / "index.json").write_text(_json.dumps(index))
    c = CatalogClient(base_url=f"file://{tmp_path}")
    with pytest.raises(CatalogError, match="invalid version"):
        c.fetch_index()


def test_file_read_error_wrapped(tmp_path):
    # Pointing the index path at a directory should raise CatalogError, not a raw OSError.
    # (Covered indirectly; ensure a directory where a file is expected is handled.)
    root = tmp_path / "catalog"
    (root / "isadir").mkdir(parents=True)  # index.json will be a directory
    (root / "index.json").mkdir()  # make index.json a directory → read_bytes raises IsADirectoryError
    c = CatalogClient(base_url=f"file://{tmp_path}")
    with pytest.raises(CatalogError):
        c.fetch_index()


def test_install_honors_dependency_version_constraint(tmp_path):
    """A device requiring ^1.0.0 of a dep must install the 1.x dep, not a 2.0.0 also present."""
    import hashlib, json
    root = tmp_path / "catalog"
    (root / "builtin").mkdir(parents=True)

    def _w(name, obj):
        p = root / "builtin" / name
        p.write_text(json.dumps(obj))
        return p, hashlib.sha256(p.read_bytes()).hexdigest()

    dep1 = {"schema_version": 1, "id": "builtin.dep", "version": "1.5.0", "type": "display", "name": "Dep 1.5"}
    dep2 = {"schema_version": 1, "id": "builtin.dep", "version": "2.0.0", "type": "display", "name": "Dep 2.0"}
    dev = {"schema_version": 1, "id": "builtin.main", "version": "1.0.0", "type": "device", "name": "Main",
           "requires": {"builtin.dep": "^1.0.0"}}
    p1, s1 = _w("dep1.json", dep1)
    p2, s2 = _w("dep2.json", dep2)
    pd, sd = _w("dev.json", dev)
    index = {"index_format_version": 1, "count": 3, "templates": [
        {"id": "builtin.dep", "version": "1.5.0", "type": "display", "name": "Dep 1.5",
         "namespace": "builtin", "path": "catalog/builtin/dep1.json", "sha256": s1, "requires": {}},
        {"id": "builtin.dep", "version": "2.0.0", "type": "display", "name": "Dep 2.0",
         "namespace": "builtin", "path": "catalog/builtin/dep2.json", "sha256": s2, "requires": {}},
        {"id": "builtin.main", "version": "1.0.0", "type": "device", "name": "Main",
         "namespace": "builtin", "path": "catalog/builtin/dev.json", "sha256": sd,
         "requires": {"builtin.dep": "^1.0.0"}},
    ]}
    (root / "index.json").write_text(json.dumps(index))
    from broker.catalog import CatalogClient
    c = CatalogClient(base_url=f"file://{tmp_path}")
    resolved = c.resolve_selection(["builtin.main"])
    dep_entry = [e for e in resolved if e["id"] == "builtin.dep"][0]
    assert dep_entry["version"] == "1.5.0"  # NOT 2.0.0


def test_resolve_unsatisfiable_dep_version_raises(tmp_path):
    import hashlib, json
    root = tmp_path / "catalog"
    (root / "builtin").mkdir(parents=True)
    dep = {"schema_version": 1, "id": "builtin.dep", "version": "2.0.0", "type": "display", "name": "Dep"}
    dev = {"schema_version": 1, "id": "builtin.main", "version": "1.0.0", "type": "device", "name": "Main",
           "requires": {"builtin.dep": "^1.0.0"}}
    (root / "builtin" / "dep.json").write_text(json.dumps(dep))
    (root / "builtin" / "dev.json").write_text(json.dumps(dev))
    sdep = hashlib.sha256((root/"builtin"/"dep.json").read_bytes()).hexdigest()
    sdev = hashlib.sha256((root/"builtin"/"dev.json").read_bytes()).hexdigest()
    index = {"index_format_version": 1, "count": 2, "templates": [
        {"id": "builtin.dep", "version": "2.0.0", "type": "display", "name": "Dep",
         "namespace": "builtin", "path": "catalog/builtin/dep.json", "sha256": sdep, "requires": {}},
        {"id": "builtin.main", "version": "1.0.0", "type": "device", "name": "Main",
         "namespace": "builtin", "path": "catalog/builtin/dev.json", "sha256": sdev,
         "requires": {"builtin.dep": "^1.0.0"}},
    ]}
    (root / "index.json").write_text(json.dumps(index))
    from broker.catalog import CatalogClient, CatalogResolveError
    c = CatalogClient(base_url=f"file://{tmp_path}")
    import pytest
    with pytest.raises(CatalogResolveError):
        c.resolve_selection(["builtin.main"])
