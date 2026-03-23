#!/usr/bin/env python3
"""Tests for tools/trivia.py"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Make sure we can import the module under test
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
import trivia  # noqa: E402


QUESTIONS_FILE = Path(__file__).parent.parent / "knowledge" / "trivia" / "questions.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_cli(*args: str) -> tuple[str, int]:
    """Run main() with the given args, capture stdout, return (output, code)."""
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = trivia.main(list(args))
    return buf.getvalue(), code


# ---------------------------------------------------------------------------
# Questions file
# ---------------------------------------------------------------------------

class TestQuestionsFile(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(QUESTIONS_FILE.exists(), "questions.json not found")

    def test_is_valid_json(self):
        with QUESTIONS_FILE.open() as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_at_least_50_questions(self):
        with QUESTIONS_FILE.open() as fh:
            data = json.load(fh)
        self.assertGreaterEqual(len(data), 50, "Need at least 50 questions")

    def test_all_questions_valid(self):
        with QUESTIONS_FILE.open() as fh:
            questions = json.load(fh)
        errors: list[str] = []
        for q in questions:
            qid = q.get("id", "?")
            for err in trivia.validate_question(q):
                errors.append(f"{qid}: {err}")
        self.assertEqual(errors, [], f"Validation errors:\n" + "\n".join(errors))

    def test_unique_ids(self):
        with QUESTIONS_FILE.open() as fh:
            questions = json.load(fh)
        ids = [q.get("id") for q in questions]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate question IDs found")

    def test_all_difficulties_present(self):
        with QUESTIONS_FILE.open() as fh:
            questions = json.load(fh)
        diffs = {q.get("difficulty") for q in questions}
        self.assertIn("easy", diffs)
        self.assertIn("medium", diffs)
        self.assertIn("hard", diffs)

    def test_all_categories_present(self):
        with QUESTIONS_FILE.open() as fh:
            questions = json.load(fh)
        cats = {q.get("category") for q in questions}
        self.assertIn("seasons", cats)
        self.assertIn("hermits", cats)
        self.assertIn("lore", cats)

    def test_every_answer_in_options(self):
        with QUESTIONS_FILE.open() as fh:
            questions = json.load(fh)
        for q in questions:
            self.assertIn(
                q["answer"],
                q["options"],
                f"Question {q['id']}: answer '{q['answer']}' not in options",
            )

    def test_exactly_4_options_per_question(self):
        with QUESTIONS_FILE.open() as fh:
            questions = json.load(fh)
        for q in questions:
            self.assertEqual(
                len(q["options"]),
                4,
                f"Question {q['id']}: expected 4 options, got {len(q['options'])}",
            )

    def test_source_field_populated(self):
        with QUESTIONS_FILE.open() as fh:
            questions = json.load(fh)
        for q in questions:
            self.assertTrue(
                q.get("source"), f"Question {q['id']}: empty source field"
            )


# ---------------------------------------------------------------------------
# filter_questions
# ---------------------------------------------------------------------------

class TestFilterQuestions(unittest.TestCase):
    def setUp(self):
        self.questions = trivia.load_questions()

    def test_no_filter_returns_all(self):
        result = trivia.filter_questions(self.questions)
        self.assertEqual(len(result), len(self.questions))

    def test_filter_easy(self):
        result = trivia.filter_questions(self.questions, difficulty="easy")
        self.assertTrue(all(q["difficulty"] == "easy" for q in result))
        self.assertGreater(len(result), 0)

    def test_filter_medium(self):
        result = trivia.filter_questions(self.questions, difficulty="medium")
        self.assertTrue(all(q["difficulty"] == "medium" for q in result))
        self.assertGreater(len(result), 0)

    def test_filter_hard(self):
        result = trivia.filter_questions(self.questions, difficulty="hard")
        self.assertTrue(all(q["difficulty"] == "hard" for q in result))
        self.assertGreater(len(result), 0)

    def test_filter_seasons(self):
        result = trivia.filter_questions(self.questions, category="seasons")
        self.assertTrue(all(q["category"] == "seasons" for q in result))
        self.assertGreater(len(result), 0)

    def test_filter_hermits(self):
        result = trivia.filter_questions(self.questions, category="hermits")
        self.assertTrue(all(q["category"] == "hermits" for q in result))
        self.assertGreater(len(result), 0)

    def test_filter_lore(self):
        result = trivia.filter_questions(self.questions, category="lore")
        self.assertTrue(all(q["category"] == "lore" for q in result))
        self.assertGreater(len(result), 0)

    def test_combined_filter(self):
        result = trivia.filter_questions(
            self.questions, difficulty="hard", category="seasons"
        )
        for q in result:
            self.assertEqual(q["difficulty"], "hard")
            self.assertEqual(q["category"], "seasons")


# ---------------------------------------------------------------------------
# validate_question
# ---------------------------------------------------------------------------

class TestValidateQuestion(unittest.TestCase):
    def _good(self):
        return {
            "id": "q001",
            "question": "Who?",
            "options": ["A", "B", "C", "D"],
            "answer": "A",
            "difficulty": "easy",
            "category": "seasons",
            "source": "knowledge/seasons/season-1.md",
        }

    def test_valid_question_no_errors(self):
        self.assertEqual(trivia.validate_question(self._good()), [])

    def test_missing_field(self):
        q = self._good()
        del q["answer"]
        errors = trivia.validate_question(q)
        self.assertTrue(any("answer" in e for e in errors))

    def test_answer_not_in_options(self):
        q = self._good()
        q["answer"] = "Z"
        errors = trivia.validate_question(q)
        self.assertTrue(any("not found in options" in e for e in errors))

    def test_invalid_difficulty(self):
        q = self._good()
        q["difficulty"] = "impossible"
        errors = trivia.validate_question(q)
        self.assertTrue(any("difficulty" in e for e in errors))

    def test_invalid_category(self):
        q = self._good()
        q["category"] = "minecraft"
        errors = trivia.validate_question(q)
        self.assertTrue(any("category" in e for e in errors))


# ---------------------------------------------------------------------------
# CLI behaviour
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):
    def test_default_returns_one_question_json(self):
        out, code = run_cli("--seed", "42")
        self.assertEqual(code, 0)
        obj = json.loads(out)
        self.assertIn("question", obj)
        self.assertIn("answer", obj)
        self.assertIn("options", obj)

    def test_count_returns_list(self):
        out, code = run_cli("--count", "3", "--seed", "42")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 3)

    def test_count_1_returns_object_not_list(self):
        out, code = run_cli("--count", "1", "--seed", "0")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIsInstance(data, dict)

    def test_difficulty_filter(self):
        out, code = run_cli("--difficulty", "easy", "--all")
        self.assertEqual(code, 0)
        questions = json.loads(out)
        self.assertTrue(all(q["difficulty"] == "easy" for q in questions))

    def test_category_filter(self):
        out, code = run_cli("--category", "lore", "--all")
        self.assertEqual(code, 0)
        questions = json.loads(out)
        self.assertTrue(all(q["category"] == "lore" for q in questions))

    def test_all_flag(self):
        out, code = run_cli("--all")
        self.assertEqual(code, 0)
        questions = json.loads(out)
        self.assertIsInstance(questions, list)
        self.assertGreaterEqual(len(questions), 50)

    def test_stats_flag(self):
        out, code = run_cli("--stats")
        self.assertEqual(code, 0)
        stats = json.loads(out)
        self.assertIn("total_questions", stats)
        self.assertIn("by_difficulty", stats)
        self.assertIn("by_category", stats)
        self.assertGreaterEqual(stats["total_questions"], 50)

    def test_no_match_returns_exit_1(self):
        # Ask for questions that don't exist through patching the loader
        original_load = trivia.load_questions
        trivia.load_questions = lambda path=None: []
        try:
            import io
            from contextlib import redirect_stdout, redirect_stderr
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = trivia.main(["--difficulty", "easy"])
            self.assertEqual(code, 1)
        finally:
            trivia.load_questions = original_load

    def test_seed_produces_reproducible_output(self):
        out1, _ = run_cli("--seed", "1337", "--count", "3")
        out2, _ = run_cli("--seed", "1337", "--count", "3")
        self.assertEqual(out1, out2)

    def test_different_seeds_likely_differ(self):
        out1, _ = run_cli("--seed", "1", "--count", "5")
        out2, _ = run_cli("--seed", "999", "--count", "5")
        # With 55 questions and picking 5, different seeds very likely differ
        # (this can theoretically fail but is astronomically unlikely)
        q1 = [q["id"] for q in json.loads(out1)]
        q2 = [q["id"] for q in json.loads(out2)]
        self.assertNotEqual(q1, q2)


# ---------------------------------------------------------------------------
# Specific content sanity checks
# ---------------------------------------------------------------------------

class TestContentSanity(unittest.TestCase):
    """Spot-check that key Hermitcraft facts are correct in the question bank."""

    def setUp(self):
        with QUESTIONS_FILE.open() as fh:
            self.questions = json.load(fh)
        self.by_id = {q["id"]: q for q in self.questions}

    def test_hermitcraft_founded_by_generikb(self):
        q = self.by_id["q001"]
        self.assertEqual(q["answer"], "Generikb")

    def test_server_founded_2012(self):
        q = self.by_id["q002"]
        self.assertEqual(q["answer"], "2012")

    def test_xisuma_became_admin(self):
        q = self.by_id["q003"]
        self.assertEqual(q["answer"], "Xisumavoid")

    def test_grian_joined_season_6(self):
        q = self.by_id["q004"]
        self.assertEqual(q["answer"], "Grian")

    def test_decked_out_is_tangoteks(self):
        q = self.by_id["q005"]
        self.assertEqual(q["answer"], "Decked Out")

    def test_season_9_longest(self):
        q = self.by_id["q006"]
        self.assertEqual(q["answer"], "Season 9")

    def test_season_8_shortest(self):
        q = self.by_id["q007"]
        self.assertEqual(q["answer"], "Season 8")

    def test_iskall85_won_demise_season6(self):
        q = self.by_id["q011"]
        self.assertEqual(q["answer"], "Iskall85")

    def test_false_symmetry_won_demise_season10(self):
        q = self.by_id["q012"]
        self.assertEqual(q["answer"], "FalseSymmetry")

    def test_mycelium_resistance_won_6_3(self):
        q = self.by_id["q017"]
        self.assertEqual(q["answer"], "6-3")

    def test_sahara_profit_5_diamond_blocks(self):
        q = self.by_id["q018"]
        self.assertEqual(q["answer"], "5 diamond blocks")

    def test_grian_real_name(self):
        q = self.by_id["q033"]
        self.assertEqual(q["answer"], "Charles Batchelor")

    def test_mumbo_real_name(self):
        q = self.by_id["q034"]
        self.assertEqual(q["answer"], "Oliver Brotherhood")


if __name__ == "__main__":
    unittest.main()
