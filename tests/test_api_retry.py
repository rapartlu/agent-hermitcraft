"""
Tests for tools/api_retry.py

Covers:
  - is_rate_limited() detection for all known signal strings
  - run_with_retry() success path (no sleep)
  - run_with_retry() rate-limit path: retries, backoff values, log messages
  - run_with_retry() exhaustion: returns last result after max_retries
  - run_with_retry() non-rate-limit failure: no retry
  - Backoff cap: sleep never exceeds max_wait
  - pr_diff_fetcher.run() delegates to run_with_retry (integration smoke-test)
"""

import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, call, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.api_retry import (
    BACKOFF_FACTOR,
    INITIAL_WAIT,
    MAX_RETRIES,
    MAX_WAIT,
    RATE_LIMIT_SIGNALS,
    is_rate_limited,
    run_with_retry,
)


# ── is_rate_limited ────────────────────────────────────────────────────────────

class TestIsRateLimited(unittest.TestCase):

    def test_empty_stderr_not_rate_limited(self):
        self.assertFalse(is_rate_limited(""))

    def test_generic_error_not_rate_limited(self):
        self.assertFalse(is_rate_limited("error: repository not found"))

    def test_rate_limit_phrase_detected(self):
        self.assertTrue(is_rate_limited("error: rate limit exceeded for this resource"))

    def test_429_detected(self):
        self.assertTrue(is_rate_limited("HTTP 429: too many requests"))

    def test_secondary_rate_detected(self):
        self.assertTrue(is_rate_limited("You have triggered an abuse detection mechanism. "
                                        "secondary rate limit applied."))

    def test_too_many_requests_detected(self):
        self.assertTrue(is_rate_limited("too many requests, please slow down"))

    def test_api_rate_detected(self):
        self.assertTrue(is_rate_limited("API rate limit exceeded for user ID 12345"))

    def test_case_insensitive(self):
        self.assertTrue(is_rate_limited("RATE LIMIT EXCEEDED"))
        self.assertTrue(is_rate_limited("Rate_Limit"))

    def test_you_have_exceeded_detected(self):
        self.assertTrue(is_rate_limited("You have exceeded the GitHub API rate limit"))

    def test_abuse_detection_detected(self):
        self.assertTrue(is_rate_limited("abuse detection mechanism triggered"))

    def test_all_signals_covered(self):
        """Every entry in RATE_LIMIT_SIGNALS should be detectable."""
        for signal in RATE_LIMIT_SIGNALS:
            with self.subTest(signal=signal):
                self.assertTrue(is_rate_limited(signal))


# ── run_with_retry — success path ──────────────────────────────────────────────

class TestRunWithRetrySuccess(unittest.TestCase):

    @patch("tools.api_retry.subprocess.run")
    @patch("tools.api_retry.time.sleep")
    def test_success_on_first_attempt_no_sleep(self, mock_sleep, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
        rc, stdout, stderr = run_with_retry(["gh", "api", "test"])
        self.assertEqual(rc, 0)
        self.assertEqual(stdout, "output")
        mock_run.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("tools.api_retry.subprocess.run")
    @patch("tools.api_retry.time.sleep")
    def test_non_rate_limit_failure_no_retry(self, mock_sleep, mock_run):
        """A plain error (non-429) must not trigger any retry."""
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: repository not found"
        )
        rc, stdout, stderr = run_with_retry(["gh", "pr", "diff", "99"])
        self.assertEqual(rc, 1)
        mock_run.assert_called_once()
        mock_sleep.assert_not_called()


# ── run_with_retry — rate-limit retry path ────────────────────────────────────

