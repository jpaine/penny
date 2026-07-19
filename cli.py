import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import costs
import heuristics
import learner
import preference
import util


def _sessions_path() -> str:
    return os.path.join(util.PENNY_DIR, "sessions.json")


def _prefs_path() -> str:
    return os.path.join(util.PENNY_DIR, "prefs.json")


def _backup_path() -> str:
    return os.path.join(util.PENNY_DIR, "settings.backup.json")


SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")


def _ts_from(s: Dict) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s["timestamp"])
    except (KeyError, ValueError):
        return None


def week_key(dt: datetime) -> str:
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week}"


def week_key_from(s: Dict) -> Optional[str]:
    ts = _ts_from(s)
    return week_key(ts) if ts else None


def sessions_this_week(sessions: List[Dict]) -> List[Dict]:
    current_week = week_key(datetime.now())
    return [s for s in sessions if week_key_from(s) == current_week]


def weekly_stats() -> Dict[str, Any]:
    sessions: List[Dict] = util.load_json(_sessions_path(), [])
    week_sessions = sessions_this_week(sessions)

    spent_cents = sum(s.get("estimated_cost_cents", 0) for s in week_sessions)
    could_save_cents = sum(s.get("potential_savings_cents", 0) for s in week_sessions)
    flagged_count = sum(
        1 for s in week_sessions
        if heuristics.TIER_RANK.get(s.get("model_tier"), 1) > heuristics.TIER_RANK.get(s.get("dominant_tier"), 1)
    )

    return {
        "spent_cents": spent_cents,
        "could_save_cents": could_save_cents,
        "session_count": len(week_sessions),
        "flagged_count": flagged_count,
        "sessions": week_sessions,
    }


def cmd_stats() -> None:
    stats = weekly_stats()
    spent = costs.format_dollars(stats["spent_cents"])
    could_save = costs.format_dollars(stats["could_save_cents"])
    pct = round((stats["could_save_cents"] / stats["spent_cents"]) * 100) if stats["spent_cents"] > 0 else 0

    print("This week with Claude Code\n")
    print(f"Spent:        {spent}")
    print(f"Could save:   {could_save}  ({pct}%)")
    print(f"Sessions:     {stats['session_count']}  ({stats['flagged_count']} flagged)")
    print()

    if stats["flagged_count"] >= 3:
        print("Most of your sessions were simple tasks running")
        print("on a more powerful mode than needed.\n")
        print(f"-> Run this command to save ~{could_save}/week automatically:\n")
        print("   penny set-default\n")
    elif stats["spent_cents"] > 2000:
        print("Consider switching your default model to save more.\n")
    else:
        print("You're already being efficient. Nice.\n")


def determine_recommended_model(sessions: List[Dict]) -> Tuple[Optional[str], float]:
    if not sessions:
        return None, 0.0

    tiers = [s.get("dominant_tier") for s in sessions if s.get("dominant_tier")]
    if not tiers:
        return None, 0.0

    counts = Counter(tiers)
    tier, count = counts.most_common(1)[0]
    fraction = count / len(tiers)
    threshold = costs.config("default_tier_majority_threshold", 0.6)
    if fraction <= threshold:
        return None, 0.0

    model = heuristics.TIER_TO_MODEL.get(tier)
    return model, fraction


def average_weekly_savings_cents(sessions: List[Dict]) -> float:
    if not sessions:
        return 0.0

    weeks: set = set()
    total_cents = 0.0
    for s in sessions:
        wk = week_key_from(s)
        if wk is None:
            continue
        weeks.add(wk)
        total_cents += s.get("potential_savings_cents", 0)

    if not weeks:
        return 0.0
    return total_cents / len(weeks)


def perform_set_default() -> Dict[str, Any]:
    sessions: List[Dict] = util.load_json(_sessions_path(), [])
    recommended_model, _fraction = determine_recommended_model(sessions)

    if not recommended_model:
        return {"ok": False, "reason": "Not enough usage data yet to recommend a default model."}

    settings = util.load_json(SETTINGS_PATH, {})
    util.write_json(_backup_path(), settings)

    settings["model"] = recommended_model
    util.write_json(SETTINGS_PATH, settings)

    prefs: Dict = util.load_json(_prefs_path(), {})
    prefs["suggested_default_switch"] = False
    util.write_json(_prefs_path(), prefs)

    return {
        "ok": True,
        "model": recommended_model,
        "tier": heuristics.model_tier(recommended_model),
        "save_cents": average_weekly_savings_cents(sessions),
    }


def cmd_set_default() -> None:
    result = perform_set_default()

    if not result["ok"]:
        print(result["reason"])
        print("Keep using Claude Code and check back later.")
        return

    could_save = costs.format_dollars(result["save_cents"])
    print(f"✓ Default model updated to {result['tier']} mode")
    print(f"  Estimated savings: ~{could_save}/week based on your recent usage")
    print("  To undo: penny set-default --restore")


