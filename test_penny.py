import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest


@pytest.fixture(autouse=True)
def penny_dir(monkeypatch):
    """Point util.PENNY_DIR at a temp dir for every test and reload modules."""
    tmp = tempfile.mkdtemp()
    monkeypatch.setattr("util.PENNY_DIR", tmp)
    # Re-import all project modules so they pick up the patched PENNY_DIR
    # Don't delete "util" -- it holds the monkeypatched PENNY_DIR
    for mod in list(sys.modules.keys()):
        if mod in ("costs", "cli", "hook", "heuristics", "learner", "preference"):
            del sys.modules[mod]
    yield tmp
    shutil.rmtree(tmp)


def write_sessions(sessions: List[Dict]) -> None:
    import util
    util.write_json(os.path.join(util.PENNY_DIR, "sessions.json"), sessions)


def make_session(days_ago: int = 0, model_tier: str = "standard", dominant_tier: str = "basic",
                 cost: float = 100, savings: float = 50, turn_count: int = 5, char_count: int = 200) -> Dict:
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
    return {
        "timestamp": ts,
        "model": "claude-sonnet-5",
        "model_tier": model_tier,
        "dominant_tier": dominant_tier,
        "estimated_cost_cents": cost,
        "potential_savings_cents": savings,
        "char_count": char_count,
        "turn_count": turn_count,
        "auto_switched": False,
        "nudge_accepted": None,
    }


class TestWeeklyStats:
    def test_empty_sessions(self):
        from cli import weekly_stats
        stats = weekly_stats()
        assert stats["spent_cents"] == 0
        assert stats["could_save_cents"] == 0
        assert stats["session_count"] == 0
        assert stats["flagged_count"] == 0

    def test_mixed_sessions(self):
        sessions = [
            make_session(days_ago=0, model_tier="advanced", dominant_tier="basic", cost=200, savings=150),
            make_session(days_ago=0, model_tier="standard", dominant_tier="standard", cost=50, savings=0),
            make_session(days_ago=0, model_tier="advanced", dominant_tier="basic", cost=300, savings=250),
        ]
        write_sessions(sessions)
        from cli import weekly_stats
        stats = weekly_stats()
        assert stats["session_count"] == 3
        assert stats["spent_cents"] == 550
        assert stats["could_save_cents"] == 400
        assert stats["flagged_count"] == 2

    def test_old_sessions_excluded(self):
        sessions = [
            make_session(days_ago=10, model_tier="advanced", dominant_tier="basic", cost=500, savings=400),
        ]
        write_sessions(sessions)
        from cli import weekly_stats
        stats = weekly_stats()
        assert stats["session_count"] == 0


class TestCosts:
    def test_format_dollars(self):
        from costs import format_dollars
        assert format_dollars(0) == "$0.00"
        assert format_dollars(100) == "$1.00"
        assert format_dollars(1049) == "$10.49"
        assert format_dollars(1) == "$0.01"

    def test_estimate_cost_cents(self):
        from costs import estimate_cost_cents
        cost = estimate_cost_cents(4000, "claude-sonnet-5")
        assert cost > 0

    def test_estimate_cost_unknown_model_falls_back(self):
        from costs import estimate_cost_cents
        cost = estimate_cost_cents(4000, "unknown-model")
        assert cost > 0

    def test_savings_cents(self):
        from costs import savings_cents
        savings = savings_cents(10000, "claude-opus-4-8", "claude-haiku-4-5")
        assert savings > 0

    def test_savings_cents_cheaper_to_expensive(self):
        from costs import savings_cents
        savings = savings_cents(10000, "claude-haiku-4-5", "claude-opus-4-8")
        assert savings < 0


