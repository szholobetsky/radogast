"""Orchestrates all metrics and produces a RadogastReport."""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from radogast.target import Target
from radogast.metrics import coverage, drift, markers, balance, glossary, trends


@dataclass
class RadogastReport:
    # drift
    drift_angle: float | None
    drift_status: str               # on_track | warning | critical | no_embeddings
    # milestones
    active_milestone: str | None
    milestone_votes: dict
    milestone_warnings: list[str]
    # coverage
    term_coverage: dict[str, str]   # term → defined|mentioned|absent
    coverage_ratio: float
    rouge1: float
    # balance
    balance: dict                   # freqs, bias, biased_toward
    # glossary
    glossary: dict[str, str | None]
    # verification
    verification_fails: list[str]
    verification_trends: dict[str, dict]  # term → {spark, trend, recent}
    # out of scope
    oos_hits: dict[str, int]        # term → total count in context
    oos_recent: list[str]           # terms that appeared in last 3 messages
    oos_trends: dict[str, dict]     # term → {spark, trend}
    # key term trends
    term_trends: dict[str, dict]    # term → {spark, trend, recent}
    # milestone trends
    milestone_trends: dict[str, dict]  # name → {spark, first_seg, last_seg, active}
    # output
    suggestions: list[str]


def analyze(
    messages: list[dict],
    target: Target,
    cfg: dict,
    verbose: bool = True,
) -> RadogastReport:
    import sys

    def _step(msg: str):
        if verbose:
            print(f"  [radogast] {msg}", file=sys.stderr, flush=True)

    contents = [m.get("content", "") for m in messages if m.get("content")]
    context_text = "\n".join(contents)
    target_text = target.goal + " " + " ".join(target.key_terms)
    windows: list[int] = cfg.get("windows", [1, 3, 5])
    embed_model: str = cfg.get("embedding_model", "BAAI/bge-small-en-v1.5")
    hybrid: bool = cfg.get("hybrid", True)
    drift_thresh: float = float(cfg.get("drift_threshold_deg", 40.0))
    bias_thresh: float = float(cfg.get("bias_threshold", 3.0))
    n_seg: int = int(cfg.get("trend_segments", 7))

    n_msg = len(contents)
    n_terms = len(target.key_terms)
    _step(f"messages: {n_msg}  terms: {n_terms}  windows: {windows}")

    # ── drift ─────────────────────────────────────────────────────────────────
    if hybrid:
        _step("drift: computing embeddings...")
        drift_result = drift.compute_drift(
            contents, target.goal, target.key_terms,
            embed_model, max_window=max(windows),
        )
        _step(f"drift: {drift_result.get('angle', 'n/a')}°  status: {drift_result['status']}")
    else:
        drift_result = {"angle": None, "status": "disabled", "available": False}

    # override threshold from config
    if drift_result["available"] and drift_result["angle"] is not None:
        angle = drift_result["angle"]
        if angle <= drift_thresh:
            drift_result["status"] = "on_track"
        elif angle <= drift_thresh * 1.6:
            drift_result["status"] = "warning"
        else:
            drift_result["status"] = "critical"

    # ── markers ───────────────────────────────────────────────────────────────
    _step("markers: detecting stage...")
    vote_result = markers.vote_state(contents, target, windows)
    trans_warnings = markers.check_transition(vote_result, target)
    _step(f"markers: stage={vote_result.get('consensus') or 'none'}")

    # ── coverage ──────────────────────────────────────────────────────────────
    _step(f"coverage: checking {n_terms} terms...")
    cov = coverage.term_coverage(context_text, target.key_terms)
    cov_ratio = coverage.coverage_ratio(cov)
    r1 = coverage.rouge1_recall(target_text, context_text)
    defined = sum(1 for s in cov.values() if s == "defined")
    _step(f"coverage: {defined}/{n_terms} defined  rouge1={r1:.2f}")

    # ── balance ───────────────────────────────────────────────────────────────
    _step("balance: frequency analysis...")
    bal = balance.compute_balance(context_text, target.key_terms)

    # ── glossary ──────────────────────────────────────────────────────────────
    _step("glossary: extracting definitions...")
    gloss = glossary.extract_glossary(context_text, target.key_terms)

    # ── trends ────────────────────────────────────────────────────────────────
    _step("trends: computing sparklines...")
    term_trends = {
        term: trends.term_trend(contents, term, n_seg)
        for term in target.key_terms
    }
    milestone_trends = {
        ms.name: trends.milestone_trend(contents, ms.name, ms.markers, n_seg)
        for ms in target.milestones
    }

    # ── verification ─────────────────────────────────────────────────────────
    fails = [
        term for term in target.verification.mandatory_terms
        if cov.get(term, "absent") == "absent"
    ]
    verification_trends = {
        term: trends.term_trend(contents, term, n_seg)
        for term in target.verification.mandatory_terms
    }

    # ── out of scope ──────────────────────────────────────────────────────────
    _step(f"out-of-scope: checking {len(target.out_of_scope)} terms...")
    oos_hits = {}
    oos_recent = []
    oos_trends = {}
    for term in target.out_of_scope:
        t = trends.term_trend(contents, term, n_seg)
        oos_trends[term] = t
        if t["counts"] and sum(t["counts"]) > 0:
            oos_hits[term] = sum(t["counts"])
            if t["recent"] > 0:
                oos_recent.append(term)

    # ── suggestions ───────────────────────────────────────────────────────────
    suggestions = _build_suggestions(
        cov, bal, drift_result, vote_result, trans_warnings, bias_thresh,
        oos_hits, oos_recent, oos_trends,
    )

    return RadogastReport(
        drift_angle=drift_result.get("angle"),
        drift_status=drift_result["status"],
        active_milestone=vote_result["consensus"],
        milestone_votes=vote_result["votes"],
        milestone_warnings=trans_warnings,
        term_coverage=cov,
        coverage_ratio=cov_ratio,
        rouge1=r1,
        balance=bal,
        glossary=gloss,
        verification_fails=list(dict.fromkeys(fails)),
        verification_trends=verification_trends,
        oos_hits=oos_hits,
        oos_recent=oos_recent,
        oos_trends=oos_trends,
        term_trends=term_trends,
        milestone_trends=milestone_trends,
        suggestions=suggestions,
    )


