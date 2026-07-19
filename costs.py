import json
import os
from typing import Any, Dict, Optional

PRICING_MODULE = os.path.dirname(os.path.abspath(__file__))
PRICING_FILE = os.path.join(PRICING_MODULE, "pricing.json")
USER_PRICING_FILE = os.path.expanduser("~/.penny/pricing.json")


def _load_pricing() -> Dict:
    path = USER_PRICING_FILE if os.path.exists(USER_PRICING_FILE) else PRICING_FILE
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def config(key: str, default: Any = None) -> Any:
    pricing = _load_pricing()
    return pricing.get(key, default)


def model_price(model: str) -> Optional[Dict[str, float]]:
    pricing = _load_pricing()
    entry = pricing.get(model)
    if entry and "input" in entry and "output" in entry:
        return entry
    return None


def estimate_cost_cents(char_count: int, model: str) -> float:
    model_entry = model_price(model)
    if model_entry is None:
        model_entry = model_price("claude-sonnet-5") or {"input": 3.0, "output": 15.0}
    pricing = _load_pricing()
    chars_per_token = float(pricing.get("chars_per_token", 4))
    input_fraction = float(pricing.get("input_fraction", 0.3))
    output_fraction = float(pricing.get("output_fraction", 0.7))
    tokens = char_count / chars_per_token
    input_tokens = tokens * input_fraction
    output_tokens = tokens * output_fraction
    dollars = (
        (input_tokens / 1_000_000) * model_entry["input"]
        + (output_tokens / 1_000_000) * model_entry["output"]
    )
    return dollars * 100


def savings_cents(char_count: int, current: str, suggested: str) -> float:
    return estimate_cost_cents(char_count, current) - estimate_cost_cents(char_count, suggested)


def format_dollars(cents: float) -> str:
    return "${:.2f}".format(cents / 100)
