from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def configuration_path() -> Path:
    override = os.getenv("GOKBORU_CONFIG_PATH", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".local/share/moriarty-v5/gokboru/configuration.json"


def load_local_configuration() -> dict[str, Any]:
    path = configuration_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def microsoft_credentials(*, clear_environment: bool = False) -> tuple[str | None, str | None]:
    config = load_local_configuration()
    email = (os.getenv("GOKBORU_MICROSOFT_EMAIL") or config.get("microsoft_email") or "").strip()
    password = os.getenv("GOKBORU_MICROSOFT_PASSWORD") or config.get("microsoft_password") or ""
    if clear_environment:
        os.environ.pop("GOKBORU_MICROSOFT_EMAIL", None)
        os.environ.pop("GOKBORU_MICROSOFT_PASSWORD", None)
    return (email or None, str(password) or None)
