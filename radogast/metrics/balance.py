"""Term frequency bias: detect when one term dominates the context."""
from __future__ import annotations
import re


def compute_balance(context_text: str, key_terms: list[str]) -> dict:
    """Return per-term frequencies, bias score, and which term dominates."""
    if not key_terms:
        return {"freqs": {}, "bias": 0.0, "biased_toward": None}

    freqs = {
        t: len(re.findall(re.escape(t), context_text, re.IGNORECASE))
        for t in key_terms
    }
    total = sum(freqs.values())
    mean = total / len(freqs)
    max_freq = max(freqs.values())
    bias = round(max_freq / mean, 2) if mean > 0 else 0.0
    biased = max(freqs, key=freqs.get) if max_freq > 0 else None

    return {"freqs": freqs, "bias": bias, "biased_toward": biased}
