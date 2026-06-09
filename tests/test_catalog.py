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
