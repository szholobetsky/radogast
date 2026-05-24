"""Term coverage (defined/mentioned/absent) and ROUGE-1-Recall."""
from __future__ import annotations
import re


DEFINITION_PATTERNS = [
    r"{term}\s+(?:is|are|—|це|це\s+є|refers\s+to|means)\s+",
    r"{term}\s*:\s+\S",
    r"##\s+{term}\b",
    r"###\s+{term}\b",
    r"\*\*{term}\*\*\s*[—\-:]\s+\S",
]


def term_coverage(context_text: str, key_terms: list[str]) -> dict[str, str]:
    """Return status for each term: 'defined' | 'mentioned' | 'absent'."""
    result: dict[str, str] = {}
    for term in key_terms:
        escaped = re.escape(term)
        if not re.search(escaped, context_text, re.IGNORECASE):
            result[term] = "absent"
        elif any(
            re.search(p.format(term=escaped), context_text, re.IGNORECASE)
            for p in DEFINITION_PATTERNS
        ):
            result[term] = "defined"
        else:
            result[term] = "mentioned"
    return result


def coverage_ratio(cov: dict[str, str]) -> float:
    if not cov:
        return 0.0
    defined = sum(1 for s in cov.values() if s == "defined")
    return round(defined / len(cov), 3)


def rouge1_recall(target_text: str, context_text: str) -> float:
    """Fraction of target unigrams (≥4 chars, non-stopword) found in context."""
    _STOP = {
        "that", "this", "with", "from", "have", "which", "will", "they",
        "their", "there", "been", "were", "into", "also",
    }

    def _tokens(text: str) -> set[str]:
        return {
            w.lower() for w in re.findall(r"\b[A-Za-zА-Яа-яІіЇїЄє]{4,}\b", text)
            if w.lower() not in _STOP
        }

    t_tokens = _tokens(target_text)
    if not t_tokens:
        return 0.0
    c_tokens = _tokens(context_text)
    return round(len(t_tokens & c_tokens) / len(t_tokens), 3)
