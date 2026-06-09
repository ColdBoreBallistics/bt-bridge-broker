"""Tests for the template CI lint script."""
from __future__ import annotations

import json
import pathlib
import pytest

from tools.lint_templates import lint_directory, LintResult


@pytest.fixture
def tmpdir_path(tmp_path):
    return tmp_path


def write_template(directory, filename, content):
    (directory / filename).write_text(json.dumps(content))


def make_valid_template(tid="contrib.test", ver="1.0.0"):
    return {
        "schema_version": 1,
        "id": tid,
        "version": ver,
        "type": "display",
        "name": "Test"
    }


def test_lint_empty_dir(tmpdir_path):
    result = lint_directory(tmpdir_path)
    assert result.errors == []
    assert result.warnings == []


def test_lint_valid_template(tmpdir_path):
    write_template(tmpdir_path, "t.json", make_valid_template())
    result = lint_directory(tmpdir_path)
    assert result.errors == []


def test_lint_invalid_json(tmpdir_path):
    (tmpdir_path / "bad.json").write_text("not json")
    result = lint_directory(tmpdir_path)
    assert any("JSON" in e for e in result.errors)


def test_lint_missing_id(tmpdir_path):
    t = make_valid_template()
    del t["id"]
    write_template(tmpdir_path, "t.json", t)
    result = lint_directory(tmpdir_path)
    assert any("id" in e.lower() for e in result.errors)


def test_lint_missing_version(tmpdir_path):
    t = make_valid_template()
    del t["version"]
    write_template(tmpdir_path, "t.json", t)
    result = lint_directory(tmpdir_path)
    assert any("version" in e.lower() for e in result.errors)


def test_lint_duplicate_id_version(tmpdir_path):
    write_template(tmpdir_path, "a.json", make_valid_template())
    write_template(tmpdir_path, "b.json", make_valid_template())
    result = lint_directory(tmpdir_path)
    assert any("duplicate" in e.lower() for e in result.errors)


def test_lint_builtin_in_contrib_pr(tmpdir_path):
    t = make_valid_template("builtin.should-fail", "1.0.0")
    write_template(tmpdir_path, "t.json", t)
    result = lint_directory(tmpdir_path, is_community_pr=True)
    assert any("builtin" in e.lower() for e in result.errors)


def test_lint_unresolvable_requires(tmpdir_path):
    t = make_valid_template()
    t["requires"] = {"builtin.missing-dep": "^1.0.0"}
    write_template(tmpdir_path, "t.json", t)
    result = lint_directory(tmpdir_path)
    assert any("requires" in e.lower() or "unresolvable" in e.lower() for e in result.errors)


def test_lint_non_dict_top_level_json(tmpdir_path):
    # A JSON array / string / number at top level must produce a clean error, not crash.
    (tmpdir_path / "arr.json").write_text("[]")
    (tmpdir_path / "str.json").write_text('"hello"')
    (tmpdir_path / "num.json").write_text("42")
    result = lint_directory(tmpdir_path)  # must not raise
    assert any("not an object" in e.lower() or "object" in e.lower() for e in result.errors)
    assert len(result.errors) >= 3


def test_lint_exit_code(tmpdir_path, monkeypatch):
    import sys
    from tools.lint_templates import main
    monkeypatch.setattr(sys, "argv", ["lint_templates", str(tmpdir_path)])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
