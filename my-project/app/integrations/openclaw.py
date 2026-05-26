from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"
DEFAULT_NOTIFY_PATH = os.environ.get("OPENCLAW_NOTIFY_PATH", "/v1/notifications")


class OpenClawClient:

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
        self.config_path = config_path
        self.enabled = False
        self.host = "127.0.0.1"
        self.port: int | None = None
        self.token: str | None = None
        self._load_config()

    def _load_config(self) -> None:
        if not self.config_path.exists():
            logger.warning(
                "openclaw: no config at %s — adapter disabled",
                self.config_path,
            )
            return

        try:
            with self.config_path.open("r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("openclaw: cannot read config (%s) — adapter disabled", exc)
            return

        gateway = cfg.get("gateway", {})
        port = gateway.get("port")
        token = (gateway.get("auth") or {}).get("token")

        if not port or not token:
            logger.warning(
                "openclaw: config missing gateway.port or gateway.auth.token "
                "— adapter disabled"
            )
            return

        self.port = int(port)
        self.token = str(token)
        self.enabled = True
        logger.info(
            "openclaw: adapter ready (gateway %s:%d)", self.host, self.port
        )

    @property
    def base_url(self) -> str | None:
        if not self.enabled:
            return None
        return f"http://{self.host}:{self.port}"

    def notify(self, title: str, body: str, level: str = "info") -> bool:
        if not self.enabled:
            logger.debug("openclaw: notify() called but adapter is disabled")
            return False

        url = f"{self.base_url}{DEFAULT_NOTIFY_PATH}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "title": title,
            "body": body,
            "level": level,
            "source": "first-project-orchestrator",
        }

        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=5.0)
        except httpx.HTTPError as exc:
            logger.debug("openclaw: notify failed (%s)", exc)
            return False

        if response.status_code >= 400:
            logger.warning(
                "openclaw: notify got %d: %s",
                response.status_code, response.text[:200],
            )
            return False

        return True


openclaw_client = OpenClawClient()
