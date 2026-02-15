"""Lightweight HTTP service for Vercel integration lifecycle endpoints."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .store import InstallationStore


def _safe_json(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    content_length = int(handler.headers.get("Content-Length", "0"))
    if content_length <= 0:
        return {}

    raw = handler.rfile.read(content_length)
    if not raw:
        return {}

    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("JSON body must be an object")
    return parsed


def _normalize_scope(payload: dict[str, Any]) -> dict[str, Any]:
    team = payload.get("team") if isinstance(payload.get("team"), dict) else {}
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}

    return {
        "team_id": payload.get("team_id") or team.get("id"),
        "team_slug": payload.get("team_slug") or team.get("slug"),
        "project_id": payload.get("project_id") or project.get("id"),
        "project_name": payload.get("project_name") or project.get("name"),
    }


def _make_handler(store: InstallationStore) -> type[BaseHTTPRequestHandler]:
    class IntegrationHandler(BaseHTTPRequestHandler):
        server_version = "IBMCloudVercelIntegration/0.1"

        def log_message(self, fmt: str, *args: object) -> None:
            # Keep logging concise and predictable in CI/container logs.
            print(f"[integration] {self.address_string()} - {fmt % args}")

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/integration/health":
                _safe_json(self, {"status": "ok"}, 200)
                return

            _safe_json(self, {"error": "Not Found"}, 404)

        def do_POST(self) -> None:
            path = urlparse(self.path).path

            try:
                payload = _read_json_body(self)
            except (ValueError, json.JSONDecodeError) as exc:
                _safe_json(self, {"error": f"Invalid JSON payload: {exc}"}, 400)
                return

            if path in {"/integration/install", "/integration/update"}:
                self._handle_upsert(payload, path)
                return

            if path == "/integration/uninstall":
                self._handle_uninstall(payload)
                return

            _safe_json(self, {"error": "Not Found"}, 404)

        def _handle_upsert(self, payload: dict[str, Any], path: str) -> None:
            installation_id = payload.get("installation_id")
            access_token = payload.get("access_token")

            if not installation_id:
                _safe_json(self, {"error": "Missing required field: installation_id"}, 400)
                return
            if not access_token:
                _safe_json(self, {"error": "Missing required field: access_token"}, 400)
                return

            scope = _normalize_scope(payload)
            record = store.upsert_installation(
                installation_id=str(installation_id),
                access_token=str(access_token),
                team_id=str(scope["team_id"]) if scope["team_id"] is not None else None,
                team_slug=str(scope["team_slug"]) if scope["team_slug"] is not None else None,
                project_id=str(scope["project_id"]) if scope["project_id"] is not None else None,
                project_name=(
                    str(scope["project_name"]) if scope["project_name"] is not None else None
                ),
            )

            operation = "installed" if path.endswith("/install") else "updated"
            _safe_json(self, {"status": operation, "installation": record}, 200)

        def _handle_uninstall(self, payload: dict[str, Any]) -> None:
            installation_id = payload.get("installation_id")
            if not installation_id:
                _safe_json(self, {"error": "Missing required field: installation_id"}, 400)
                return

            removed = store.delete_installation(str(installation_id))
            if not removed:
                _safe_json(
                    self,
                    {"status": "not_found", "installation_id": str(installation_id)},
                    404,
                )
                return

            _safe_json(
                self,
                {"status": "uninstalled", "installation_id": str(installation_id)},
                200,
            )

    return IntegrationHandler


def run_server(host: str, port: int, store_path: str | Path) -> None:
    """Run the integration lifecycle service."""
    store = InstallationStore(store_path)
    handler = _make_handler(store)
    server = ThreadingHTTPServer((host, port), handler)

    print(f"Starting integration service on http://{host}:{port}")
    print(f"Using installation store: {Path(store_path).resolve()}")
    server.serve_forever()
