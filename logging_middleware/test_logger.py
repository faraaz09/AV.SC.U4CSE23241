"""
Unit tests for Logging Middleware.
Run: python test_logger.py
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

os.environ["TESTING"] = "1"   # skip live API calls

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_middleware.logger import Log, _validate, VALID_STACKS, VALID_LEVELS, VALID_PACKAGES


# ── Validation tests ──────────────────────────────────────────────────────────
class TestValidation(unittest.TestCase):

    def test_invalid_stack_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _validate("mobile", "info", "handler")
        self.assertIn("stack", str(ctx.exception))

    def test_invalid_level_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _validate("backend", "verbose", "handler")
        self.assertIn("level", str(ctx.exception))

    def test_frontend_package_rejected_on_backend(self):
        with self.assertRaises(ValueError) as ctx:
            _validate("backend", "info", "component")
        self.assertIn("package", str(ctx.exception))

    def test_backend_package_rejected_on_frontend(self):
        with self.assertRaises(ValueError) as ctx:
            _validate("frontend", "info", "handler")
        self.assertIn("package", str(ctx.exception))

    def test_all_backend_packages_accepted(self):
        for pkg in VALID_PACKAGES["backend"]:
            _validate("backend", "info", pkg)  # no exception

    def test_all_frontend_packages_accepted(self):
        for pkg in VALID_PACKAGES["frontend"]:
            _validate("frontend", "info", pkg)

    def test_all_levels_accepted(self):
        for lvl in VALID_LEVELS:
            _validate("backend", lvl, "handler")

    def test_shared_packages_valid_on_both_stacks(self):
        shared = {"auth", "config", "middleware", "utils"}
        for pkg in shared:
            _validate("backend", "info", pkg)
            _validate("frontend", "info", pkg)

    def test_empty_stack_raises(self):
        with self.assertRaises(ValueError):
            _validate("", "info", "handler")

    def test_empty_level_raises(self):
        with self.assertRaises(ValueError):
            _validate("backend", "", "handler")

    def test_empty_package_raises(self):
        with self.assertRaises(ValueError):
            _validate("backend", "info", "")

    def test_uppercase_stack_rejected(self):
        with self.assertRaises(ValueError):
            _validate("Backend", "info", "handler")

    def test_uppercase_level_rejected(self):
        with self.assertRaises(ValueError):
            _validate("backend", "INFO", "handler")


# ── Log function tests (TESTING=1 skips real API) ─────────────────────────────
class TestLogFunction(unittest.TestCase):

    def test_log_returns_dict(self):
        result = Log("backend", "info", "handler", "test message")
        self.assertIsInstance(result, dict)

    def test_log_invalid_stack_raises(self):
        with self.assertRaises(ValueError):
            Log("cloud", "info", "handler", "bad stack")

    def test_log_invalid_level_raises(self):
        with self.assertRaises(ValueError):
            Log("backend", "critical", "handler", "bad level")

    def test_log_invalid_package_raises(self):
        with self.assertRaises(ValueError):
            Log("backend", "info", "component", "frontend-only package")

    def test_spec_example_backend_error(self):
        result = Log("backend", "error", "handler", "received string, expected bool")
        self.assertIsInstance(result, dict)

    def test_spec_example_backend_fatal(self):
        result = Log("backend", "fatal", "db", "Critical database connection failure.")
        self.assertIsInstance(result, dict)

    def test_all_levels_on_backend(self):
        for level in ["debug", "info", "warn", "error", "fatal"]:
            result = Log("backend", level, "handler", f"test {level} log")
            self.assertIsInstance(result, dict)

    def test_all_levels_on_frontend(self):
        for level in ["debug", "info", "warn", "error", "fatal"]:
            result = Log("frontend", level, "component", f"test {level} log")
            self.assertIsInstance(result, dict)

    def test_log_writes_local_file(self):
        import tempfile
        log_dir = tempfile.mkdtemp()
        os.environ["LOG_DIR"] = log_dir
        Log("backend", "info", "service", "local file test")
        log_file = os.path.join(log_dir, "app.log")
        self.assertTrue(os.path.exists(log_file))
        with open(log_file) as fh:
            line = fh.readline()
        self.assertIn("local file test", line)
        del os.environ["LOG_DIR"]


# ── Live API tests (only when TESTING != 1 and AUTH_TOKEN is set) ─────────────
class TestLogAPICall(unittest.TestCase):

    @patch("logging_middleware.logger.requests.post")
    def test_post_called_with_correct_payload(self, mock_post):
        os.environ.pop("TESTING", None)   # enable API path
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"logID": "abc-123", "message": "log created successfully"}
        mock_post.return_value = mock_resp

        result = Log("backend", "error", "handler", "received string, expected bool")

        self.assertEqual(result["logID"], "abc-123")
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json", {})
        self.assertEqual(payload["stack"],   "backend")
        self.assertEqual(payload["level"],   "error")
        self.assertEqual(payload["package"], "handler")
        self.assertEqual(payload["message"], "received string, expected bool")

        os.environ["TESTING"] = "1"        # restore

    @patch("logging_middleware.logger.requests.post")
    def test_bearer_token_in_headers(self, mock_post):
        os.environ.pop("TESTING", None)
        os.environ["AUTH_TOKEN"] = "my-secret-token"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"logID": "x", "message": "log created successfully"}
        mock_post.return_value = mock_resp

        Log("backend", "info", "service", "auth header test")

        headers = (mock_post.call_args.kwargs.get("headers")
                   or mock_post.call_args[1].get("headers", {}))
        self.assertEqual(headers["Authorization"], "Bearer my-secret-token")

        os.environ["TESTING"] = "1"
        del os.environ["AUTH_TOKEN"]

    @patch("logging_middleware.logger.requests.post")
    def test_api_failure_falls_back_gracefully(self, mock_post):
        import requests as _req
        os.environ.pop("TESTING", None)
        mock_post.side_effect = _req.exceptions.ConnectionError("network down")

        result = Log("backend", "error", "handler", "api down test")

        self.assertIsNone(result["logID"])
        self.assertIn("unavailable", result["message"].lower())

        os.environ["TESTING"] = "1"


if __name__ == "__main__":
    print("Running Logging Middleware Tests...\n")
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