def _build_suggestions(cov, bal, drift_result, vote_result, trans_warnings, bias_thresh,
                       oos_hits=None, oos_recent=None, oos_trends=None) -> list[str]:
    s = []
    absent = [t for t, st in cov.items() if st == "absent"]
    if absent:
        s.append(f"missing from context: {', '.join(absent[:3])} — add definitions or examples")
    undefined = [t for t, st in cov.items() if st == "mentioned"]
    if undefined:
        s.append(f"mentioned but not defined: {', '.join(undefined[:3])} — add explicit definitions")
    if bal["bias"] > bias_thresh and bal["biased_toward"]:
        s.append(
            f"context biased toward '{bal['biased_toward']}' (ratio {bal['bias']}x) "
            f"— reduce or rebalance with other key terms"
        )
    if drift_result.get("status") == "warning":
        s.append(f"drift {drift_result['angle']}° — context drifting from target, consider refocusing")
    elif drift_result.get("status") == "critical":
        s.append(
            f"drift {drift_result['angle']}° — CRITICAL: context has diverged significantly from target"
        )
    s.extend(trans_warnings)
    for term, count in (oos_hits or {}).items():
        t = (oos_trends or {}).get(term, {})
        trend = t.get("trend", "")
        if trend == "declining":
            continue  # was mentioned but fading — no alert
        if term in (oos_recent or []) or trend == "growing":
            s.append(f"OUT-OF-SCOPE '{term}' — {count}x, trend: {trend} — refocus away from this topic")
        else:
            s.append(f"out-of-scope '{term}' — {count}x in context")
    return s
