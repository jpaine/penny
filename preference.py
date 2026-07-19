"""Per-user preference learning based on auto-switch acceptance history."""

from typing import Dict

import util


def _prefs_path() -> str:
    return util.PENNY_DIR + "/prefs.json"


def _load() -> Dict:
    return util.load_json(_prefs_path(), {})


def _save(prefs: Dict) -> None:
    util.write_json(_prefs_path(), prefs)


def record_switch(auto_switched: bool, nudge_accepted: bool) -> None:
    prefs = _load()
    switches = prefs.get("auto_switch_total", 0)
    accepts = prefs.get("auto_switch_accepted", 0)

    if auto_switched:
        prefs["auto_switch_total"] = switches + 1
        if nudge_accepted is not False:
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
