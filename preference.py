"""Per-user preference learning based on auto-switch acceptance history."""

from typing import Dict, Optional

import util


def _prefs_path() -> str:
    return util.PENNY_DIR + "/prefs.json"


def _load() -> Dict:
    return util.load_json(_prefs_path(), {})


def _save(prefs: Dict) -> None:
    util.write_json(_prefs_path(), prefs)


def record_switch(auto_switched: bool, nudge_accepted: Optional[bool]) -> None:
    prefs = _load()
    switches = prefs.get("auto_switch_total", 0)
    accepts = prefs.get("auto_switch_accepted", 0)

    # Only count a switch when we actually switched AND we know the outcome.
    # nudge_accepted is None when we couldn't determine acceptance (no marker /
    # no model info) — in that case don't increment either counter, otherwise
    # the acceptance rate is skewed toward 100%.
    if auto_switched and nudge_accepted is not None:
        prefs["auto_switch_total"] = switches + 1
        if nudge_accepted:
            prefs["auto_switch_accepted"] = accepts + 1

    _save(prefs)


def acceptance_rate() -> float:
    prefs = _load()
    total = prefs.get("auto_switch_total", 0)
    if total == 0:
        return 1.0
    accepted = prefs.get("auto_switch_accepted", 0)
    return accepted / total


def should_switch_conservatively() -> bool:
    rate = acceptance_rate()
    total = _load().get("auto_switch_total", 0)
    if total < 5:
        return False
    return rate < 0.5