def cmd_restore() -> None:
    backup = util.load_json(_backup_path(), None)
    if backup is None:
        print("No backup found -- nothing to restore.")
        return

    util.write_json(SETTINGS_PATH, backup)
    print("✓ Restored your previous Claude Code settings.")


def cmd_pause() -> None:
    prefs: Dict = util.load_json(_prefs_path(), {})
    prefs["paused"] = True
    util.write_json(_prefs_path(), prefs)
    print("Penny nudges paused. Run 'penny resume' to turn them back on.")


def cmd_resume() -> None:
    prefs: Dict = util.load_json(_prefs_path(), {})
    prefs["paused"] = False
    util.write_json(_prefs_path(), prefs)
    print("Penny nudges resumed.")


def cmd_check_cap(today: str) -> None:
    prefs: Dict = util.load_json(_prefs_path(), {})

    if prefs.get("paused"):
        print("paused")
        return

    last_date = prefs.get("last_nudge_date")
    count = prefs.get("daily_nudge_count", 0)
    if last_date != today:
        count = 0

    if count >= 3:
        print("capped")
        return

    prefs["last_nudge_date"] = today
    prefs["daily_nudge_count"] = count + 1
    util.write_json(_prefs_path(), prefs)
    print("ok")


def cmd_check_tip(today: str) -> None:
    prefs: Dict = util.load_json(_prefs_path(), {})

    if not prefs.get("suggested_default_switch"):
        return
    if prefs.get("tip_last_shown_date") == today:
        return

    sessions: List[Dict] = util.load_json(_sessions_path(), [])
    current_week = week_key(datetime.now())
    total_cents = 0.0
    for s in sessions:
        wk = week_key_from(s)
        if wk == current_week:
            total_cents += s.get("potential_savings_cents", 0)

    prefs["suggested_default_switch"] = False
    prefs["tip_last_shown_date"] = today
    util.write_json(_prefs_path(), prefs)

    if total_cents > 0:
        print(costs.format_dollars(total_cents))


def cmd_health() -> None:
    error_log = os.path.join(util.PENNY_DIR, "error.log")
    errors = []
    try:
        with open(error_log) as f:
            errors = [line for line in f if line.strip()]
    except FileNotFoundError:
        pass

    session_count = 0
    recent_count = 0
    stale = False
    sessions = util.load_json(_sessions_path(), [])
    if isinstance(sessions, list):
        session_count = len(sessions)
        recent_count = len(sessions_this_week(sessions))
        grace_hours = float(costs.config("session_grace_period_hours", 24))
        cutoff = datetime.now() - timedelta(hours=grace_hours)
        recent_sessions = [s for s in sessions if _ts_from(s) and _ts_from(s) > cutoff]
        stale = len(recent_sessions) == 0 and session_count > 0

    pricing_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pricing.json")
    pricing_ok = os.path.exists(pricing_path)

    print("Penny Health\n")
    if errors:
        print(f"  \u26a0 Recent errors: {len(errors)} (review ~/.penny/error.log)")
    else:
        print("  \u2713 No recent errors")
    if stale:
        print(f"  \u26a0 No sessions recorded in {grace_hours}h — hook may not be firing")
    else:
        print(f"  \u2713 Hook active (last session within {grace_hours}h)")
    print(f"  \u2713 Sessions tracked: {session_count} ({recent_count} this week)")
    print(f"  \u2713 Pricing config: {'found' if pricing_ok else 'missing'}")
    print(f"  \u2713 State directory: {util.PENNY_DIR}")


def cmd_rate() -> None:
    """Rate recent classifications to train the classifier."""
    sessions = util.load_json(_sessions_path(), [])
    if not sessions:
        print("No sessions to rate yet.")
        return

    feedback_count = len(learner.load_feedback())
    print(f"Existing feedback entries: {feedback_count}\n")

    recent = sessions[-10:]
    for i, s in enumerate(recent):
        ts = _ts_from(s)
        ts_str = ts.strftime("%a %H:%M") if ts else "?"
        prompt = s.get("_sample_prompt", "")[:60]
        predicted = s.get("dominant_tier", "?")
        print(f"  [{i}] {ts_str}  {predicted:>8}  {prompt}")

    print()
    print("To rate: penny rate <index> <basic|standard|advanced>")
    print("Example: penny rate 3 basic")


def cmd_rate_session(args: List[str]) -> None:
    if len(args) < 2:
        print("Usage: penny rate-session <index> <basic|standard|advanced>")
        return
    try:
        idx = int(args[0])
        corrected = args[1].lower()
        if corrected not in ("basic", "standard", "advanced"):
            print("Tier must be: basic, standard, or advanced")
            return
    except (IndexError, ValueError):
        print("Usage: penny rate-session <index> <basic|standard|advanced>")
        return

    sessions = util.load_json(_sessions_path(), [])
    if idx < 0 or idx >= len(sessions):
        print(f"No session at index {idx}")
        return

    session = sessions[idx]
    prompt = session.get("_sample_prompt", "")
    predicted = session.get("dominant_tier", "standard")
    if not prompt:
        print("Session has no stored prompt — can't rate.")
        return

    learner.save_feedback(prompt, predicted, corrected)
    print(f"Saved feedback: '{prompt[:50]}...' → {corrected}")


