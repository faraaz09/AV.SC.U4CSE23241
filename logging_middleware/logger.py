"""
Logging Middleware
==================
Reusable function:  Log(stack, level, package, message)

Posts structured log entries to the evaluation-service Log API.
Falls back to a local JSON-lines file when the API is unavailable
or when TESTING=1 is set (used in unit tests to skip network calls).

Log API: POST http://20.207.122.201/evaluation-service/logs
Auth:    Bearer token from AUTH_TOKEN environment variable
"""

import os
import json
import requests
from datetime import datetime, timezone

# ── API endpoint ──────────────────────────────────────────────────────────────
LOG_API_URL = "http://20.207.122.201/evaluation-service/logs"

# ── Allowed values (must be lower-case, per spec) ────────────────────────────
VALID_STACKS = {"backend", "frontend"}

VALID_LEVELS = {"debug", "info", "warn", "error", "fatal"}

VALID_PACKAGES: dict[str, set] = {
    "backend": {
        # backend-only
        "cache", "controller", "cron_job", "db", "domain",
        "handler", "repository", "route", "service",
        # shared
        "auth", "config", "middleware", "utils",
    },
    "frontend": {
        # frontend-only
        "api", "component", "hook", "page", "state", "style",
        # shared
        "auth", "config", "middleware", "utils",
    },
}


# ── Public API ────────────────────────────────────────────────────────────────

def Log(stack: str, level: str, package: str, message: str) -> dict:
    """
    Reusable logging middleware.

    Args:
        stack   : "backend" | "frontend"
        level   : "debug" | "info" | "warn" | "error" | "fatal"
        package : valid package name for the given stack (lower-case)
        message : descriptive log message

    Returns:
        dict — API response body, or local-fallback response dict.

    Raises:
        ValueError — if stack / level / package values are invalid.

    Examples:
        Log("backend", "error", "handler", "received string, expected bool")
        Log("backend", "fatal", "db",      "Critical database connection failure.")
    """
    _validate(stack, level, package)
    _write_local(stack, level, package, message)

    # Skip network call when running tests
    if os.environ.get("TESTING") == "1":
        return {"logID": None, "message": "skipped — TESTING mode"}

    token = os.environ.get("AUTH_TOKEN", "")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "stack":   stack,
        "level":   level,
        "package": package,
        "message": message,
    }

    try:
        resp = requests.post(LOG_API_URL, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        _write_local(stack, "error", "middleware",
                     f"Log API unreachable ({exc}); entry already saved locally")
        return {"logID": None, "message": "API unavailable — logged locally"}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _validate(stack: str, level: str, package: str) -> None:
    if stack not in VALID_STACKS:
        raise ValueError(
            f"Invalid stack {stack!r}. Must be one of: {sorted(VALID_STACKS)}"
        )
    if level not in VALID_LEVELS:
        raise ValueError(
            f"Invalid level {level!r}. Must be one of: {sorted(VALID_LEVELS)}"
        )
    valid_pkgs = VALID_PACKAGES.get(stack, set())
    if package not in valid_pkgs:
        raise ValueError(
            f"Invalid package {package!r} for stack={stack!r}. "
            f"Valid packages: {sorted(valid_pkgs)}"
        )


def _write_local(stack: str, level: str, package: str, message: str, **extra) -> None:
    """Persist log entry to a local JSON-lines audit file."""
    log_dir = os.environ.get(
        "LOG_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"),
    )
    os.makedirs(log_dir, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level":     level,
        "stack":     stack,
        "package":   package,
        "message":   message,
    }
    entry.update(extra)
    log_file = os.path.join(log_dir, "app.log")
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
