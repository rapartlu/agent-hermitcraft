"""
api_retry.py
============
Exponential-backoff retry wrapper for subprocess calls (primarily GitHub
CLI ``gh`` commands) that may be throttled by a rate-limit response.

Problem
-------
GitHub's REST API returns HTTP 429 or an "API rate limit exceeded" message
when a client sends too many requests in a short window.  Without retry
logic every agent tool that shells out to ``gh api`` / ``gh pr diff`` fails
hard on the first throttled call, requiring a human or supervisor to
re-dispatch the task.

Strategy
--------
1. Run the command normally.
2. If it exits non-zero *and* stderr contains a known rate-limit signal,
   wait (1 s → 2 s → 4 s → 8 s → 16 s, capped at 30 s) and retry.
3. Log each retry attempt to stderr so operators can monitor backoff
   behaviour without inspecting internal state.
4. After exhausting *max_retries* attempts, return the last result
   (non-zero exit code) so callers can decide how to handle final failure.

Usage
-----
    from tools.api_retry import run_with_retry

    rc, stdout, stderr = run_with_retry(["gh", "api", "repos/owner/repo"])
    if rc != 0:
        # all retries exhausted or non-rate-limit error
        raise RuntimeError(stderr)

Exit conventions (same as subprocess.run)
-----------------------------------------
    0   — success
    non-zero — command failed (after all retries if rate-limited)

Constants (all overridable per-call)
-------------------------------------
    MAX_RETRIES    = 5     retry attempts after the first failure
    INITIAL_WAIT   = 1.0   seconds before first retry
    BACKOFF_FACTOR = 2     multiplier applied after each retry
    MAX_WAIT       = 30    seconds ceiling on any single sleep
"""

import subprocess
import sys
import time

# ── tuneable defaults ──────────────────────────────────────────────────────────

MAX_RETRIES: int = 5
INITIAL_WAIT: float = 1.0   # seconds
BACKOFF_FACTOR: float = 2.0
MAX_WAIT: float = 30.0      # seconds

# Substrings that indicate a GitHub API rate-limit response (case-insensitive).
RATE_LIMIT_SIGNALS: tuple[str, ...] = (
    "rate limit",
    "rate_limit",
    "429",
    "secondary rate",
    "api rate",
    "too many requests",
    "you have exceeded",
    "abuse detection",
)


# ── helpers ────────────────────────────────────────────────────────────────────

def is_rate_limited(stderr: str) -> bool:
    """Return True if *stderr* text looks like a GitHub rate-limit response."""
    lower = stderr.lower()
    return any(signal in lower for signal in RATE_LIMIT_SIGNALS)


# ── public API ─────────────────────────────────────────────────────────────────

def run_with_retry(
    cmd: list,
    timeout: int = 60,
    max_retries: int = MAX_RETRIES,
    initial_wait: float = INITIAL_WAIT,
    backoff_factor: float = BACKOFF_FACTOR,
    max_wait: float = MAX_WAIT,
) -> tuple[int, str, str]:
    """
    Run *cmd* as a subprocess and return ``(returncode, stdout, stderr)``.

    If the command fails with a rate-limit signal in stderr, retry up to
    *max_retries* times with exponential backoff, logging each attempt.

    Parameters
    ----------
    cmd:           Command and arguments list, passed to ``subprocess.run``.
    timeout:       Per-attempt timeout in seconds (default 60).
    max_retries:   Maximum number of retry attempts after first failure (default 5).
    initial_wait:  Seconds to wait before first retry (default 1.0).
    backoff_factor: Multiplier applied to wait after each retry (default 2.0).
    max_wait:      Ceiling on any single sleep duration in seconds (default 30.0).

    Returns
    -------
    (returncode, stdout, stderr) of the last attempt.
    """
    wait = initial_wait

    # attempt 1 is the initial try; attempts 2..max_retries+1 are retries
    for attempt in range(1, max_retries + 2):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        rc, stdout, stderr = result.returncode, result.stdout, result.stderr

        # Success or non-rate-limit failure — return immediately, no retry
        if rc == 0 or not is_rate_limited(stderr):
            return rc, stdout, stderr

        # Rate-limited.  Retry if attempts remain.
        retries_used = attempt - 1
        if retries_used < max_retries:
            sleep_for = min(wait, max_wait)
            sys.stderr.write(
                f"[api_retry] rate limit detected, retrying in {sleep_for:.0f}s "
                f"(attempt {retries_used + 1}/{max_retries})\n"
            )
            time.sleep(sleep_for)
            wait = min(wait * backoff_factor, max_wait)

    # All retries exhausted — return the last result
    return rc, stdout, stderr
