#!/usr/bin/env python3
"""
Hermitcraft Trivia Quiz CLI
============================
Serves trivia questions drawn from the knowledge base.

Usage
-----
  python3 tools/trivia.py                         # one random question
  python3 tools/trivia.py --count 5               # 5 random questions
  python3 tools/trivia.py --difficulty easy        # filter by difficulty
  python3 tools/trivia.py --category seasons       # filter by category
  python3 tools/trivia.py --difficulty hard --count 3
  python3 tools/trivia.py --all                    # all questions
  python3 tools/trivia.py --stats                  # summary stats only

Output is always newline-delimited JSON (one object per line), or a single
JSON array when --all is used, so it's easy to pipe into jq.

Exit codes
----------
  0  success
  1  no questions match the given filters
  2  bad arguments or questions file not found
"""

import argparse
import json
import os
import random
import sys
from pathlib import Path

QUESTIONS_FILE = Path(__file__).parent.parent / "knowledge" / "trivia" / "questions.json"

VALID_DIFFICULTIES = {"easy", "medium", "hard"}
VALID_CATEGORIES = {"seasons", "hermits", "lore"}


def load_questions(path: Path = QUESTIONS_FILE) -> list[dict]:
    """Load and validate the questions JSON file."""
    if not path.exists():
        sys.stderr.write(f"[trivia] questions file not found: {path}\n")
        sys.exit(2)
    try:
        with path.open() as fh:
            questions = json.load(fh)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"[trivia] malformed JSON in {path}: {exc}\n")
        sys.exit(2)
    if not isinstance(questions, list):
        sys.stderr.write(f"[trivia] questions file must be a JSON array\n")
        sys.exit(2)
    return questions


def filter_questions(
    questions: list[dict],
    difficulty: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Return questions matching the given filters (None = no filter)."""
    result = questions
    if difficulty:
        result = [q for q in result if q.get("difficulty") == difficulty]
    if category:
        result = [q for q in result if q.get("category") == category]
    return result


def validate_question(q: dict) -> list[str]:
    """Return a list of validation errors for a single question dict."""
    errors: list[str] = []
    required = ("id", "question", "options", "answer", "difficulty", "category", "source")
    for field in required:
        if field not in q:
            errors.append(f"missing field '{field}'")
    if "options" in q and not isinstance(q["options"], list):
        errors.append("'options' must be an array")
    if "options" in q and "answer" in q and q["answer"] not in q["options"]:
        errors.append(
            f"answer '{q['answer']}' not found in options {q['options']}"
        )
    if "difficulty" in q and q["difficulty"] not in VALID_DIFFICULTIES:
        errors.append(f"difficulty must be one of {sorted(VALID_DIFFICULTIES)}")
    if "category" in q and q["category"] not in VALID_CATEGORIES:
        errors.append(f"category must be one of {sorted(VALID_CATEGORIES)}")
    return errors


def print_stats(questions: list[dict]) -> None:
    """Print a human-readable summary to stdout."""
    total = len(questions)
    by_diff: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    for q in questions:
        d = q.get("difficulty", "unknown")
        c = q.get("category", "unknown")
        by_diff[d] = by_diff.get(d, 0) + 1
        by_cat[c] = by_cat.get(c, 0) + 1
    stats = {
        "total_questions": total,
        "by_difficulty": by_diff,
        "by_category": by_cat,
    }
    print(json.dumps(stats, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hermitcraft Trivia Quiz CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--difficulty",
        choices=sorted(VALID_DIFFICULTIES),
        help="Filter by difficulty level",
    )
    parser.add_argument(
        "--category",
        choices=sorted(VALID_CATEGORIES),
        help="Filter by category",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        metavar="N",
        help="Number of questions to return (default: 1)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_questions",
        help="Return all matching questions as a JSON array",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print question bank stats and exit",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Random seed (for reproducible output in tests)",
    )

    args = parser.parse_args(argv)

    questions = load_questions()

    if args.stats:
        print_stats(questions)
        return 0

    filtered = filter_questions(questions, args.difficulty, args.category)

    if not filtered:
        sys.stderr.write(
            f"[trivia] no questions match filters "
            f"(difficulty={args.difficulty!r}, category={args.category!r})\n"
        )
        return 1

    if args.all_questions:
        print(json.dumps(filtered, indent=2))
        return 0

    rng = random.Random(args.seed)
    count = min(args.count, len(filtered))
    selected = rng.sample(filtered, count)

    if count == 1:
        print(json.dumps(selected[0], indent=2))
    else:
        print(json.dumps(selected, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
