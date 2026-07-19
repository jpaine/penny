import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import util

MIN_FEEDBACK_FOR_TRAIN = 10
CONFIDENCE_THRESHOLD = 0.6

TIERS = ["basic", "standard", "advanced"]

_TOKEN_PAT = re.compile(r"[a-zA-Z_]\w{2,}")


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_PAT.findall(text)]


def _feedback_path() -> str:
    return os.path.join(util.PENNY_DIR, "feedback.jsonl")


def load_feedback() -> List[Dict]:
    examples = []
    try:
        with open(_feedback_path()) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    examples.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return examples


def save_feedback(prompt: str, predicted_tier: str, corrected_tier: str) -> None:
    os.makedirs(util.PENNY_DIR, exist_ok=True)
    entry = {
        "prompt": prompt,
        "predicted_tier": predicted_tier,
        "corrected_tier": corrected_tier,
        "timestamp": datetime.now().isoformat(),
    }
    with open(_feedback_path(), "a") as f:
        f.write(json.dumps(entry) + "\n")


def _train() -> Optional[Dict]:
    examples = load_feedback()
    if len(examples) < MIN_FEEDBACK_FOR_TRAIN:
        return None

    tier_word_counts: Dict[str, Counter] = defaultdict(Counter)
    tier_doc_counts: Dict[str, int] = Counter()
    total_docs = len(examples)

    for ex in examples:
        tier = ex.get("corrected_tier", ex.get("predicted_tier", "standard"))
        if tier not in TIERS:
            continue
        tier_doc_counts[tier] += 1
        tokens = _tokenize(ex.get("prompt", ""))
        tier_word_counts[tier].update(tokens)

    vocab: set = set()
    for tc in tier_word_counts.values():
        vocab.update(tc.keys())
    vocab_size = len(vocab)

    model = {
        "tier_priors": {t: math.log(tier_doc_counts.get(t, 0) + 1) - math.log(total_docs + len(TIERS))
                        for t in TIERS},
        "word_probs": {},
        "vocab_size": vocab_size,
            "total_examples": total_docs,
    }

    for tier in TIERS:
        tc = tier_word_counts.get(tier, Counter())
        total_words = sum(tc.values())
        model["word_probs"][tier] = {
            word: math.log((tc.get(word, 0) + 1) / (total_words + vocab_size))
            for word in vocab
        }

    return model


def predict(prompt: str) -> Tuple[str, float]:
    model = _train()

    if model is None:
        return ("heuristics", 0.0)

    tokens = _tokenize(prompt)
    if not tokens:
        return ("heuristics", 0.0)

    scores = {}
    for tier in TIERS:
        log_prob = model["tier_priors"].get(tier, 0)
        word_probs = model["word_probs"].get(tier, {})
        for token in tokens:
            log_prob += word_probs.get(token, math.log(1 / (1 + model["vocab_size"])))
        scores[tier] = log_prob

    sorted_tiers = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_tier, best_score = sorted_tiers[0]
    second_score = sorted_tiers[1][1] if len(sorted_tiers) > 1 else float("-inf")

    if best_score == float("-inf"):
        return ("heuristics", 0.0)

    confidence = 1.0 - (math.exp(second_score - best_score) if second_score != float("-inf") else 0.0)

    if confidence < CONFIDENCE_THRESHOLD:
        return ("heuristics", confidence)

    return (best_tier, confidence)
