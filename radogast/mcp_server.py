"""FastMCP server — exposes Radogast as MCP tools (port 3700)."""
from __future__ import annotations
import asyncio
import json
import yaml

from mcp.server.fastmcp import FastMCP

from radogast import config as _cfg
from radogast.target import load_target, derive_target, Target
from radogast.analyzer import analyze

mcp = FastMCP("radogast")


def _cfg_load() -> dict:
    return _cfg.load()


@mcp.tool()
def analyze_context(messages_json: str, target_yaml: str) -> str:
    """
    Analyze an AI agent session for context drift and term coverage.

    messages_json: JSON array of {role, content} objects
    target_yaml:   YAML string (full target) OR path to .yaml file OR plain goal text

    Returns a JSON report with drift_angle, drift_status, term_coverage, suggestions, etc.
    """
    cfg = _cfg_load()
    messages = json.loads(messages_json)

    target = _resolve_target(target_yaml)

    report = analyze(messages, target, cfg)

    return json.dumps({
        "drift_angle": report.drift_angle,
        "drift_status": report.drift_status,
        "active_milestone": report.active_milestone,
        "term_coverage": report.term_coverage,
        "coverage_ratio": report.coverage_ratio,
        "rouge1": report.rouge1,
        "balance_bias": report.balance.get("bias"),
        "biased_toward": report.balance.get("biased_toward"),
        "glossary_found": sum(1 for v in report.glossary.values() if v),
        "glossary_total": len(report.glossary),
        "falsification_fails": report.falsification_fails,
        "suggestions": report.suggestions,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def get_drift_score(messages_json: str, goal: str, key_terms: str) -> str:
    """
    Quick drift check — returns drift angle in degrees and status.

    messages_json: JSON array of {role, content}
    goal:          one-sentence task description
    key_terms:     comma-separated domain terms

    Returns: {"angle": 23.5, "status": "on_track"}
    """
    from radogast.metrics.drift import compute_drift
    cfg = _cfg_load()
    messages = json.loads(messages_json)
    contents = [m.get("content", "") for m in messages if m.get("content")]
    terms = [t.strip() for t in key_terms.split(",") if t.strip()]

    result = compute_drift(
        contents, goal, terms,
        cfg.get("embedding_model", "BAAI/bge-small-en-v1.5"),
        max_window=max(cfg.get("windows", [5])),
    )
    return json.dumps(result)


@mcp.tool()
def suggest_refocus(messages_json: str, target_yaml: str) -> str:
    """
    Return up to 5 actionable suggestions to refocus the context toward the target.

    messages_json: JSON array of {role, content}
    target_yaml:   YAML string, file path, or plain goal text
    """
    cfg = _cfg_load()
    messages = json.loads(messages_json)
    target = _resolve_target(target_yaml)
    report = analyze(messages, target, cfg)

    if not report.suggestions:
        return "Context is well-aligned with the target. No refocusing needed."
    return "\n".join(f"  → {s}" for s in report.suggestions[:5])


# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve_target(target_input: str) -> Target:
    """Accept YAML string, file path, or plain text goal."""
    stripped = target_input.strip()
    # file path
    import os
    if os.path.isfile(stripped):
        return load_target(stripped)
    # YAML string
    try:
        data = yaml.safe_load(stripped)
        if isinstance(data, dict) and "goal" in data:
            import tempfile, os
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
                f.write(stripped)
                tmp = f.name
            t = load_target(tmp)
            os.unlink(tmp)
            return t
    except Exception:
        pass
    # plain text → derive
    return derive_target(stripped)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
