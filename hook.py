import glob
import json
import os
import sys
import traceback
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import costs
import heuristics
import preference
import util

ERROR_LOG_PATH = os.path.join(util.PENNY_DIR, "error.log")

TIER_TO_MODEL = heuristics.TIER_TO_MODEL
TIER_RANK = heuristics.TIER_RANK


def log_error(msg: str) -> None:
    try:
        os.makedirs(util.PENNY_DIR, exist_ok=True)
        with open(ERROR_LOG_PATH, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except OSError:
        pass


def find_latest_transcript() -> Optional[str]:
    projects_dir = os.path.expanduser("~/.claude/projects")
    candidates = glob.glob(os.path.join(projects_dir, "**", "*.jsonl"), recursive=True)
    candidates += glob.glob(os.path.join(projects_dir, "**", "*.json"), recursive=True)
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return ""


def parse_transcript(path: str) -> Tuple[List[str], Optional[str]]:
    user_texts: List[str] = []
    model_used: Optional[str] = None

    def handle_entry(entry: Any) -> None:
        nonlocal model_used
        if not isinstance(entry, dict):
            return
        msg = entry.get("message", entry)
        role = msg.get("role") or entry.get("type")
        if role == "user":
            text = extract_text(msg.get("content", ""))
            if text.strip():
                user_texts.append(text)
        elif role == "assistant":
            model_used = msg.get("model") or model_used

    if path.endswith(".jsonl"):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    handle_entry(json.loads(line))
                except json.JSONDecodeError:
                    continue
    else:
        with open(path) as f:
            data = json.load(f)
        entries = data if isinstance(data, list) else data.get("messages", [])
        for entry in entries:
            handle_entry(entry)

    return user_texts, model_used


def dominant_tier_of(user_texts: List[str]) -> str:
    if not user_texts:
        return "standard"
    tiers = [heuristics.classify_prompt(t) for t in user_texts]
    return Counter(tiers).most_common(1)[0][0]


def week_key(dt: datetime) -> str:
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week}"


def count_mismatches_this_week(sessions: List[Dict], now: datetime) -> int:
    current_week = week_key(now)
    count = 0
    for s in sessions:
        try:
            ts = datetime.fromisoformat(s["timestamp"])
        except (KeyError, ValueError):
            continue
        if week_key(ts) != current_week:
            continue
        if TIER_RANK.get(s.get("model_tier"), 1) > TIER_RANK.get(s.get("dominant_tier"), 1):
            count += 1
    return count


def main() -> None:
    try:
        os.makedirs(util.PENNY_DIR, exist_ok=True)

        transcript_path = find_latest_transcript()
        user_texts: List[str] = []
        transcript_model: Optional[str] = None
        if transcript_path:
            user_texts, transcript_model = parse_transcript(transcript_path)

        char_count = sum(len(t) for t in user_texts)
        dominant_tier = dominant_tier_of(user_texts)
        sample_prompt = user_texts[0][:200] if user_texts else ""

        model = heuristics.normalize_model(transcript_model) if transcript_model else heuristics.get_current_model()
        model_tier = heuristics.model_tier(model)

        estimated_cost_cents = costs.estimate_cost_cents(char_count, model)

        potential_savings_cents = 0.0
        if TIER_RANK.get(model_tier, 1) > TIER_RANK.get(dominant_tier, 1):
            suggested_model = TIER_TO_MODEL.get(dominant_tier, model)
            potential_savings_cents = costs.savings_cents(char_count, model, suggested_model)

        now = datetime.now()
        # Detect if wrapper.sh auto-switched (actual model differs from env default)
        auto_switched = False
        if transcript_model:
            default_model = heuristics.normalize_model(
                os.environ.get("ANTHROPIC_MODEL") or ""
            )
            if default_model and default_model != model:
                auto_switched = True

        record: Dict[str, Any] = {
            "timestamp": now.isoformat(),
            "model": model,
            "model_tier": model_tier,
            "dominant_tier": dominant_tier,
            "estimated_cost_cents": round(estimated_cost_cents, 2),
            "potential_savings_cents": round(potential_savings_cents, 2),
            "char_count": char_count,
            "turn_count": len(user_texts),
            "auto_switched": auto_switched,
            "nudge_accepted": None,
            "_sample_prompt": sample_prompt,
        }

        sessions: List[Dict] = util.load_json(os.path.join(util.PENNY_DIR, "sessions.json"), [])
        sessions.append(record)
        util.write_json(os.path.join(util.PENNY_DIR, "sessions.json"), sessions)

        util.write_json(os.path.join(util.PENNY_DIR, "live_session.json"), {
            "cost_cents": round(estimated_cost_cents, 2),
            "timestamp": now.isoformat(),
        })

        notif_threshold = costs.config("min_savings_cents_for_notification", 10)
        if potential_savings_cents > notif_threshold and TIER_RANK.get(model_tier, 1) > TIER_RANK.get(dominant_tier, 1):
            message = (
                f"This session could have cost {costs.format_dollars(potential_savings_cents)} less "
                f"in a faster mode."
            )
            util.write_json(os.path.join(util.PENNY_DIR, "notify.json"), {
                "timestamp": now.isoformat(),
                "message": message,
            })

            mismatch_count = count_mismatches_this_week(sessions, now)
            if mismatch_count >= 3:
                prefs: Dict = util.load_json(os.path.join(util.PENNY_DIR, "prefs.json"), {})
                prefs["suggested_default_switch"] = True
                util.write_json(os.path.join(util.PENNY_DIR, "prefs.json"), prefs)

        preference.record_switch(auto_switched, None)

    except Exception:
        log_error(traceback.format_exc())

    sys.exit(0)


if __name__ == "__main__":
    main()
