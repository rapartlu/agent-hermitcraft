"""
tag_task_result.py — Stop hook for hermitcraft-agent

Runs automatically when Claude stops (via the Stop hook in
.claude/settings.json).  Reads the session transcript, scans the last
assistant message for infrastructure blocker signals, and writes a
structured metadata file (.task_result_meta.json) that the orchestrator
verifier reads *before* scoring.

This means the verifier never has to call a separate tool: the tagging
happens automatically as part of every task completion.

Metadata file written: <cwd>/.task_result_meta.json

Hook input (stdin): JSON with keys
    session_id      — Claude session identifier
    transcript_path — absolute path to the JSONL transcript
    cwd             — working directory (= repo root)

Exit codes:
    0  — always (hook failures must not block Claude from stopping)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow import from repo root whether the hook is called from tools/ or root.
_repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root))

from tools.rejection_classifier import INFRA_PATTERNS  # noqa: E402
import re

METADATA_FILENAME = ".task_result_meta.json"

# Words that indicate the agent explicitly flagged a blocker in its output
# (strengthens confidence that the agent noticed the failure).
EXPLICIT_FLAG_PATTERNS = [
    r"gh[_ ]cli.{0,30}(not authenticated|missing|unavailable)",
    r"(github|gh)[_ ]token.{0,30}(not set|missing|empty|unavailable)",
    r"cannot (push|create pr|open pr)",
    r"blocked by.{0,30}(infra|environment|token|credential)",
    r"infrastructure.{0,30}(blocker|issue|problem)",
    r"(push|pr creation).{0,30}failed.{0,30}(token|auth|credential)",
]


def read_last_assistant_message(transcript_path: str) -> str:
    """
    Read the JSONL transcript and return the text of the last assistant message.
    Returns empty string if the transcript cannot be read.
    """
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
        last_assistant = ""
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Transcript entries have type="assistant" with content blocks
            if entry.get("type") == "assistant":
                content = entry.get("message", {}).get("content", "")
                if isinstance(content, list):
                    text_parts = [
                        c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    ]
                    last_assistant = " ".join(text_parts)
                elif isinstance(content, str):
                    last_assistant = content
        return last_assistant
    except Exception:
        return ""


def detect_blocker(text: str) -> dict:
    """
    Returns blocker info dict:
        {"detected": bool, "signal": str|None, "explicitly_flagged": bool}
    """
    lower = text.lower()
    matched_signal = None
    for pattern in INFRA_PATTERNS:
        if re.search(pattern, lower):
            matched_signal = pattern
            break

    explicitly_flagged = False
    if matched_signal:
        for flag_pattern in EXPLICIT_FLAG_PATTERNS:
            if re.search(flag_pattern, lower):
                explicitly_flagged = True
                break

    return {
        "detected": matched_signal is not None,
        "signal": matched_signal,
        "explicitly_flagged": explicitly_flagged,
    }


def build_metadata(session_id: str, blocker: dict, cwd: str) -> dict:
    """Build the metadata dict to write to .task_result_meta.json."""
    meta = {
        "schema_version": 1,
        "session_id": session_id,
        "cwd": cwd,
        "tagged_at": datetime.now(timezone.utc).isoformat(),
        "infrastructure_blocked": blocker["detected"],
    }
    if blocker["detected"]:
        meta.update({
            "blocker_signal": blocker["signal"],
            "agent_explicitly_flagged_blocker": blocker["explicitly_flagged"],
            # Fraction of the task score attributable to infra steps (push, PR
            # creation).  Verifier should not penalise this portion.
            "infra_score_weight": 0.25,
            "verifier_instruction": (
                "Infrastructure blocker detected. Score only the agent-controlled "
                "portion of the work (correctness, completeness, format, commits). "
                "Do not penalise for failed push or missing PR. "
                "Set verification_status='blocked', not 'rejected'. "
                "Do not re-dispatch agent — fix infra first."
            ),
        })
    else:
        meta["verifier_instruction"] = "No infrastructure blocker detected. Score normally."
    return meta


def main():
    try:
        raw = sys.stdin.read().strip()
        event = json.loads(raw) if raw else {}

        session_id = event.get("session_id", "unknown")
        transcript_path = event.get("transcript_path", "")
        cwd = event.get("cwd", str(_repo_root))

        last_message = read_last_assistant_message(transcript_path) if transcript_path else ""
        blocker = detect_blocker(last_message)
        metadata = build_metadata(session_id, blocker, cwd)

        out_path = Path(cwd) / METADATA_FILENAME
        out_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    except Exception:
        # Hooks must not crash Claude — swallow all errors silently.
        pass

    sys.exit(0)  # Always exit 0


if __name__ == "__main__":
    main()
