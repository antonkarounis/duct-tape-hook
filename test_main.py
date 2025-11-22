#!/usr/bin/env python3
"""
Unit tests for DuctTapeHook.

Run with: python3 -m pytest test_main.py
or: python3 test_main.py
"""

import unittest
import os
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock
from time import time, sleep
import secrets

# Import functions from main
from main import (
    Config,
    RateLimiter,
    check_auth,
    sanitize_env_vars,
    get_target,
    get_vars,
)


class TestConfig(unittest.TestCase):
    """Test Config class."""

    def test_config_initialization(self):
        """Test that Config initializes with correct defaults."""
        config = Config()
        self.assertIsNone(config.log)
        self.assertIsNone(config.auth_token)
        self.assertIsNone(config.scripts_path)
        self.assertEqual(config.port, 2000)


class TestRateLimiter(unittest.TestCase):
    """Test RateLimiter class."""

    def test_no_rate_limit_initially(self):
        """Test that new IPs are not rate limited."""
        limiter = RateLimiter(max_attempts=3, window=60)
        self.assertFalse(limiter.is_rate_limited("192.168.1.1"))

    def test_rate_limit_after_max_attempts(self):
        """Test that IPs are rate limited after max attempts."""
        limiter = RateLimiter(max_attempts=3, window=60)
        ip = "192.168.1.1"

        # Record 3 failed attempts
        for _ in range(3):
            limiter.record_attempt(ip)

        # Should now be rate limited
        self.assertTrue(limiter.is_rate_limited(ip))

    def test_rate_limit_expires(self):
        """Test that rate limits expire after the window."""
        limiter = RateLimiter(max_attempts=2, window=1)  # 1 second window
        ip = "192.168.1.1"

        # Record 2 failed attempts
        limiter.record_attempt(ip)
        limiter.record_attempt(ip)

        # Should be rate limited
        self.assertTrue(limiter.is_rate_limited(ip))

        # Wait for window to expire
        sleep(1.1)

        # Should no longer be rate limited
        self.assertFalse(limiter.is_rate_limited(ip))

    def test_different_ips_tracked_separately(self):
        """Test that different IPs are tracked independently."""
        limiter = RateLimiter(max_attempts=2, window=60)

        limiter.record_attempt("192.168.1.1")
        limiter.record_attempt("192.168.1.1")

        self.assertTrue(limiter.is_rate_limited("192.168.1.1"))
        self.assertFalse(limiter.is_rate_limited("192.168.1.2"))


class TestCheckAuth(unittest.TestCase):
    """Test authentication function."""

    def setUp(self):
        """Set up test config."""
        self.config = Config()
        self.config.auth_token = "test_token_12345"

    def test_valid_bearer_token(self):
        """Test that valid bearer token authenticates."""
        self.assertTrue(check_auth(self.config, "Bearer test_token_12345"))

    def test_case_insensitive_bearer(self):
        """Test that bearer keyword is case insensitive."""
        self.assertTrue(check_auth(self.config, "bearer test_token_12345"))
        self.assertTrue(check_auth(self.config, "BEARER test_token_12345"))

    def test_invalid_token(self):
        """Test that invalid token fails authentication."""
        self.assertFalse(check_auth(self.config, "Bearer wrong_token"))

    def test_missing_bearer_keyword(self):
        """Test that missing Bearer keyword fails."""
        self.assertFalse(check_auth(self.config, "test_token_12345"))

    def test_empty_auth_header(self):
        """Test that empty auth header fails."""
        self.assertFalse(check_auth(self.config, ""))

    def test_timing_attack_resistance(self):
        """Test that check_auth uses constant-time comparison."""
        # This test verifies that secrets.compare_digest is used
        # by checking that the function doesn't leak timing info
        # (We can't easily test timing, but we verify correct tokens work)
        config = Config()
        config.auth_token = "a" * 32

        # These should all take similar time (constant-time comparison)
        self.assertTrue(check_auth(config, f"Bearer {'a' * 32}"))
        self.assertFalse(check_auth(config, f"Bearer {'b' * 32}"))
        self.assertFalse(check_auth(config, f"Bearer {'a' * 31}b"))


class TestSanitizeEnvVars(unittest.TestCase):
    """Test environment variable sanitization."""

    def setUp(self):
        """Set up test config with mock logger."""
        self.config = Config()
        self.config.log = Mock()

    def test_empty_env_vars(self):
        """Test that empty dict returns empty dict."""
        result = sanitize_env_vars(self.config, {})
        self.assertEqual(result, {})

    def test_none_env_vars(self):
        """Test that None returns empty dict."""
        result = sanitize_env_vars(self.config, None)
        self.assertEqual(result, {})

    def test_valid_env_vars(self):
        """Test that valid env vars are passed through."""
        env_vars = {
            "MY_VAR": "value1",
            "ANOTHER_VAR": "value2",
        }
        result = sanitize_env_vars(self.config, env_vars)
        self.assertEqual(result, env_vars)

    def test_blocked_dangerous_vars(self):
        """Test that dangerous env vars are blocked."""
        dangerous_vars = {
            "PATH": "/malicious/path",
            "LD_PRELOAD": "/malicious/lib.so",
            "WEBHOOK_AUTH_TOKEN": "stolen_token",
        }
        result = sanitize_env_vars(self.config, dangerous_vars)
        self.assertEqual(result, {})
        self.assertEqual(self.config.log.warning.call_count, 3)

    def test_invalid_var_names(self):
        """Test that invalid variable names are rejected."""
        invalid_vars = {
            "my-var": "value",  # Hyphens not allowed
            "123VAR": "value",  # Can't start with number
            "my var": "value",  # Spaces not allowed
        }
        result = sanitize_env_vars(self.config, invalid_vars)
        self.assertEqual(result, {})

    def test_too_many_vars(self):
        """Test that too many vars raises ValueError."""
        many_vars = {f"VAR_{i}": "value" for i in range(51)}
        with self.assertRaises(ValueError):
            sanitize_env_vars(self.config, many_vars)

    def test_too_long_var_name(self):
        """Test that overly long var names are rejected."""
        long_name = "A" * 129
        result = sanitize_env_vars(self.config, {long_name: "value"})
        self.assertEqual(result, {})

    def test_too_long_var_value(self):
        """Test that overly long values are rejected."""
        long_value = "x" * 4097
        result = sanitize_env_vars(self.config, {"MY_VAR": long_value})
        self.assertEqual(result, {})

    def test_case_insensitive_blocking(self):
        """Test that blocked vars are case-insensitive."""
        result = sanitize_env_vars(self.config, {"path": "malicious"})
        self.assertEqual(result, {})


