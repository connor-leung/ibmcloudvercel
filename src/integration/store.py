"""Persistence layer for Vercel integration installation records.

Supports two backends:
  - COS (IBM Cloud Object Storage): used when IBM_COS_BUCKET is set
  - Local file: fallback for local development

Sensitive fields (ibm_cloud_api_key, access_token) are encrypted at rest
when STORE_ENCRYPTION_KEY is set (a Fernet key).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# Fields encrypted before writing and decrypted after reading.
_ENCRYPTED_FIELDS = {"ibm_cloud_api_key", "access_token"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_fernet() -> Any:
    """Return a Fernet instance if STORE_ENCRYPTION_KEY is set, else None."""
    key = os.getenv("STORE_ENCRYPTION_KEY", "").strip()
    if not key:
        return None
    from cryptography.fernet import Fernet
    return Fernet(key.encode())


def _encrypt_record(record: dict[str, Any]) -> dict[str, Any]:
    fernet = _get_fernet()
    if not fernet:
        return record
    out = dict(record)
    for field in _ENCRYPTED_FIELDS:
        if out.get(field):
            out[field] = fernet.encrypt(out[field].encode()).decode()
    return out


def _decrypt_record(record: dict[str, Any]) -> dict[str, Any]:
    fernet = _get_fernet()
    if not fernet:
        return record
    out = dict(record)
    for field in _ENCRYPTED_FIELDS:
        val = out.get(field)
        if val:
            try:
                out[field] = fernet.decrypt(val.encode()).decode()
            except Exception:
                # If decryption fails the value is either plaintext (migration)
                # or corrupt — leave it as-is and let the caller handle it.
                pass
    return out


class InstallationStore:
    """Installation record store backed by COS or a local JSON file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._cos = _build_cos_client()

        if self._cos is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal load / save
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        raw = self._read_raw()
        if not raw:
            return {"installations": {}}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {"installations": {}}
        if not isinstance(data, dict):
            return {"installations": {}}
        installations = data.get("installations")
        if not isinstance(installations, dict):
            return {"installations": {}}
        return {"installations": installations}

    def _save(self, data: dict[str, Any]) -> None:
        raw = json.dumps(data, indent=2, sort_keys=True)
        self._write_raw(raw)

    def _read_raw(self) -> str:
        if self._cos:
            return _cos_get(self._cos)
        if not self.path.exists():
            return ""
        return self.path.read_text(encoding="utf-8").strip()

    def _write_raw(self, raw: str) -> None:
        if self._cos:
            _cos_put(self._cos, raw)
            return
        temp = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp.write_text(raw, encoding="utf-8")
        temp.replace(self.path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
            previous_raw = installations.get(installation_id) or {}
            previous = _decrypt_record(previous_raw)
            now = _utc_now_iso()

            record: dict[str, Any] = {
                "installation_id": installation_id,
                "access_token": access_token,
                "team_id": team_id,
                "team_slug": team_slug,
                "project_id": project_id,
                "project_name": project_name,
                "ibm_cloud_api_key": ibm_cloud_api_key or previous.get("ibm_cloud_api_key"),
                "ibm_code_engine_project_id": (
                    ibm_code_engine_project_id or previous.get("ibm_code_engine_project_id")
                ),
                "ibm_cloud_region": ibm_cloud_region or previous.get("ibm_cloud_region"),
                "ibm_registry_secret": ibm_registry_secret or previous.get("ibm_registry_secret"),
                "ibm_icr_namespace": ibm_icr_namespace or previous.get("ibm_icr_namespace"),
                "installed_at": previous.get("installed_at", now),
                "updated_at": now,
            }

            installations[installation_id] = _encrypt_record(record)
            self._save(data)
            return record  # return plaintext to caller

    def get_installation(self, installation_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            data = self._load()
            record = data["installations"].get(installation_id)
            if not isinstance(record, dict):
                return None
            return _decrypt_record(record)

    def delete_installation(self, installation_id: str) -> bool:
        with self._lock:
            data = self._load()
            installations = data["installations"]
            if installation_id not in installations:
                return False
            del installations[installation_id]
            self._save(data)
            return True


# ------------------------------------------------------------------
# COS helpers
# ------------------------------------------------------------------

def _build_cos_client() -> Any:
    """Return an ibm_boto3 COS client if all required env vars are set."""
    bucket = (os.getenv("IBM_COS_BUCKET_NAME") or os.getenv("IBM_COS_BUCKET") or "").strip()
    if not bucket:
        return None

    api_key = (
        os.getenv("IBM_COS_API_KEY")
        or os.getenv("IBM_CLOUD_API_KEY")
        or ""
    ).strip()
    instance_crn = (os.getenv("IBM_COS_INSTANCE_CRN") or os.getenv("IBM_COS_SERVICE_INSTANCE_ID") or "").strip()
    endpoint = os.getenv("IBM_COS_ENDPOINT", "").strip()

    if not api_key or not instance_crn or not endpoint:
        print(
            "[integration] IBM_COS_BUCKET is set but IBM_COS_INSTANCE_CRN or "
            "IBM_COS_ENDPOINT is missing — falling back to local file store."
        )
        return None

    try:
        import ibm_boto3
        from ibm_botocore.client import Config

        client = ibm_boto3.client(
            "s3",
            ibm_api_key_id=api_key,
            ibm_service_instance_id=instance_crn,
            config=Config(signature_version="oauth"),
            endpoint_url=endpoint,
        )
        print(f"[integration] Using COS store: bucket={bucket}")
        return client
    except Exception as exc:
        print(f"[integration] Failed to initialise COS client: {exc} — falling back to local file.")
        return None


def _cos_bucket() -> str:
    return (os.getenv("IBM_COS_BUCKET_NAME") or os.getenv("IBM_COS_BUCKET") or "ibmcloudvercel-store")


_COS_KEY = "installations.json"


def _cos_get(client: Any) -> str:
    try:
        resp = client.get_object(Bucket=_cos_bucket(), Key=_COS_KEY)
        return resp["Body"].read().decode("utf-8")
    except Exception as exc:
        # NoSuchKey on first use — return empty string
        if "NoSuchKey" in str(exc) or "404" in str(exc):
            return ""
        print(f"[integration] COS read error: {exc}")
        return ""


def _cos_put(client: Any, raw: str) -> None:
    try:
        client.put_object(Bucket=_cos_bucket(), Key=_COS_KEY, Body=raw.encode("utf-8"))
    except Exception as exc:
        print(f"[integration] COS write error: {exc}")