class TestHeuristics:
    def test_classify_basic(self):
        from heuristics import classify_prompt
        assert classify_prompt("fix typo in README") == "basic"
        assert classify_prompt("rename userID to userId") == "basic"
        assert classify_prompt("add a docstring") == "basic"
        assert classify_prompt("format this JSON") == "basic"

    def test_classify_standard(self):
        from heuristics import classify_prompt
        assert classify_prompt("write a function that parses CSV") == "standard"
        assert classify_prompt("add error handling to this endpoint") == "standard"
        assert classify_prompt("help me implement pagination") == "standard"

    def test_classify_advanced(self):
        from heuristics import classify_prompt
        assert classify_prompt("refactor the entire auth system") == "advanced"
        assert classify_prompt("debug why this crashes in production") == "advanced"
        assert classify_prompt("audit my security setup") == "advanced"

    def test_classify_negation(self):
        from heuristics import classify_prompt
        assert classify_prompt("should I refactor this variable") == "standard"
        assert classify_prompt("do I need to migrate this code") == "standard"

    def test_model_tier(self):
        from heuristics import model_tier
        assert model_tier("claude-haiku-4-5") == "basic"
        assert model_tier("claude-sonnet-5") == "standard"
        assert model_tier("claude-opus-4-8") == "advanced"
        assert model_tier("unknown") == "standard"

    def test_normalize_model(self):
        from heuristics import normalize_model
        assert normalize_model("haiku") == "claude-haiku-4-5"
        assert normalize_model("sonnet") == "claude-sonnet-5"
        assert normalize_model("opus") == "claude-opus-4-8"
        assert normalize_model("claude-sonnet-5") == "claude-sonnet-5"


class TestSetDefault:
    def test_not_enough_data(self):
        write_sessions([])
        from cli import perform_set_default
        result = perform_set_default()
        assert result["ok"] is False
        assert "usage data" in result["reason"]

    def test_sessions_all_same_dominant_tier(self):
        sessions = [make_session(days_ago=i, dominant_tier="basic") for i in range(10)]
        write_sessions(sessions)
        from cli import perform_set_default
        result = perform_set_default()
        assert result["ok"] is True
        assert result["tier"] == "basic"

    def test_majority_dominant_tier_wins(self):
        sessions = [make_session(days_ago=i, dominant_tier="standard") for i in range(8)]
        sessions.append(make_session(days_ago=8, dominant_tier="advanced"))
        write_sessions(sessions)
        from cli import perform_set_default
        result = perform_set_default()
        assert result["ok"] is True
        assert result["tier"] == "standard"


class TestPauseResume:
    def test_pause_and_resume(self):
        from cli import cmd_pause, cmd_resume
        import util
        prefs_path = os.path.join(util.PENNY_DIR, "prefs.json")
        cmd_pause()
        prefs = util.load_json(prefs_path, {})
        assert prefs.get("paused") is True
        cmd_resume()
        prefs = util.load_json(prefs_path, {})
        assert prefs.get("paused") is False


class TestCheckCap:
    def test_ok_when_not_paused_or_capped(self, capsys):
        from cli import cmd_check_cap
        today = datetime.now().strftime("%Y-%m-%d")
        cmd_check_cap(today)
        captured = capsys.readouterr()
        assert "ok" in captured.out

    def test_paused_returns_paused(self, capsys):
        import util
        util.write_json(os.path.join(util.PENNY_DIR, "prefs.json"), {"paused": True})
        from cli import cmd_check_cap
        today = datetime.now().strftime("%Y-%m-%d")
        cmd_check_cap(today)
        captured = capsys.readouterr()
        assert "paused" in captured.out

    def test_capped_after_three(self, capsys):
        import util
        today = datetime.now().strftime("%Y-%m-%d")
        util.write_json(os.path.join(util.PENNY_DIR, "prefs.json"),
                        {"daily_nudge_count": 3, "last_nudge_date": today})
        from cli import cmd_check_cap
        cmd_check_cap(today)
        captured = capsys.readouterr()
        assert "capped" in captured.out

    def test_resets_count_on_new_day(self, capsys):
        import util
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        util.write_json(os.path.join(util.PENNY_DIR, "prefs.json"),
                        {"daily_nudge_count": 3, "last_nudge_date": yesterday})
        from cli import cmd_check_cap
        today = datetime.now().strftime("%Y-%m-%d")
        cmd_check_cap(today)
        captured = capsys.readouterr()
        assert "ok" in captured.out