class TestGetTarget(unittest.TestCase):
    """Test get_target function."""

    def test_get_target_with_header(self):
        """Test extracting target from request header."""
        request = Mock()
        request.headers.get.return_value = "my_script"
        result = get_target(request)
        self.assertEqual(result, "my_script")
        request.headers.get.assert_called_once_with("Target", "")

    def test_get_target_missing_header(self):
        """Test that missing target header returns empty string."""
        request = Mock()
        request.headers.get.return_value = ""
        result = get_target(request)
        self.assertEqual(result, "")


class TestGetVars(unittest.TestCase):
    """Test get_vars function."""

    def test_get_vars_empty_body(self):
        """Test that empty body returns empty dict."""
        request = Mock()
        request.headers.get.return_value = "0"
        result = get_vars(request)
        self.assertEqual(result, {})

    def test_get_vars_with_form_data(self):
        """Test parsing form data from POST body."""
        request = Mock()
        post_data = b"VAR1=value1&VAR2=value2"
        request.headers.get.return_value = str(len(post_data))
        request.rfile.read.return_value = post_data

        result = get_vars(request)

        self.assertEqual(result, {"VAR1": "value1", "VAR2": "value2"})

    def test_get_vars_too_large(self):
        """Test that oversized requests raise ValueError."""
        request = Mock()
        request.headers.get.return_value = str(2 * 1024 * 1024)  # 2MB

        with self.assertRaises(ValueError):
            get_vars(request)

    def test_get_vars_url_encoded(self):
        """Test that URL-encoded values are decoded."""
        request = Mock()
        post_data = b"MESSAGE=hello+world&EMOJI=%F0%9F%91%8D"
        request.headers.get.return_value = str(len(post_data))
        request.rfile.read.return_value = post_data

        result = get_vars(request)

        self.assertEqual(result["MESSAGE"], "hello world")
        self.assertEqual(result["EMOJI"], "👍")


class TestIntegration(unittest.TestCase):
    """Integration tests for script execution."""

    def setUp(self):
        """Set up temporary directory for test scripts."""
        self.temp_dir = tempfile.mkdtemp()
        self.config = Config()
        self.config.log = Mock()
        self.config.scripts_path = self.temp_dir

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_run_script_not_found(self):
        """Test that nonexistent script raises FileNotFoundError."""
        from main import run_script

        with self.assertRaises(FileNotFoundError):
            run_script(self.config, "nonexistent_script")

    def test_run_script_success(self):
        """Test successful script execution."""
        from main import run_script

        # Create test script
        script_dir = os.path.join(self.temp_dir, "test_script")
        os.makedirs(script_dir)

        script_path = os.path.join(script_dir, "script.sh")
        with open(script_path, "w") as f:
            f.write("#!/bin/bash\necho 'Hello World'\n")
        os.chmod(script_path, 0o755)

        # Run script
        output = run_script(self.config, "test_script")

        self.assertIn("Hello World", output)

    def test_run_script_with_env_vars(self):
        """Test script execution with environment variables."""
        from main import run_script

        # Create test script that uses env var
        script_dir = os.path.join(self.temp_dir, "env_test")
        os.makedirs(script_dir)

        script_path = os.path.join(script_dir, "script.sh")
        with open(script_path, "w") as f:
            f.write("#!/bin/bash\necho \"Name: $USER_NAME\"\n")
        os.chmod(script_path, 0o755)

        # Run script with env var
        output = run_script(self.config, "env_test", env_vars={"USER_NAME": "Alice"})

        self.assertIn("Name: Alice", output)

    def test_run_script_timeout(self):
        """Test that long-running scripts timeout."""
        from main import run_script
        from subprocess import TimeoutExpired

        # Create script that sleeps forever
        script_dir = os.path.join(self.temp_dir, "timeout_test")
        os.makedirs(script_dir)

        script_path = os.path.join(script_dir, "script.sh")
        with open(script_path, "w") as f:
            f.write("#!/bin/bash\nsleep 1000\n")
        os.chmod(script_path, 0o755)

        # Mock SCRIPT_TIMEOUT to be very short for testing
        with patch('main.SCRIPT_TIMEOUT', 1):
            with self.assertRaises(TimeoutExpired):
                run_script(self.config, "timeout_test")


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(__import__(__name__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    exit(run_tests())
