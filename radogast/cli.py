"""CLI entry point: radogast init | analyze | watch | target derive | target validate"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

import click
import yaml

from radogast import config as _cfg
from radogast.target import load_target, derive_target, target_to_yaml, load_messages
from radogast.analyzer import analyze, RadogastReport

# ── encoding-safe output ──────────────────────────────────────────────────────
import sys as _sys
_UTF8 = (getattr(_sys.stdout, "encoding", "") or "").lower().replace("-", "") in ("utf8", "utf-8")

def _u(utf_str: str, ascii_str: str) -> str:
    return utf_str if _UTF8 else ascii_str

_SEP   = _u("─", "-")
_TICK  = _u("✓", "+")
_CROSS = _u("✗", "x")
_WAVE  = "~"
_FULL  = _u("█", "#")
_EMPTY = _u("░", ".")
_ARR   = _u("→", "->")

# ── colour helpers ────────────────────────────────────────────────────────────
_R = "\033[0m"
_RED = "\033[91m"
_YEL = "\033[93m"
_GRN = "\033[92m"
_CYA = "\033[96m"
_DIM = "\033[2m"

_STATUS_COLOR = {
    "on_track": _GRN,
    "warning": _YEL,
    "critical": _RED,
    "no_embeddings": _DIM,
    "disabled": _DIM,
}
_COV_COLOR = {"defined": _GRN, "mentioned": _YEL, "absent": _RED}


def _bar(value: float, width: int = 12) -> str:
    filled = int(round(value * width))
    return _FULL * filled + _EMPTY * (width - filled)


def _print_report(report: RadogastReport, target_goal: str, fmt: str):
    if fmt == "json":
        out = {
            "drift_angle": report.drift_angle,
            "drift_status": report.drift_status,
            "active_milestone": report.active_milestone,
            "term_coverage": report.term_coverage,
            "coverage_ratio": report.coverage_ratio,
            "rouge1": report.rouge1,
            "balance": report.balance,
            "glossary": {k: v for k, v in report.glossary.items() if v},
            "falsification_fails": report.falsification_fails,
            "suggestions": report.suggestions,
        }
        click.echo(json.dumps(out, ensure_ascii=False, indent=2))
        return

    # text output
    click.echo(f"\n{_CYA}[radogast]{_R} target: {target_goal[:80]}")
    click.echo(_SEP * 60)

    # drift
    ds = report.drift_status
    dc = _STATUS_COLOR.get(ds, "")
    if report.drift_angle is not None:
        click.echo(f"DRIFT:    {dc}{report.drift_angle:5.1f}°  {ds}{_R}")
    else:
        click.echo(f"DRIFT:    {_DIM}embeddings not available — marker-only mode{_R}")

    # milestone
    if report.active_milestone:
        click.echo(f"STAGE:    {_CYA}{report.active_milestone}{_R}  "
                   f"{_DIM}votes={report.milestone_votes}{_R}")
    else:
        click.echo(f"STAGE:    {_DIM}no milestone detected{_R}")

    # coverage
    click.echo(f"\nTERM COVERAGE  ({len([v for v in report.term_coverage.values() if v=='defined'])}"
               f"/{len(report.term_coverage)} defined)  ROUGE-1={report.rouge1:.2f}")
    for term, status in report.term_coverage.items():
        c = _COV_COLOR.get(status, "")
        freq = report.balance["freqs"].get(term, 0)
        bar = _bar(min(freq / 10, 1.0))
        icon = _TICK if status == "defined" else _WAVE if status == "mentioned" else _CROSS
        click.echo(f"  {c}{icon}{_R} {term:<22} {_DIM}{bar}{_R}  {c}{status}{_R}")

    # balance
    bias = report.balance["bias"]
    if bias > 1.0:
        bc = _YEL if bias < 3.0 else _RED
        click.echo(f"\nBALANCE:  {bc}bias={bias:.1f}x toward '{report.balance['biased_toward']}'{_R}")

    # glossary
    has_defs = {k: v for k, v in report.glossary.items() if v}
    if has_defs:
        click.echo(f"\nGLOSSARY ({len(has_defs)}/{len(report.glossary)} terms):")
        for term, defn in list(has_defs.items())[:5]:
            snippet = (defn[:90] + "…") if defn and len(defn) > 90 else defn
            click.echo(f"  {term}: {_DIM}{snippet}{_R}")

    # falsification
    if report.falsification_fails:
        click.echo(f"\n{_RED}FAILS:{_R}")
        for f in report.falsification_fails:
            click.echo(f"  {_RED}{_CROSS}{_R} {f}")

    # suggestions
    if report.suggestions:
        click.echo(f"\nSUGGESTED:")
        for sg in report.suggestions:
            click.echo(f"  {_ARR} {sg}")

    click.echo()


# ── commands ──────────────────────────────────────────────────────────────────

@click.group()
def main():
    """Radogast — context drift monitor for AI agent sessions."""


# ── init ──────────────────────────────────────────────────────────────────────

@main.command("init")
@click.option("--dir", "init_dir", default=".", help="Directory to initialize (default: cwd).")
def init_cmd(init_dir):
    """Create .radogast/task.yaml by answering a few questions."""
    from radogast.target import Target, Milestone, Falsification, target_to_yaml

    out_dir = Path(init_dir).resolve() / ".radogast"
    task_file = out_dir / "task.yaml"

    if task_file.exists():
        if not click.confirm(f"[radogast] {task_file} already exists. Overwrite?", default=False):
            click.echo("[radogast] aborted.")
            return

    click.echo(f"\n[radogast] Initializing project target in {out_dir.relative_to(Path(init_dir).resolve()) if init_dir == '.' else out_dir}\n")

    # ── goal ──────────────────────────────────────────────────────────────────
    goal = click.prompt("  Goal (one sentence describing what this session/project should achieve)")
    goal = goal.strip()

    # ── key terms ─────────────────────────────────────────────────────────────
    click.echo(f"\n  Key terms: concepts/modules/technologies that MUST appear in the context.")
    click.echo(f"  (comma-separated, or press Enter to auto-detect from goal)")
    raw_terms = click.prompt("  Key terms", default="").strip()
    if raw_terms:
        key_terms = [t.strip() for t in raw_terms.split(",") if t.strip()]
    else:
        t = derive_target(goal)
        key_terms = t.key_terms
        click.echo(f"  auto-detected: {', '.join(key_terms)}")

    # ── milestones ────────────────────────────────────────────────────────────
    click.echo(f"\n  Milestones: named stages of progress (e.g. design, implementation, testing).")
    click.echo(f"  (comma-separated, or press Enter to skip)")
    raw_ms = click.prompt("  Milestones", default="").strip()
    milestones: list[Milestone] = []
    if raw_ms:
        for ms_name in [m.strip() for m in raw_ms.split(",") if m.strip()]:
            click.echo(f"\n  Milestone '{ms_name}':")
            click.echo(f"  Marker words — words that appear in messages when this stage is active.")
            raw_markers = click.prompt(f"    Markers for '{ms_name}' (comma-separated, or Enter to skip)", default="").strip()
            markers = [m.strip() for m in raw_markers.split(",") if m.strip()] if raw_markers else []
            milestones.append(Milestone(name=ms_name, markers=markers))

    # ── falsification ─────────────────────────────────────────────────────────
    click.echo(f"\n  Falsification: what would PROVE this goal was NOT met?")
    click.echo(f"  (comma-separated conditions, or press Enter to auto-generate from key terms)")
    raw_f = click.prompt("  Critical tests", default="").strip()
    if raw_f:
        critical_tests = [t.strip() for t in raw_f.split(",") if t.strip()]
    else:
        critical_tests = [
            f"result contains no mention of '{t}'" for t in key_terms[:3]
        ]
        click.echo(f"  auto-generated: {'; '.join(critical_tests)}")

    min_evidence = [f"at least one concrete statement about {key_terms[0]}"] if key_terms else ["task addressed"]

    # ── out of scope ──────────────────────────────────────────────────────────
    click.echo(f"\n  Out of scope: topics that should NOT appear / drift into.")
    click.echo(f"  (comma-separated, or press Enter to skip)")
    raw_oos = click.prompt("  Out of scope", default="").strip()
    out_of_scope = [s.strip() for s in raw_oos.split(",") if s.strip()] if raw_oos else []

    # ── write ─────────────────────────────────────────────────────────────────
    target = Target(
        goal=goal,
        key_terms=key_terms,
        milestones=milestones,
        falsification=Falsification(critical_tests=critical_tests, minimum_evidence=min_evidence),
        out_of_scope=out_of_scope,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    task_file.write_text(target_to_yaml(target), encoding="utf-8")

    click.echo(f"\n[radogast] {task_file} written.")
    click.echo(f"[radogast] To analyze: radogast analyze")
    click.echo(f"[radogast] To edit manually: {task_file}")
    click.echo()


# ── clear ────────────────────────────────────────────────────────────────────

@main.command("clear")
@click.option("--dir", "clear_dir", default=".", help="Project directory (default: cwd).")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def clear_cmd(clear_dir, yes):
    """Remove .radogast/task.yaml so a new task can be initialized."""
    task_file = Path(clear_dir).resolve() / ".radogast" / "task.yaml"

    if not task_file.exists():
        click.echo("[radogast] no task.yaml found — nothing to clear.")
        return

    if not yes:
        click.echo(f"[radogast] will remove: {task_file}")
        if not click.confirm("Continue?", default=False):
            click.echo("[radogast] aborted.")
            return

    task_file.unlink()
    click.echo("[radogast] task.yaml removed.")
    click.echo("[radogast] Run 'radogast init' to define the next task.")


# ── session auto-detection ────────────────────────────────────────────────────

def _find_recent_session(agent: str | None = None) -> Path | None:
    """Return most recently modified yasna session for the current project."""
    from pathlib import Path as _Path
    index_dir = _Path.home() / ".yasna" / "index"
    if not index_dir.exists():
        return None

    cwd = str(_Path.cwd().resolve()).lower().replace("\\", "/").rstrip("/")

    candidates: list[tuple[float, _Path]] = []
    pattern = f"{agent}/*.txt" if agent else "**/*.txt"
    for f in index_dir.glob(pattern):
        try:
            from yasna.core import read_meta
            meta = read_meta(f)
            pp = meta.get("project_path", "").lower().replace("\\", "/").rstrip("/")
            # prefer exact project match; fall back to any session
            if pp == cwd or pp.startswith(cwd + "/") or cwd.startswith(pp + "/"):
                candidates.append((f.stat().st_mtime, f))
        except Exception:
            continue

    if not candidates:
        # no project match — return most recent overall
        for f in index_dir.glob(pattern):
            try:
                candidates.append((f.stat().st_mtime, f))
            except Exception:
                continue

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


# ── analyze ───────────────────────────────────────────────────────────────────

@main.command("analyze")
@click.option("--target", "-t", "target_path", default=None,
              help="Path to target YAML (default: .radogast/task.yaml).")
@click.option("--input", "-i", "input_path", default=None,
              help="Path to messages file. Default: most recent yasna session.")
@click.option("--agent", "-a", default=None,
              help="Filter session search by agent (claude, gemini, …).")
@click.option("--format", "-f", "fmt", default="text",
              type=click.Choice(["text", "json"]), help="Output format.")
@click.option("--config", "cfg_path", default=None, help="Config YAML override.")
def analyze_cmd(target_path, input_path, agent, fmt, cfg_path):
    """Analyze a session for context drift and term coverage."""
    cfg = _cfg.load()
    if cfg_path:
        with open(cfg_path) as f:
            cfg.update(yaml.safe_load(f) or {})

    if not target_path:
        found = _cfg.find_target()
        if not found:
            click.echo(
                "[radogast] no target found. Run 'radogast init' to create .radogast/task.yaml\n"
                "           or pass --target <file>",
                err=True,
            )
            sys.exit(1)
        target_path = str(found)
        click.echo(f"[radogast] using target: {found}", err=True)

    if not input_path:
        session = _find_recent_session(agent)
        if not session:
            click.echo(
                "[radogast] no indexed sessions found.\n"
                "           Run 'yasna index' first, or pass --input <file>.",
                err=True,
            )
            sys.exit(1)
        input_path = str(session)
        click.echo(f"[radogast] using session: {session}", err=True)

    target = load_target(target_path)
    messages = load_messages(input_path)
    if not messages:
        click.echo("[radogast] no messages found", err=True)
        sys.exit(1)

    report = analyze(messages, target, cfg)
    _print_report(report, target.goal, fmt)

    if report.drift_status == "critical" or report.falsification_fails:
        sys.exit(2)


@main.command()
@click.option("--target", "-t", "target_path", default=None,
              help="Path to target YAML (default: .radogast/task.yaml).")
@click.option("--dir", "-d", "watch_dir", required=True,
              help="Directory to watch for session files.")
@click.option("--interval", default=5, help="Poll interval in seconds.")
@click.option("--format", "-f", "fmt", default="text",
              type=click.Choice(["text", "json"]))
def watch(target_path, watch_dir, interval, fmt):
    """Watch a directory for session updates and re-analyze on change."""
    cfg = _cfg.load()
    if not target_path:
        found = _cfg.find_target()
        if not found:
            click.echo("[radogast] no target found. Run 'radogast init' or pass --target.", err=True)
            sys.exit(1)
        target_path = str(found)
        click.echo(f"[radogast] using target: {found}", err=True)
    target = load_target(target_path)
    watch_path = Path(watch_dir)
    last_mtime: dict[Path, float] = {}

    click.echo(f"[radogast] watching {watch_dir} every {interval}s — Ctrl+C to stop")
    tick = 0
    _SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏" if _UTF8 else "-\\|/"
    try:
        while True:
            changed = []
            for fpath in sorted(
                list(watch_path.glob("**/*.json")) +
                list(watch_path.glob("**/*.txt"))
            ):
                mtime = fpath.stat().st_mtime
                if last_mtime.get(fpath) != mtime:
                    last_mtime[fpath] = mtime
                    changed.append(fpath)

            if changed:
                for fpath in changed:
                    click.echo(f"\n[radogast] changed: {fpath.name}", err=True)
                    try:
                        messages = load_messages(str(fpath))
                        if messages:
                            report = analyze(messages, target, cfg)
                            _print_report(report, target.goal, fmt)
                        else:
                            click.echo(f"  [skip] no messages in {fpath.name}", err=True)
                    except Exception as e:
                        click.echo(f"  [skip] {fpath.name}: {e}", err=True)
            else:
                spin = _SPIN[tick % len(_SPIN)]
                ts = time.strftime("%H:%M:%S")
                click.echo(f"\r  {spin} watching {watch_dir}  {ts}  (next in {interval}s)  ",
                           nl=False, err=True)
                tick += 1

            time.sleep(interval)
    except KeyboardInterrupt:
        click.echo("\n[radogast] stopped")


@main.group()
def target():
    """Target management commands."""


@target.command("derive")
@click.argument("prompt_text")
@click.option("--output", "-o", default=None, help="Write YAML to this file.")
def target_derive(prompt_text, output):
    """Auto-generate a minimal target YAML from a plain-text prompt."""
    t = derive_target(prompt_text)
    yaml_text = target_to_yaml(t)
    if output:
        Path(output).write_text(yaml_text, encoding="utf-8")
        click.echo(f"[radogast] target saved → {output}")
    else:
        click.echo(yaml_text)


@target.command("validate")
@click.argument("target_path")
def target_validate(target_path):
    """Check that a target YAML has the required fields."""
    try:
        t = load_target(target_path)
        issues = []
        if not t.goal:
            issues.append("missing: goal")
        if not t.key_terms:
            issues.append("warning: no key_terms")
        if not t.falsification.critical_tests:
            issues.append("warning: no falsification.critical_tests")
        if issues:
            for i in issues:
                click.echo(f"  {'✗' if i.startswith('missing') else '!'} {i}")
        else:
            click.echo(f"[radogast] {target_path} — valid ✓")
            click.echo(f"  goal: {t.goal[:80]}")
            click.echo(f"  key_terms: {len(t.key_terms)}")
            click.echo(f"  milestones: {len(t.milestones)}")
    except Exception as e:
        click.echo(f"[radogast] error: {e}", err=True)
        sys.exit(1)