def cmd_watch() -> None:
    """Live terminal dashboard."""
    try:
        from rich.live import Live
        from rich.table import Table
        from rich.panel import Panel
        from rich.layout import Layout
    except ImportError:
        print("The watch command requires 'rich'. Install with: pip install rich")
        return

    def make_dashboard() -> Layout:
        stats = weekly_stats()
        spent_str = costs.format_dollars(stats["spent_cents"])
        save_str = costs.format_dollars(stats["could_save_cents"])

        live = util.load_json(os.path.join(util.PENNY_DIR, "live_session.json"), None)
        live_str = ""
        if live:
            try:
                ts = datetime.fromisoformat(live["timestamp"])
                if datetime.now() - ts < timedelta(minutes=2):
                    live_cost = costs.format_dollars(live.get("cost_cents", 0))
                    live_str = f"  \u25b6 Live session: {live_cost}"
            except (KeyError, ValueError):
                pass

        feedback_count = len(learner.load_feedback())

        summary = Table.grid(padding=(0, 1))
        summary.add_column()
        summary.add_row(f"[bold]Spent this week:[/] {spent_str}")
        summary.add_row(f"[bold]Could save:[/]     {save_str}")
        summary.add_row(f"[bold]Sessions:[/]      {stats['session_count']}  ({stats['flagged_count']} flagged)")
        summary.add_row(f"[bold]Feedback:[/]      {feedback_count} labeled")

        table = Table(show_header=True, header_style="bold")
        table.add_column("When", width=10)
        table.add_column("Tier", width=10)
        table.add_column("Prompt", width=50)

        sessions_data = stats.get("sessions", [])
        for s in sessions_data[-8:]:
            ts = _ts_from(s)
            ts_str = ts.strftime("%H:%M") if ts else "?"
            tier = s.get("dominant_tier", "?")
            prompt = s.get("_sample_prompt", "")[:48]
            table.add_row(ts_str, tier, prompt)

        layout = Layout()
        layout.split_column(
            Layout(Panel(summary, title=f"Penny {live_str}")),
            Layout(Panel(table, title="Recent classifications")),
        )
        return layout

    try:
        with Live(make_dashboard(), refresh_per_second=2, screen=True) as live:
            import signal
            def _handle(sig, frame):
                raise KeyboardInterrupt
            signal.signal(signal.SIGINT, _handle)
            while True:
                live.update(make_dashboard())
                import time
                time.sleep(5)
    except KeyboardInterrupt:
        pass


def cmd_check_preference() -> None:
    """Output 'conservative' if user history warrants being cautious about switching."""
    if preference.should_switch_conservatively():
        print("conservative")
    else:
        print("normal")


def cmd_help() -> None:
    print("Penny -- a savings companion for Claude Code\n")
    print("Commands:")
    print("  penny stats               Show this week's spend and savings")
    print("  penny set-default         Switch your default model to match your usage")
    print("  penny set-default --restore   Undo the last set-default change")
    print("  penny pause               Turn off nudges and tips")
    print("  penny resume              Turn nudges and tips back on")
    print("  penny watch               Live terminal dashboard")
    print("  penny rate                List recent classifications to rate")
    print("  penny rate-session <i> <tier>   Correct a classification")
    print("  penny health              Check Penny's status and error log")
    print("  penny help                Show this message")
    print()
    print("Internal commands (used by wrapper.sh):")
    print("  penny check-cap <date>        Check auto-switch frequency cap")
    print("  penny check-tip <date>        Check and show a usage tip")
    print("  penny check-preference        Check if user prefers conservative switching")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        cmd_help()
        return

    command = args[0]
    try:
        if command == "stats":
            cmd_stats()
        elif command == "set-default":
            if "--restore" in args:
                cmd_restore()
            else:
                cmd_set_default()
        elif command == "pause":
            cmd_pause()
        elif command == "resume":
            cmd_resume()
        elif command == "health":
            cmd_health()
        elif command == "watch":
            cmd_watch()
        elif command == "rate":
            cmd_rate()
        elif command == "rate-session":
            cmd_rate_session(args[1:])
        elif command == "check-preference":
            cmd_check_preference()
        elif command == "check-cap":
            today = args[1] if len(args) > 1 else datetime.now().strftime("%Y-%m-%d")
            cmd_check_cap(today)
        elif command == "check-tip":
            today = args[1] if len(args) > 1 else datetime.now().strftime("%Y-%m-%d")
            cmd_check_tip(today)
        elif command in ("help", "-h", "--help"):
            cmd_help()
        else:
            print(f"Unknown command: {command}")
            cmd_help()
    except Exception as e:
        print(f"Penny hit a snag: {e}")


if __name__ == "__main__":
    main()