class TestCheckTip:
    def test_no_tip_when_not_suggested(self, capsys):
        from cli import cmd_check_tip
        today = datetime.now().strftime("%Y-%m-%d")
        cmd_check_tip(today)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_tip_when_suggested(self, capsys):
        import util
        util.write_json(os.path.join(util.PENNY_DIR, "prefs.json"), {"suggested_default_switch": True})
        sessions = [make_session(days_ago=0, savings=100)]
        write_sessions(sessions)
        from cli import cmd_check_tip
        today = datetime.now().strftime("%Y-%m-%d")
        cmd_check_tip(today)
        captured = capsys.readouterr()
        assert "$" in captured.out

    def test_tip_only_once_per_day(self, capsys):
        import util
        util.write_json(os.path.join(util.PENNY_DIR, "prefs.json"),
                        {"suggested_default_switch": True,
                         "tip_last_shown_date": datetime.now().strftime("%Y-%m-%d")})
        from cli import cmd_check_tip
        today = datetime.now().strftime("%Y-%m-%d")
        cmd_check_tip(today)
        captured = capsys.readouterr()
        assert captured.out == ""


class TestAtomicWrite:
    def test_write_and_read(self):
        from util import write_json, load_json
        path = os.path.join(tempfile.mkdtemp(), "test_atomic.json")
        data = {"hello": "world", "nested": [1, 2, 3]}
        write_json(path, data)
        result = load_json(path)
        assert result == data

    def test_load_missing_file(self):
        from util import load_json
        result = load_json("/nonexistent/path.json", {"default": True})
        assert result == {"default": True}


class TestHealthCommand:
    def test_health_output(self, capsys):
        from cli import cmd_health
        cmd_health()
        captured = capsys.readouterr()
        assert "Penny Health" in captured.out
        assert "No recent errors" in captured.out
        assert "Hook" in captured.out

    def test_health_stale_hook(self, capsys):
        """Warning when no recent sessions found."""
        sessions = [make_session(days_ago=30, dominant_tier="basic")]
        write_sessions(sessions)
        from cli import cmd_health
        cmd_health()
        captured = capsys.readouterr()
        assert "hook may not be firing" in captured.out


class TestLearner:
    def test_predict_falls_back_without_data(self):
        from learner import predict
        tier, conf = predict("fix typo in README")
        assert tier == "heuristics"
        assert conf == 0.0

    def test_save_and_load_feedback(self):
        from learner import save_feedback, load_feedback
        save_feedback("test prompt", "standard", "basic")
        save_feedback("another prompt", "standard", "advanced")
        entries = load_feedback()
        assert len(entries) == 2
        assert entries[0]["prompt"] == "test prompt"
        assert entries[0]["corrected_tier"] == "basic"

    def test_train_after_enough_feedback(self, monkeypatch):
        import learner
        from learner import save_feedback, predict, MIN_FEEDBACK_FOR_TRAIN
        monkeypatch.setattr(learner, "MIN_FEEDBACK_FOR_TRAIN", 5)
        for i in range(5):
            save_feedback(f"fix typo number {i}", "standard", "basic")
        for i in range(5):
            save_feedback(f"refactor the entire system {i}", "standard", "advanced")
        tier, conf = predict("fix typo in the docs")
        assert tier in ("basic", "advanced")
        assert conf > 0

    def test_feedback_persists_across_calls(self):
        from learner import save_feedback, load_feedback
        before = len(load_feedback())
        save_feedback("unique test", "standard", "standard")
        after = len(load_feedback())
        assert after == before + 1