class TestRunWithRetryRateLimit(unittest.TestCase):

    def _rate_limited_result(self):
        return MagicMock(returncode=1, stdout="", stderr="rate limit exceeded")

    def _success_result(self):
        return MagicMock(returncode=0, stdout="ok", stderr="")

    @patch("tools.api_retry.subprocess.run")
    @patch("tools.api_retry.time.sleep")
    def test_retries_once_then_succeeds(self, mock_sleep, mock_run):
        mock_run.side_effect = [self._rate_limited_result(), self._success_result()]
        rc, stdout, _ = run_with_retry(["gh", "api", "x"], max_retries=5, initial_wait=1)
        self.assertEqual(rc, 0)
        self.assertEqual(stdout, "ok")
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once_with(1)  # waited 1 s before retry

    @patch("tools.api_retry.subprocess.run")
    @patch("tools.api_retry.time.sleep")
    def test_retries_up_to_max_retries(self, mock_sleep, mock_run):
        """Fails max_retries+1 times → max_retries sleeps, last result returned."""
        always_rate_limited = [self._rate_limited_result()] * (MAX_RETRIES + 1)
        mock_run.side_effect = always_rate_limited
        rc, _, _ = run_with_retry(["gh", "api", "x"])
        self.assertNotEqual(rc, 0)
        self.assertEqual(mock_run.call_count, MAX_RETRIES + 1)
        self.assertEqual(mock_sleep.call_count, MAX_RETRIES)

    @patch("tools.api_retry.subprocess.run")
    @patch("tools.api_retry.time.sleep")
    def test_does_not_exceed_max_retries(self, mock_sleep, mock_run):
        """Never calls subprocess.run more than max_retries+1 times."""
        mock_run.return_value = self._rate_limited_result()
        run_with_retry(["gh", "api", "x"], max_retries=3)
        self.assertEqual(mock_run.call_count, 4)   # 1 initial + 3 retries
        self.assertEqual(mock_sleep.call_count, 3)

    @patch("tools.api_retry.subprocess.run")
    @patch("tools.api_retry.time.sleep")
    def test_backoff_sequence_doubles(self, mock_sleep, mock_run):
        """Sleep durations should double: 1, 2, 4, 8, 16 (capped at 30)."""
        mock_run.return_value = self._rate_limited_result()
        run_with_retry(["gh", "api", "x"],
                       max_retries=5, initial_wait=1, backoff_factor=2, max_wait=30)
        expected_sleeps = [call(1), call(2), call(4), call(8), call(16)]
        mock_sleep.assert_has_calls(expected_sleeps)

    @patch("tools.api_retry.subprocess.run")
    @patch("tools.api_retry.time.sleep")
    def test_backoff_capped_at_max_wait(self, mock_sleep, mock_run):
        """No sleep call should exceed max_wait."""
        mock_run.return_value = self._rate_limited_result()
        run_with_retry(["gh", "api", "x"],
                       max_retries=5, initial_wait=10, backoff_factor=4, max_wait=30)
        for c in mock_sleep.call_args_list:
            sleep_duration = c.args[0]
            self.assertLessEqual(sleep_duration, 30,
                                 f"Sleep {sleep_duration}s exceeds max_wait=30s")

    @patch("tools.api_retry.subprocess.run")
    @patch("tools.api_retry.time.sleep")
    def test_retry_logs_to_stderr(self, mock_sleep, mock_run):
        """Each retry should log a message with the wait duration and attempt number."""
        mock_run.side_effect = [self._rate_limited_result(), self._success_result()]
        captured = StringIO()
        with patch("tools.api_retry.sys.stderr", captured):
            run_with_retry(["gh", "api", "x"], max_retries=5, initial_wait=1)
        log = captured.getvalue()
        self.assertIn("[api_retry]", log)
        self.assertIn("rate limit", log)
        self.assertIn("1/5", log)   # attempt 1 of 5
        self.assertIn("1s", log)    # wait duration

    @patch("tools.api_retry.subprocess.run")
    @patch("tools.api_retry.time.sleep")
    def test_retry_log_shows_correct_attempt_numbers(self, mock_sleep, mock_run):
        """Log lines should show ascending attempt numbers."""
        mock_run.return_value = self._rate_limited_result()
        captured = StringIO()
        with patch("tools.api_retry.sys.stderr", captured):
            run_with_retry(["gh", "api", "x"], max_retries=3, initial_wait=1)
        log = captured.getvalue()
        self.assertIn("1/3", log)
        self.assertIn("2/3", log)
        self.assertIn("3/3", log)

    @patch("tools.api_retry.subprocess.run")
    @patch("tools.api_retry.time.sleep")
    def test_zero_retries_returns_immediately(self, mock_sleep, mock_run):
        """max_retries=0 should try once and return, never sleep."""
        mock_run.return_value = self._rate_limited_result()
        rc, _, _ = run_with_retry(["gh", "api", "x"], max_retries=0)
        self.assertNotEqual(rc, 0)
        mock_run.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("tools.api_retry.subprocess.run")
    @patch("tools.api_retry.time.sleep")
    def test_returns_last_result_after_exhaustion(self, mock_sleep, mock_run):
        """After all retries, the final (rate-limited) result is returned."""
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="rate limit exceeded — final"
        )
        rc, _, stderr = run_with_retry(["gh", "api", "x"], max_retries=2)
        self.assertEqual(rc, 1)
        self.assertIn("rate limit", stderr)


# ── module constants sanity ───────────────────────────────────────────────────

class TestConstants(unittest.TestCase):

    def test_max_retries_is_5(self):
        self.assertEqual(MAX_RETRIES, 5)

    def test_initial_wait_is_1_second(self):
        self.assertEqual(INITIAL_WAIT, 1.0)

    def test_backoff_factor_is_2(self):
        self.assertEqual(BACKOFF_FACTOR, 2.0)

    def test_max_wait_is_30_seconds(self):
        self.assertEqual(MAX_WAIT, 30.0)

    def test_rate_limit_signals_non_empty(self):
        self.assertGreater(len(RATE_LIMIT_SIGNALS), 0)


# ── pr_diff_fetcher integration: run() delegates to run_with_retry ────────────

class TestPrDiffFetcherUsesRetry(unittest.TestCase):

    @patch("tools.pr_diff_fetcher.run_with_retry")
    def test_run_delegates_to_run_with_retry(self, mock_retry):
        """pr_diff_fetcher.run() must call run_with_retry, not subprocess.run directly."""
        from tools.pr_diff_fetcher import run
        mock_retry.return_value = (0, "stdout", "")
        rc, stdout, stderr = run(["gh", "api", "test"], timeout=30)
        mock_retry.assert_called_once_with(["gh", "api", "test"], timeout=30)
        self.assertEqual(rc, 0)
        self.assertEqual(stdout, "stdout")

    @patch("tools.pr_diff_fetcher.run_with_retry")
    def test_run_passes_timeout(self, mock_retry):
        from tools.pr_diff_fetcher import run
        mock_retry.return_value = (0, "", "")
        run(["gh", "pr", "diff", "42"], timeout=120)
        _, kwargs = mock_retry.call_args
        self.assertEqual(kwargs.get("timeout"), 120)


if __name__ == "__main__":
    unittest.main()
