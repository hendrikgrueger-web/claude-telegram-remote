# tests/test_workspace.py
import json
import pytest
from pathlib import Path


@pytest.fixture
def mgr(tmp_path):
    """WorkspaceManager mit isoliertem tmp_path."""
    from workspace import WorkspaceManager
    return WorkspaceManager(
        default_dir=str(tmp_path / "default"),
        config_dir=tmp_path,
    )


def test_creates_default_workspace_on_init(mgr):
    assert mgr.get_active_name() == "main"
    ws = mgr.get_active()
    assert ws is not None
    assert "directory" in ws


def test_get_active_returns_active_workspace(mgr):
    ws = mgr.get_active()
    assert ws["directory"] is not None


def test_get_by_name(mgr):
    mgr.switch("dev", directory="/tmp/dev")
    mgr.switch("main")
    ws = mgr.get("dev")
    assert ws["directory"] == "/tmp/dev"


def test_switch_creates_new_workspace_if_not_exists(mgr, tmp_path):
    mgr.switch("dev", directory=str(tmp_path / "dev"))
    assert mgr.get_active_name() == "dev"
    ws = mgr.get_active()
    assert ws["directory"] == str(tmp_path / "dev")


def test_switch_to_existing_workspace(mgr, tmp_path):
    mgr.switch("dev", directory=str(tmp_path / "dev"))
    mgr.switch("main")
    mgr.switch("dev")
    assert mgr.get_active_name() == "dev"


def test_list_workspaces_returns_all(mgr, tmp_path):
    mgr.switch("dev", directory=str(tmp_path / "dev"))
    mgr.switch("main")
    names = mgr.list_names()
    assert "main" in names
    assert "dev" in names


def test_delete_workspace(mgr, tmp_path):
    mgr.switch("dev", directory=str(tmp_path / "dev"))
    mgr.switch("main")
    mgr.delete("dev")
    assert "dev" not in mgr.list_names()


def test_delete_active_workspace_raises(mgr):
    with pytest.raises(ValueError, match="aktiven"):
        mgr.delete("main")


def test_save_and_load_session_id(tmp_path):
    """Prüft echtes Disk-Roundtrip unter Isolation."""
    from workspace import WorkspaceManager
    mgr = WorkspaceManager(default_dir=str(tmp_path / "d"), config_dir=tmp_path)
    mgr.set_session_id("abc-123")
    mgr2 = WorkspaceManager(default_dir=str(tmp_path / "d"), config_dir=tmp_path)
    ws = mgr2.get_active()
    assert ws["session_id"] == "abc-123"


def test_clear_session_id(mgr):
    mgr.set_session_id("abc-123")
    mgr.clear_session_id()
    ws = mgr.get_active()
    assert ws.get("session_id") is None
