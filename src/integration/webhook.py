"""Webhook verification and async job processing for integration mode."""

from __future__ import annotations

import hashlib
import hmac
import os
import shlex
import subprocess
import threading
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any, Optional

from .store import InstallationStore


SUPPORTED_WEBHOOK_EVENTS = {"deployment.created", "deployment.ready"}


@dataclass(frozen=True)
class WebhookEvent:
    """Normalized Vercel webhook event data."""

    event_type: str
    payload: dict[str, Any]
    deployment_id: Optional[str]
    project_id: Optional[str]
    team_id: Optional[str]
    installation_id: Optional[str]
    git_commit_ref: Optional[str]
    git_commit_sha: Optional[str]
    project_name: Optional[str]


def _normalize_signature(value: str) -> str:
    candidate = value.strip()
    if candidate.startswith("sha1="):
        return candidate.split("=", maxsplit=1)[1].strip()
    return candidate


def verify_webhook_signature(
    *,
    raw_body: bytes,
    signature_header: Optional[str],
    secret: Optional[str],
) -> tuple[bool, str | None]:
    """Verify Vercel webhook signature using HMAC-SHA1."""
    if not secret:
        return False, "Webhook secret is not configured."
    if not signature_header:
        return False, "Missing x-vercel-signature header."

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha1,
    ).hexdigest()
    provided = _normalize_signature(signature_header).lower()

    if not hmac.compare_digest(provided, expected):
        return False, "Invalid webhook signature."
    return True, None


def _first_string(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


def parse_webhook_event(payload: dict[str, Any]) -> WebhookEvent:
    """Extract event metadata from a Vercel webhook payload."""
    event_type = _first_string(payload.get("type"), payload.get("event")) or ""
    payload_data = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    deployment = (
        payload_data.get("deployment")
        if isinstance(payload_data.get("deployment"), dict)
        else payload.get("deployment")
        if isinstance(payload.get("deployment"), dict)
        else {}
    )
    project = (
        payload_data.get("project")
        if isinstance(payload_data.get("project"), dict)
        else payload.get("project")
        if isinstance(payload.get("project"), dict)
        else {}
    )
    team = (
        payload_data.get("team")
        if isinstance(payload_data.get("team"), dict)
        else payload.get("team")
        if isinstance(payload.get("team"), dict)
        else {}
    )

    deployment_id = _first_string(
        deployment.get("id"),
        payload_data.get("deploymentId"),
        payload.get("deployment_id"),
    )
    project_id = _first_string(
        deployment.get("projectId"),
        project.get("id"),
        payload_data.get("projectId"),
        payload.get("project_id"),
    )
    team_id = _first_string(
        deployment.get("teamId"),
        team.get("id"),
        payload_data.get("teamId"),
        payload.get("team_id"),
    )
    installation_id = _first_string(
        payload_data.get("installationId"),
        payload_data.get("installation_id"),
        payload.get("installation_id"),
    )

    meta = deployment.get("meta") if isinstance(deployment.get("meta"), dict) else {}

    git_commit_sha = _first_string(
        meta.get("githubCommitSha"),
        deployment.get("sha"),
        payload_data.get("sha"),
    )
    git_commit_ref = _first_string(
        meta.get("githubCommitRef"),
        deployment.get("ref"),
        payload_data.get("ref"),
    )
    project_name = _first_string(
        project.get("name"),
        deployment.get("name"),
        payload_data.get("projectName"),
    )

    return WebhookEvent(
        event_type=event_type,
        payload=payload,
        deployment_id=deployment_id,
        project_id=project_id,
        team_id=team_id,
        installation_id=installation_id,
        git_commit_ref=git_commit_ref,
        git_commit_sha=git_commit_sha,
        project_name=project_name,
    )


class DeploymentJobWorker:
    """In-process async queue for handling webhook deployment jobs."""

    def __init__(self, store: InstallationStore):
        self._store = store
        self._queue: Queue[WebhookEvent] = Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="integration-deploy-worker",
        )

    def start(self) -> None:
        self._thread.start()

    def enqueue(self, event: WebhookEvent) -> int:
        self._queue.put(event)
        return self._queue.qsize()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                event = self._queue.get(timeout=0.5)
            except Empty:
                continue

            try:
                self._process(event)
            finally:
                self._queue.task_done()

    def _process(self, event: WebhookEvent) -> None:
        if event.event_type == "deployment.created":
            print(
                "[integration] deployment.created received "
                f"(deployment_id={event.deployment_id or 'unknown'})"
            )
            return

        if event.event_type != "deployment.ready":
            print(f"[integration] ignoring unsupported webhook event: {event.event_type}")
            return

        deploy_command = os.getenv("INTEGRATION_DEPLOY_COMMAND", "python deploy_ibm.py").strip()
        if not deploy_command:
            print("[integration] deployment.ready received; no deploy command configured.")
            return

        cmd = shlex.split(deploy_command)
        if not cmd:
            print("[integration] deployment.ready received; invalid deploy command.")
            return

        env = os.environ.copy()
        if event.deployment_id:
            env["VERCEL_DEPLOYMENT_ID"] = event.deployment_id
        if event.project_id:
            env["VERCEL_PROJECT_ID"] = event.project_id
        if event.team_id:
            env["VERCEL_TEAM_ID"] = event.team_id
        if event.installation_id:
            env["VERCEL_INTEGRATION_INSTALLATION_ID"] = event.installation_id
            installation = self._store.get_installation(event.installation_id)
            if installation and isinstance(installation.get("access_token"), str):
                env.setdefault("VERCEL_INSTALLATION_TOKEN", installation["access_token"])
                env.setdefault("VERCEL_INTEGRATION_ACCESS_TOKEN", installation["access_token"])
                env.setdefault("VERCEL_CHECKS_TOKEN", installation["access_token"])
        if event.git_commit_sha:
            env["VERCEL_GIT_COMMIT_SHA"] = event.git_commit_sha
        if event.git_commit_ref:
            env["VERCEL_GIT_COMMIT_REF"] = event.git_commit_ref
        if event.project_name:
            env["VERCEL_PROJECT_NAME"] = event.project_name

        print(
            "[integration] processing deployment.ready asynchronously "
            f"(deployment_id={event.deployment_id or 'unknown'})"
        )
        result = subprocess.run(cmd, env=env, check=False)
        if result.returncode != 0:
            print(
                "[integration] async deployment command failed "
                f"with exit code {result.returncode}"
            )
            return

        print("[integration] async deployment command completed successfully")
