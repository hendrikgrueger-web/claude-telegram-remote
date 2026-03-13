# workspace.py
"""WorkspaceManager: Verwaltet Named Workspaces mit Session-ID-Persistenz."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "claude-telegram"


class WorkspaceManager:
    def __init__(
        self,
        default_dir: str = "~/Coding",
        config_dir: Optional[Path] = None,
    ):
        self._default_dir = str(Path(default_dir).expanduser())
        self._config_dir = Path(config_dir) if config_dir else _DEFAULT_CONFIG_DIR
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._config_dir / "workspaces.json"
        self._state = self._load()
        if not self._state["workspaces"]:
            self._create_workspace("main", self._default_dir)
            self._state["active"] = "main"
            self._save()

    def get_active_name(self) -> str:
        return self._state["active"]

    def get_active(self) -> dict:
        return self._state["workspaces"][self._state["active"]]

    def get(self, name: str) -> dict:
        if name not in self._state["workspaces"]:
            raise KeyError(f"Workspace '{name}' nicht gefunden.")
        return self._state["workspaces"][name]

    def list_names(self) -> list[str]:
        return list(self._state["workspaces"].keys())

    def switch(self, name: str, directory: Optional[str] = None) -> dict:
        if name not in self._state["workspaces"]:
            dir_path = directory or self._default_dir
            self._create_workspace(name, dir_path)
        self._state["active"] = name
        self._save()
        return self._state["workspaces"][name]

    def delete(self, name: str) -> None:
        if name == self._state["active"]:
            raise ValueError(f"Kann aktiven Workspace '{name}' nicht löschen.")
        if name not in self._state["workspaces"]:
            raise KeyError(f"Workspace '{name}' nicht gefunden.")
        del self._state["workspaces"][name]
        self._save()

    def set_session_id(self, session_id: str) -> None:
        ws = self.get_active()
        ws["session_id"] = session_id
        ws["last_used"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def clear_session_id(self) -> None:
        ws = self.get_active()
        ws["session_id"] = None
        self._save()

    def get_model(self) -> Optional[str]:
        return self.get_active().get("model")

    def set_model(self, model: Optional[str]) -> None:
        ws = self.get_active()
        ws["model"] = model
        self._save()

    def _create_workspace(self, name: str, directory: str) -> None:
        self._state["workspaces"][name] = {
            "directory": str(Path(directory).expanduser()),
            "session_id": None,
            "last_used": datetime.now(timezone.utc).isoformat(),
        }

    def _load(self) -> dict:
        if self._file.exists():
            try:
                return json.loads(self._file.read_text())
            except (json.JSONDecodeError, KeyError):
                pass
        return {"active": "main", "workspaces": {}}

    def _save(self) -> None:
        self._file.write_text(json.dumps(self._state, indent=2))
