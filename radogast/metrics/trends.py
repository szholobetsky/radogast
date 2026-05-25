"""Temporal trend analysis: sparkline + trend label per term across message segments."""
from __future__ import annotations
import re

_SPARK_CHARS = "·▁▂▃▄▅▆▇█"


def _count_in_text(text: str, term: str) -> int:
    return len(re.findall(re.escape(term.lower()), text.lower()))


def term_trend(
    messages: list[str],
    term: str,
    segments: int = 5,
) -> dict:
    """
    Divide messages into `segments` equal buckets, count term frequency per bucket.
    Returns:
        spark   — sparkline string e.g. "··▃▅█▇▅"
        trend   — "growing" | "stable" | "declining" | "absent" | "peak_early" | "peak_late"
        counts  — list of int per segment (length == segments, padded with 0 if n < segments)
        recent  — count in last 3 raw messages (independent of segment boundaries)
    """
    n = len(messages)
    if n == 0:
        return {"spark": "·" * segments, "trend": "absent", "counts": [0] * segments, "recent": 0}

    # effective segments: can't have more buckets than messages
    # this guarantees the last bucket always contains at least the last message
    effective = min(segments, n)
    seg_size = n / effective
    counts_eff = []
    for i in range(effective):
        start = int(i * seg_size)
        end = int((i + 1) * seg_size) if i < effective - 1 else n
        seg_text = " ".join(messages[start:end])
        counts_eff.append(_count_in_text(seg_text, term))

    # pad to requested length so sparklines stay same width across all terms
    counts = counts_eff + [0] * (segments - effective)

    # recent = last effective bucket; always covers the last message by construction
    recent = counts_eff[-1]

    total = sum(counts_eff)

    # sparkline over effective segments, pad remainder with dots
    max_c = max(counts_eff) or 1
    spark = "".join(
        _SPARK_CHARS[max(1, int((c / max_c) * (len(_SPARK_CHARS) - 1)))] if c > 0 else "·"
        for c in counts_eff
    ) + "·" * (segments - effective)

    # trend: compare first half vs second half of effective buckets
    mid = effective // 2
    first_half = sum(counts_eff[:mid]) if mid else 0
    second_half = sum(counts_eff[mid:])

    if total == 0:
        trend = "absent"
    elif first_half == 0 and second_half > 0:
        trend = "peak_late"
    elif second_half == 0 and first_half > 0:
        trend = "peak_early"
    elif second_half > first_half * 1.4:
        trend = "growing"
    elif first_half > second_half * 1.4:
        trend = "declining"
    else:
        trend = "stable"

    return {"spark": spark, "trend": trend, "counts": counts, "recent": recent}


def milestone_trend(
    messages: list[str],
    milestone_name: str,
    milestone_markers: list[str],
    segments: int = 5,
) -> dict:
    """
    Track when milestone markers appeared across message segments.
    Returns aggregate spark + per-marker trends for tree display.
    """
    n = len(messages)
    if n == 0 or not milestone_markers:
        return {
            "spark": "·" * segments, "first_seg": None, "last_seg": None,
            "active": False, "counts": [0] * segments, "markers": {},
        }

    effective = min(segments, n)
    seg_size = n / effective
    counts_eff = []
    for i in range(effective):
        start = int(i * seg_size)
        end = int((i + 1) * seg_size) if i < effective - 1 else n
        seg_text = " ".join(messages[start:end]).lower()
        hit = sum(1 for m in milestone_markers if m.lower() in seg_text)
        counts_eff.append(hit)

    counts = counts_eff + [0] * (segments - effective)

    max_c = max(counts_eff) or 1
    spark = "".join(
        _SPARK_CHARS[max(1, int((c / max_c) * (len(_SPARK_CHARS) - 1)))] if c > 0 else "·"
        for c in counts_eff
    ) + "·" * (segments - effective)

    active_segs = [i for i, c in enumerate(counts_eff) if c > 0]
    first_seg = active_segs[0] if active_segs else None
    last_seg = active_segs[-1] if active_segs else None
    # active = any marker appeared in last 3 raw messages
    recent_text = " ".join(messages[-min(3, n):]).lower()
    active = any(m.lower() in recent_text for m in milestone_markers)

    # per-marker trends for tree display
    marker_data = {marker: term_trend(messages, marker, segments) for marker in milestone_markers}

    return {
        "spark": spark,
        "first_seg": first_seg,
        "last_seg": last_seg,
        "active": active,
        "counts": counts,
        "markers": marker_data,
    }
