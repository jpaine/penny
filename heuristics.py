import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

import costs
import learner

# Keywords that strongly indicate an advanced task even when used alone
STRONG_ADVANCED: List[str] = [
    "refactor", "architect", "architecture", "rewrite", "migrate", "migration",
    "audit", "from scratch", "best approach", "trade-off", "tradeoff",
    "review my", "debug", "root cause", "should i", "compare",
    "pros and cons",
]

WEAK_ADVANCED: List[str] = [
    "design system", "explain why", "diagnose", "performance",
    "security", "all files", "entire codebase", "what's wrong",
]

# Neutralizing phrases -- if any of these appear within 30 chars before an
# advanced keyword, the match is suppressed (avoiding false positives like
# "should I refactor?" or "do I need to migrate?")
NEGATION_PATTERNS: List[str] = [
    r"don.t\s+(need\s+to\s+)?refactor",
    r"(should|can|do)\s+i\s+(even\s+|really\s+)?(refactor|migrate|rewrite|debug|audit)",
    r"(do|does)\s+(i|this|it)\s+(really\s+)?need\s+to\s+(refactor|migrate|rewrite|audit)",
    r"is\s+it\s+(worth|safe|time)",
    r"not\s+(a\s+)?(migration|refactor|audit)",
    r"avoid\s+(refactoring|migrating)",
    r"skip\s+the\s+(refactor|migration|audit)",
]

BASIC_PATTERNS: List[str] = [
    r"\btypo\b",
    r"\brename\b",
    r"\bdocstring\b",
    r"\badd (a |an )?comment\b",
    r"^what does this \w+\??$",
    r"\bformat (this|the) (json|code|file|text)\b",
]

TIERS: Dict[str, str] = {
    "claude-haiku-4-5": "basic",
    "claude-sonnet-5": "standard",
    "claude-opus-4-8": "advanced",
}

CHEAPER: Dict[str, Optional[str]] = {
    "claude-opus-4-8": "claude-sonnet-5",
    "claude-sonnet-5": "claude-haiku-4-5",
    "claude-haiku-4-5": None,
}

TIER_RANK: Dict[str, int] = {"basic": 0, "standard": 1, "advanced": 2}

TIER_TO_MODEL: Dict[str, str] = {
    "basic": "claude-haiku-4-5",
    "standard": "claude-sonnet-5",
    "advanced": "claude-opus-4-8",
}


def _has_negated_keyword(text: str, keyword: str) -> bool:
    idx = text.find(keyword)
    if idx < 0:
        return False
    start = max(0, idx - 30)
    end = min(len(text), idx + len(keyword) + 30)
    window = text[start:end]
    for pat in NEGATION_PATTERNS:
        if re.search(pat, window):
            return True
    return bool(re.search(r"(don't|isn't|not|avoid|skip|stop|without)\s*\w{0,20}$", text[max(0, idx - 30):idx]))


def classify_prompt(text: str) -> str:
    learned_tier, confidence = learner.predict(text)
    if learned_tier != "heuristics":
        return learned_tier

    lowered = text.lower().strip()
    char_len = len(lowered)
    is_short = char_len < 200

    strong = 0
    weak = 0
    for kw in STRONG_ADVANCED:
        if kw in lowered and not _has_negated_keyword(lowered, kw):
            strong += 1
    for kw in WEAK_ADVANCED:
        if kw in lowered and not _has_negated_keyword(lowered, kw):
            weak += 1

    if strong >= 1:
        return "advanced"
    if weak >= 2:
        return "advanced"
    if weak == 1 and not is_short:
        return "advanced"

    for pattern in BASIC_PATTERNS:
        if re.search(pattern, lowered) and is_short:
            return "basic"

    return "standard"


ALIAS_SUBSTRINGS: List[Tuple[str, str]] = [
    ("opus", "claude-opus-4-8"),
    ("haiku", "claude-haiku-4-5"),
    ("sonnet", "claude-sonnet-5"),
]


def normalize_model(model: str) -> str:
    if not model:
        return model
    if model in TIERS:
        return model
    lowered = model.lower()
    for substring, canonical in ALIAS_SUBSTRINGS:
        if substring in lowered:
            return canonical
    return model


def get_current_model() -> str:
    env_model = os.environ.get("ANTHROPIC_MODEL")
    if env_model:
        return normalize_model(env_model)

    settings_path = os.path.expanduser("~/.claude/settings.json")
    try:
        with open(settings_path) as f:
            settings = json.load(f)
        model = settings.get("model")
        if model:
            return normalize_model(model)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    return "claude-sonnet-5"


def model_tier(model: str) -> str:
    return TIERS.get(model, "standard")


def cheaper_model(model: str) -> Optional[str]:
    return CHEAPER.get(model)


TEST_CASES: List[Tuple[str, str]] = [
    ("fix typo in README", "basic"),
    ("rename userID to userId", "basic"),
    ("what does this return", "basic"),
    ("add a docstring", "basic"),
    ("format this JSON", "basic"),
    ("should I refactor this variable", "standard"),
    ("do I need to migrate this code", "standard"),
    ("write a function that parses CSV", "standard"),
    ("add error handling to this endpoint", "standard"),
    ("write tests for the auth module", "standard"),
    ("explain how this works", "standard"),
    ("help me implement pagination", "standard"),
    ("refactor the entire auth system", "advanced"),
    ("debug why this crashes in production", "advanced"),
    ("what's the best architecture for this", "advanced"),
    ("review my API design", "advanced"),
    ("migrate from REST to GraphQL", "advanced"),
    ("explain why this is slow", "standard"),
    ("rewrite this in async", "advanced"),
    ("should I use Redis or Memcached", "advanced"),
    ("audit my security setup", "advanced"),
    ("compare these two approaches", "advanced"),
    ("debug log is too verbose", "advanced"),
    ("refactor this variable name", "advanced"),
    ("pros and cons of microservices vs monolith for our team", "advanced"),
]


def _run_tests() -> List[Tuple[str, str, str]]:
    failures = []
    for text, expected in TEST_CASES:
        actual = classify_prompt(text)
        status = "OK" if actual == expected else "FAIL"
        if actual != expected:
            failures.append((text, expected, actual))
        print(f"[{status}] {text!r} -> {actual} (expected {expected})")
    print(f"\n{len(TEST_CASES) - len(failures)}/{len(TEST_CASES)} passed")
    return failures


def _decide(prompt_text: str) -> str:
    tier = classify_prompt(prompt_text)
    current_model = get_current_model()
    current_tier = model_tier(current_model)
    cheaper = cheaper_model(current_model)

    savings = 0.0
    if cheaper and TIER_RANK[tier] < TIER_RANK[current_tier]:
        savings = costs.savings_cents(len(prompt_text), current_model, cheaper)

    return "\t".join([
        tier,
        current_model,
        current_tier,
        cheaper or "",
        f"{savings:.4f}",
    ])


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "classify":
        prompt_text = sys.argv[2] if len(sys.argv) > 2 else ""
        print(classify_prompt(prompt_text))
    elif len(sys.argv) >= 2 and sys.argv[1] == "decide":
        prompt_text = sys.argv[2] if len(sys.argv) > 2 else ""
        print(_decide(prompt_text))
    else:
        _run_tests()