class TestPreference:
    def test_default_acceptance_rate(self):
        from preference import acceptance_rate
        assert acceptance_rate() == 1.0

    def test_record_switch(self):
        from preference import record_switch, acceptance_rate
        record_switch(True, True)
        record_switch(True, True)
        record_switch(True, False)
        rate = acceptance_rate()
        assert 0.5 < rate <= 1.0

    def test_record_switch_none_does_not_count(self):
        """Regression: a switch with unknown acceptance must not be tallied,
        otherwise acceptance rate is pinned at 100% and conservative mode
        can never trigger."""
        import util
        from preference import record_switch, acceptance_rate
        record_switch(True, None)  # was a switch, outcome unknown
        assert acceptance_rate() == 1.0
        prefs = util.load_json(os.path.join(util.PENNY_DIR, "prefs.json"), {})
        assert prefs.get("auto_switch_total", 0) == 0

    def test_record_switch_false_lowers_rate(self):
        from preference import record_switch, acceptance_rate
        record_switch(True, True)
        record_switch(True, False)
        assert acceptance_rate() == 0.5

    def test_should_switch_conservatively(self):
        from preference import record_switch, should_switch_conservatively
        for _ in range(6):
            record_switch(True, False)
        assert should_switch_conservatively() is True

    def test_should_switch_not_conservative_with_none_only(self):
        from preference import record_switch, should_switch_conservatively
        for _ in range(6):
            record_switch(True, None)
        # None outcomes aren't counted, so total stays 0 → not conservative
        assert should_switch_conservatively() is False


class TestLearnerConfidence:
    def test_confidence_high_when_separated(self, monkeypatch):
        import learner
        from learner import save_feedback, predict, MIN_FEEDBACK_FOR_TRAIN
        monkeypatch.setattr(learner, "MIN_FEEDBACK_FOR_TRAIN", 10)
        # Plenty of separated training data so the model can be confident
        for i in range(10):
            save_feedback(f"fix typo number {i} in the readme", "standard", "basic")
        for i in range(10):
            save_feedback(f"refactor the entire system {i} architecture", "standard", "advanced")
        tier, conf = predict("fix typo in the docs")
        assert tier == "basic"
        assert conf >= 0.6

    def test_confidence_low_with_little_data(self, monkeypatch):
        """With only a few examples, the model should stay humble and defer
        to heuristics rather than override with a wild guess."""
        import learner
        from learner import save_feedback, predict, MIN_FEEDBACK_FOR_TRAIN
        monkeypatch.setattr(learner, "MIN_FEEDBACK_FOR_TRAIN", 4)
        for i in range(4):
            save_feedback(f"fix typo number {i}", "standard", "basic")
        for i in range(4):
            save_feedback(f"refactor the entire system {i}", "standard", "advanced")
        tier, conf = predict("fix typo in the docs")
        assert tier == "heuristics"
        assert 0.0 <= conf < 0.6

    def test_confidence_in_range(self, monkeypatch):
        import learner
        from learner import save_feedback, predict, MIN_FEEDBACK_FOR_TRAIN
        monkeypatch.setattr(learner, "MIN_FEEDBACK_FOR_TRAIN", 4)
        for i in range(4):
            save_feedback(f"fix typo number {i}", "standard", "basic")
        for i in range(4):
            save_feedback(f"refactor the entire system {i}", "standard", "advanced")
        tier, conf = predict("fix typo in the docs")
        assert 0.0 <= conf <= 1.0


class TestCheckPreference:
    def test_check_preference_default(self, capsys):
        from cli import cmd_check_preference
        cmd_check_preference()
        captured = capsys.readouterr()
        assert "normal" in captured.out

    def test_check_preference_conservative(self, capsys):
        from preference import record_switch
        for _ in range(6):
            record_switch(True, False)
        from cli import cmd_check_preference
        cmd_check_preference()
        captured = capsys.readouterr()
        assert "conservative" in captured.out


class TestUtil:
    def test_load_json_default_on_missing(self):
        from util import load_json
        assert load_json("/dev/null/nope", 42) == 42

    def test_write_json_creates_dirs(self):
        from util import write_json, load_json
        path = os.path.join(tempfile.mkdtemp(), "sub", "file.json")
        write_json(path, {"a": 1})
        assert load_json(path) == {"a": 1}
