"""Extract (term → definition) pairs from context text."""
from __future__ import annotations
import re

def _patterns_for(escaped_term: str) -> list[str]:
    return [
        rf"{escaped_term}\s+(?:is|are|—|це|refers\s+to|means)\s+([^.\n]{{10,120}})",
        rf"{escaped_term}\s*:\s+([^.\n]{{10,120}})",
        rf"\*\*{escaped_term}\*\*\s*[—\-:]\s+([^.\n]{{10,120}})",
        rf"##\s+{escaped_term}\b[^\n]*\n+([^\n]{{10,200}})",
    ]


def extract_glossary(context_text: str, key_terms: list[str]) -> dict[str, str | None]:
    """For each term: return best definition string found, or None."""
    result: dict[str, str | None] = {}
    for term in key_terms:
        escaped = re.escape(term)
        found = None
        for pat in _patterns_for(escaped):
            try:
                m = re.search(pat, context_text, re.IGNORECASE)
            except re.error:
                continue
            if m:
                found = m.group(1).strip().rstrip(".,;")
                break
        if found is None:
            found = _first_occurrence_context(context_text, term)
        result[term] = found
    return result


def _first_occurrence_context(text: str, term: str) -> str | None:
    """Return the sentence containing first occurrence of term."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    for sent in sentences:
        if re.search(re.escape(term), sent, re.IGNORECASE):
            s = sent.strip()
            return s[:200] if len(s) > 200 else s
    return None
