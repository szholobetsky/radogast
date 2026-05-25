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
            "verification_fails": report.verification_fails,
            "oos_hits": report.oos_hits,
            "oos_recent": report.oos_recent,
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
    _TREND_ARROW = {"growing": "↑", "declining": "↓", "stable": "→",
                    "peak_early": "↘", "peak_late": "↗", "absent": " "}
    for term, status in report.term_coverage.items():
        c = _COV_COLOR.get(status, "")
        tr = report.term_trends.get(term, {})
        spark = tr.get("spark", "·····")
        trend = tr.get("trend", "")
        arrow = _TREND_ARROW.get(trend, " ")
        tc = _GRN if trend == "growing" else _RED if trend in ("declining", "peak_early") else _DIM
        icon = _TICK if status == "defined" else _WAVE if status == "mentioned" else _CROSS
        click.echo(f"  {c}{icon}{_R} {term:<20} {_DIM}{spark}{_R} {tc}{arrow}{_R}  {c}{status}{_R}")

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

    # milestones tree
    if report.milestone_trends:
        click.echo(f"\nMILESTONES:")
        for ms_name, mt in report.milestone_trends.items():
            is_current = ms_name == report.active_milestone
            cur_tag = f"  {_GRN}<- current{_R}" if is_current else ""
            ms_c = _GRN if is_current else _DIM
            click.echo(f"  {ms_c}{ms_name}{_R}{cur_tag}")
            marker_items = list(mt.get("markers", {}).items())
            for idx, (marker, mtr) in enumerate(marker_items):
                is_last = idx == len(marker_items) - 1
                branch = _u("└─", "+-") if is_last else _u("├─", "+-")
                indent = _u("   ", "   ") if is_last else _u("│  ", "|  ")
                spark = mtr.get("spark", "·····")
                trend = mtr.get("trend", "absent")
                active_marker = mtr.get("recent", 0) > 0
                if trend == "absent":
                    status = f"{_DIM}absent{_R}"
                elif active_marker:
                    status = f"{_GRN}active{_R}"
                else:
                    status = f"{_DIM}seen{_R}"
                click.echo(f"   {branch} {marker:<18} {_DIM}{spark}{_R}  {status}")

    # verification
    if report.verification_fails or report.verification_trends:
        click.echo(f"\nVERIFICATION:")
        for term in (report.verification_trends or {}):
            vt = report.verification_trends[term]
            spark = vt.get("spark", "·····")
            trend = vt.get("trend", "")
            arrow = _TREND_ARROW.get(trend, " ")
            failed = term in report.verification_fails
            c = _RED if failed else _GRN
            icon = _CROSS if failed else _TICK
            tc = _RED if trend in ("declining", "peak_early") else _GRN if trend == "growing" else _DIM
            click.echo(f"  {c}{icon}{_R} {term:<20} {_DIM}{spark}{_R} {tc}{arrow}{_R}"
                       + (f"  {_RED}ABSENT{_R}" if failed else ""))

    # out of scope
    if report.oos_hits:
        click.echo(f"\n{_YEL}OUT OF SCOPE:{_R}")
        for term, count in report.oos_hits.items():
            ot = report.oos_trends.get(term, {})
            spark = ot.get("spark", "·····")
            trend = ot.get("trend", "")
            arrow = _TREND_ARROW.get(trend, " ")
            if trend == "declining":
                click.echo(f"  {_DIM}~ {term:<20} {spark} {arrow}  fading{_R}")
            elif term in report.oos_recent or trend == "growing":
                click.echo(f"  {_RED}! {term:<20} {spark} {arrow}  GROWING{_R}")
            else:
                click.echo(f"  {_YEL}~ {term:<20} {spark} {arrow}{_R}")

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
    from radogast.target import Target, Milestone, Verification, target_to_yaml

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

    # ── verification ─────────────────────────────────────────────────────────
    click.echo(f"\n  Verification: terms that MUST appear in the context for the goal to be met.")
    click.echo(f"  (comma-separated, or press Enter to use key terms)")
    raw_f = click.prompt("  Mandatory terms", default="").strip()
    if raw_f:
        mandatory_terms = [t.strip() for t in raw_f.split(",") if t.strip()]
    else:
        mandatory_terms = key_terms[:3]
        click.echo(f"  using: {', '.join(mandatory_terms)}")

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
        verification=Verification(mandatory_terms=mandatory_terms),
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

    if report.drift_status == "critical" or report.verification_fails:
        sys.exit(2)


@main.command()
@click.option("--target", "-t", "target_path", default=None,
              help="Path to target YAML (default: .radogast/task.yaml).")
@click.option("--dir", "-d", "watch_dir", default=None,
              help="Directory to watch (default: ~/.yasna/index/ with auto yasna index).")
@click.option("--interval", default=5, help="Poll interval in seconds.")
@click.option("--format", "-f", "fmt", default="text",
              type=click.Choice(["text", "json"]))
def watch(target_path, watch_dir, interval, fmt):
    """Watch a directory for session updates and re-analyze on change.

    Without --dir: uses ~/.yasna/index/ and runs 'yasna index' before each cycle.
    With --dir: watches that directory as-is, no yasna index step.
    """
    import subprocess
    cfg = _cfg.load()
    if not target_path:
        found = _cfg.find_target()
        if not found:
            click.echo("[radogast] no target found. Run 'radogast init' or pass --target.", err=True)
            sys.exit(1)
        target_path = str(found)
        click.echo(f"[radogast] using target: {found}", err=True)
    target = load_target(target_path)

    auto_yasna = watch_dir is None
    if auto_yasna:
        watch_dir = str(Path.home() / ".yasna" / "index")
        click.echo(f"[radogast] mode: auto  (yasna index + {watch_dir})", err=True)
    else:
        click.echo(f"[radogast] mode: manual  ({watch_dir})", err=True)

    watch_path = Path(watch_dir)
    watch_path.mkdir(parents=True, exist_ok=True)
    last_mtime: dict[Path, float] = {}

    click.echo(f"[radogast] interval: {interval}s — Ctrl+C to stop", err=True)
    tick = 0
    _SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏" if _UTF8 else "-\\|/"
    try:
        while True:
            if auto_yasna:
                click.echo("\r  [1/2] yasna index...                    ", nl=False, err=True)
                try:
                    subprocess.run(["yasna", "index"], capture_output=True, timeout=30)
                except FileNotFoundError:
                    click.echo("\n[radogast] warning: yasna not found — skipping index step", err=True)
                    auto_yasna = False
                except subprocess.TimeoutExpired:
                    click.echo("\n[radogast] warning: yasna index timed out", err=True)
                click.echo("\r  [2/2] scanning sessions...              ", nl=False, err=True)

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
        if not t.verification.mandatory_terms:
            issues.append("warning: no verification.mandatory_terms")
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
