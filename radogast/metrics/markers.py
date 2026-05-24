"""FSM state detection via marker words in sliding windows."""
from __future__ import annotations
from radogast.target import Target


def detect_state(messages: list[str], target: Target, window: int) -> dict:
    """Return active milestone name and per-milestone marker scores for given window."""
    window_text = " ".join(messages[-window:]).lower()
    scores: dict[str, int] = {}
    for ms in target.milestones:
        scores[ms.name] = sum(1 for m in ms.markers if m.lower() in window_text)
    active = max(scores, key=scores.get) if scores else None
    # treat zero-score as "no milestone detected"
    if active and scores[active] == 0:
        active = None
    return {"active": active, "scores": scores}


def vote_state(messages: list[str], target: Target, windows: list[int]) -> dict:
    """Run detect_state for each window size and return consensus + per-window results."""
    per_window = {w: detect_state(messages, target, w) for w in windows}
    votes: dict[str, int] = {}
    for result in per_window.values():
        if result["active"]:
            votes[result["active"]] = votes.get(result["active"], 0) + 1
    consensus = max(votes, key=votes.get) if votes else None
    return {"consensus": consensus, "votes": votes, "per_window": per_window}


def check_transition(vote_result: dict, target: Target) -> list[str]:
    """Return warnings if milestones are detected out of sequence."""
    warnings = []
    if not target.milestones or not vote_result["consensus"]:
        return warnings
    names = [m.name for m in target.milestones]
    active_idx = names.index(vote_result["consensus"]) if vote_result["consensus"] in names else -1
    per_window = vote_result["per_window"]
    # check if any earlier milestone has zero score across all windows
    for i in range(active_idx):
        prev = names[i]
        all_zero = all(r["scores"].get(prev, 0) == 0 for r in per_window.values())
        if all_zero:
            warnings.append(
                f"milestone '{vote_result['consensus']}' active but "
                f"'{prev}' has no evidence — possible skip"
            )
    return warnings
