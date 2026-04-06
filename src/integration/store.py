"""Persistence layer for Vercel integration installation records."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InstallationStore:
    """JSON-backed store for integration installation metadata."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"installations": {}}

        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return {"installations": {}}

        data = json.loads(raw)
        if not isinstance(data, dict):
            return {"installations": {}}

        installations = data.get("installations")
        if not isinstance(installations, dict):
            return {"installations": {}}

        return {"installations": installations}

    def _save(self, data: dict[str, Any]) -> None:
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(data, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def upsert_installation(
        self,
        *,
        installation_id: str,
        access_token: str,
        team_id: Optional[str] = None,
        team_slug: Optional[str] = None,
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
        ibm_cloud_api_key: Optional[str] = None,
        ibm_code_engine_project_id: Optional[str] = None,
        ibm_cloud_region: Optional[str] = None,
        ibm_registry_secret: Optional[str] = None,
        ibm_icr_namespace: Optional[str] = None,
    ) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            installations = data["installations"]
            previous = installations.get(installation_id) or {}
            now = _utc_now_iso()

            record = {
                "installation_id": installation_id,
                "access_token": access_token,
                "team_id": team_id,
                "team_slug": team_slug,
                "project_id": project_id,
                "project_name": project_name,
                "ibm_cloud_api_key": ibm_cloud_api_key or previous.get("ibm_cloud_api_key"),
                "ibm_code_engine_project_id": ibm_code_engine_project_id or previous.get("ibm_code_engine_project_id"),
                "ibm_cloud_region": ibm_cloud_region or previous.get("ibm_cloud_region"),
                "ibm_registry_secret": ibm_registry_secret or previous.get("ibm_registry_secret"),
                "ibm_icr_namespace": ibm_icr_namespace or previous.get("ibm_icr_namespace"),
                "installed_at": previous.get("installed_at", now),
                "updated_at": now,
            }

            installations[installation_id] = record
            self._save(data)
            return record

    def get_installation(self, installation_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            data = self._load()
            record = data["installations"].get(installation_id)
            if not isinstance(record, dict):
                return None
            return record

    def delete_installation(self, installation_id: str) -> bool:
        with self._lock:
            data = self._load()
            installations = data["installations"]
            if installation_id not in installations:
                return False

            del installations[installation_id]
            self._save(data)
            return True
