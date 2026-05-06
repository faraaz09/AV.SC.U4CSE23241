import os
import json
from datetime import datetime, timezone


class Logger:
    """Custom structured JSON logger (no inbuilt logging module used)."""

    LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}

    def __init__(self, service_name: str, log_dir: str = "logs", level: str = "INFO"):
        self.service_name = service_name
        self.log_dir = log_dir
        self.level = self.LEVELS.get(level.upper(), 20)
        os.makedirs(log_dir, exist_ok=True)
        self.log_file = os.path.join(log_dir, f"{service_name}.log")

    def _write(self, level: str, message: str, extra: dict = None):
        if self.LEVELS.get(level, 0) < self.level:
            return
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "service": self.service_name,
            "message": message,
        }
        if extra:
            entry.update(extra)
        line = json.dumps(entry)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def debug(self, message: str, **extra):
        self._write("DEBUG", message, extra or None)

    def info(self, message: str, **extra):
        self._write("INFO", message, extra or None)

    def warn(self, message: str, **extra):
        self._write("WARN", message, extra or None)

    def error(self, message: str, **extra):
        self._write("ERROR", message, extra or None)
