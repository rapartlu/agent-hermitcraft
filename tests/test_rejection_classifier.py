"""
Tests for tools/rejection_classifier.py
Run with: python -m pytest tests/test_rejection_classifier.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.rejection_classifier import classify, build_routing_message


class TestClassifyInfrastructureBlocked:
    def test_gh_not_authenticated(self):
        result = classify(0.35, "gh CLI not authenticated")
        assert result["classification"] == "infrastructure-blocked"
        assert result["confidence"] >= 0.8

    def test_github_token_missing(self):
        result = classify(0.45, "GITHUB_TOKEN not set in container env")
        assert result["classification"] == "infrastructure-blocked"

    def test_permission_denied(self):
        result = classify(0.40, "Permission denied when writing to /etc/config")
        assert result["classification"] == "infrastructure-blocked"

    def test_command_not_found(self):
        result = classify(0.30, "bash: gh: command not found")
        assert result["classification"] == "infrastructure-blocked"

    def test_network_timeout(self):
        result = classify(0.20, "Network timeout connecting to api.github.com")
        assert result["classification"] == "infrastructure-blocked"

    def test_rate_limit(self):
        result = classify(0.50, "GitHub API rate limit exceeded")
        assert result["classification"] == "infrastructure-blocked"

    def test_matched_pattern_populated(self):
        result = classify(0.35, "gh CLI not authenticated")
        assert result["matched_pattern"] is not None


class TestClassifyFixable:
    def test_wrong_facts(self):
        result = classify(0.45, "TinfoilChef incorrectly listed as Season 10 member")
        assert result["classification"] == "fixable"

    def test_missing_section(self):
        result = classify(0.40, "Season 7 file missing notable builds section")
        assert result["classification"] == "fixable"

    def test_yaml_invalid(self):
        result = classify(0.60, "YAML frontmatter parse error in hermit profile")
        assert result["classification"] == "fixable"

    def test_incomplete_work(self):
        result = classify(0.35, "Only 3 of 10 hermit profiles were written")
        assert result["classification"] == "fixable"

    def test_matched_pattern_none(self):
        result = classify(0.45, "Incorrect season end date for Season 6")
        assert result["matched_pattern"] is None

    def test_low_score_higher_confidence(self):
        low = classify(0.35, "Wrong information in profile")
        high = classify(0.60, "Wrong information in profile")
        assert low["confidence"] >= high["confidence"]


class TestBuildRoutingMessage:
    def test_infra_message_contains_blocked(self):
        msg = build_routing_message("01KMC05Z", 0.35, "gh CLI not authenticated")
        assert "INFRASTRUCTURE-BLOCKED" in msg

    def test_fixable_message_contains_fixable(self):
        msg = build_routing_message("01KMC04C", 0.45, "Missing season 7 data")
        assert "FIXABLE" in msg

    def test_message_contains_task_id(self):
        msg = build_routing_message("01KMC05Z", 0.35, "gh CLI not authenticated")
        assert "01KMC05Z" in msg

    def test_message_contains_score(self):
        msg = build_routing_message("01KMC05Z", 0.35, "gh CLI not authenticated")
        assert "0.35" in msg
