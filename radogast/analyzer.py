"""Orchestrates all metrics and produces a RadogastReport."""
from __future__ import annotations
from dataclasses import dataclass, field

from radogast.target import Target
from radogast.metrics import coverage, drift, markers, balance, glossary


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
    # falsification
    falsification_fails: list[str]
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

    # ── falsification ─────────────────────────────────────────────────────────
    fails = []
    for test in target.falsification.critical_tests:
        # heuristic: if the test references an absent term, flag it
        for term in target.key_terms:
            if term.lower() in test.lower() and cov.get(term) == "absent":
                fails.append(test)
                break
    for req in target.falsification.minimum_evidence:
        for term in target.key_terms:
            if term.lower() in req.lower() and cov.get(term) == "absent":
                fails.append(f"minimum evidence not met: {req}")
                break

    # ── suggestions ───────────────────────────────────────────────────────────
    suggestions = _build_suggestions(
        cov, bal, drift_result, vote_result, trans_warnings, bias_thresh
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
        falsification_fails=list(dict.fromkeys(fails)),
        suggestions=suggestions,
    )


def _build_suggestions(cov, bal, drift_result, vote_result, trans_warnings, bias_thresh) -> list[str]:
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
    return s
