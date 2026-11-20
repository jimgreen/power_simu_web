"""Stable signatures for command payload cursor polling."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


class CommandFrameMismatchError(RuntimeError):
    """Raised when a command payload does not match its advertised signature."""


def command_payload_signature(commands: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(commands),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
