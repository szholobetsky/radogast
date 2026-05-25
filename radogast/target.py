"""Target schema: load from YAML, auto-derive from plain text prompt."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class Milestone:
    name: str
    markers: list[str] = field(default_factory=list)
    evidence: str = ""


@dataclass
class Verification:
    mandatory_terms: list[str] = field(default_factory=list)


@dataclass
class Target:
    goal: str
    key_terms: list[str] = field(default_factory=list)
    milestones: list[Milestone] = field(default_factory=list)
    marker_words: dict[str, list[str]] = field(default_factory=dict)
    verification: Verification = field(default_factory=Verification)
    out_of_scope: list[str] = field(default_factory=list)


# ── loader ────────────────────────────────────────────────────────────────────

def load_target(path: str) -> Target:
    with open(path, encoding="utf-8") as f:
        try:
            data: dict = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(
                f"Invalid YAML in {path}: {e}\n"
                "Tip: wrap values containing backticks or special chars in quotes."
            ) from e

    milestones = [
        Milestone(
            name=m["name"],
            markers=m.get("markers", []),
            evidence=m.get("evidence", ""),
        )
        for m in data.get("milestones", [])
    ]

    raw_f = data.get("verification", [])
    if isinstance(raw_f, list):
        mandatory_terms = raw_f
    else:
        mandatory_terms = raw_f.get("mandatory_terms", [])
    verification = Verification(mandatory_terms=mandatory_terms)

    return Target(
        goal=data.get("goal", ""),
        key_terms=data.get("key_terms", []),
        milestones=milestones,
        marker_words=data.get("marker_words", {}),
        verification=verification,
        out_of_scope=data.get("out_of_scope", []),
    )


# ── auto-derive from prompt text (no LLM) ────────────────────────────────────

_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "to", "of", "in", "on", "at",
    "by", "with", "from", "that", "this", "is", "are", "be", "as", "it",
    "its", "i", "we", "you", "me", "my", "our", "your", "will", "can",
    "do", "does", "create", "build", "make", "develop", "write", "design",
    "implement", "generate", "produce", "about", "into", "via", "using",
    # Ukrainian
    "та", "і", "або", "що", "як", "це", "для", "до", "на", "по",
    "з", "зі", "із", "у", "в", "при", "про", "щоб", "але",
}

_INTENT_VERBS = [
    "write", "create", "build", "develop", "implement", "design",
    "analyze", "explain", "compare", "refactor", "fix", "debug",
    "написати", "створити", "побудувати", "розробити", "реалізувати",
    "пояснити", "порівняти", "виправити", "проаналізувати",
]


def derive_target(prompt_text: str) -> Target:
    """Extract a minimal Target from any prompt text without LLM."""
    text = prompt_text.strip()

    # intent verb (first match wins)
    intent = next((v for v in _INTENT_VERBS if re.search(rf'\b{v}\b', text, re.IGNORECASE)), "")

    # extract candidate nouns: capitalized words, technical terms, quoted phrases
    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
    quoted_terms = [q[0] or q[1] for q in quoted]

    words = re.findall(r'\b[A-Za-zА-Яа-яІіЇїЄєҐґ][A-Za-zА-Яа-яІіЇїЄєҐґ\-]{2,}\b', text)
    key_terms = list(dict.fromkeys(
        [w for w in words if w.lower() not in _STOPWORDS and w.lower() not in _INTENT_VERBS]
        + quoted_terms
    ))[:12]

    goal = text.split("\n")[0][:120]

    verification = Verification(mandatory_terms=key_terms[:3])

    return Target(
        goal=goal,
        key_terms=key_terms,
        verification=verification,
    )


def target_to_yaml(target: Target) -> str:
    data: dict[str, Any] = {"goal": target.goal}
    if target.key_terms:
        data["key_terms"] = target.key_terms
    if target.milestones:
        data["milestones"] = [
            {"name": m.name, "markers": m.markers, "evidence": m.evidence}
            for m in target.milestones
        ]
    if target.marker_words:
        data["marker_words"] = target.marker_words
    if target.verification.mandatory_terms:
        data["verification"] = target.verification.mandatory_terms
    if target.out_of_scope:
        data["out_of_scope"] = target.out_of_scope
    return yaml.dump(data, allow_unicode=True, sort_keys=False)


# ── message loaders ───────────────────────────────────────────────────────────

def load_messages(source: str) -> list[dict]:
    """Load messages from JSON file or stdin (-). Returns list of {role, content} dicts."""
    if source == "-":
        import sys
        raw = sys.stdin.read()
    else:
        raw = Path(source).read_text(encoding="utf-8")

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "messages" in data:
            return data["messages"]
    except json.JSONDecodeError:
        pass

    # yasna indexed format:
    #   :::agent: claude
    #   :::date: 2026-05-19
    #   ---
    #   [user] text...   OR   === user ===\ntext...  (1bcoder ctx format)
    if raw.startswith(":::") or "\n---\n" in raw:
        body = raw.split("\n---\n", 1)[-1]
        messages = []
        role = "user"
        buf: list[str] = []
        for line in body.splitlines():
            # [user] / [assistant] — yasna claude/aider/... format
            m = re.match(r'^\[(user|assistant|human|model)\]\s*(.*)', line, re.IGNORECASE)
            if m:
                if buf:
                    messages.append({"role": role, "content": "\n".join(buf).strip()})
                    buf = []
                raw_role = m.group(1).lower()
                role = "assistant" if raw_role in ("assistant", "model") else "user"
                if m.group(2):
                    buf.append(m.group(2))
                continue
            # === user === / === assistant === — 1bcoder ctx format
            m2 = re.match(r'^===\s*(user|assistant|system)\s*===\s*$', line, re.IGNORECASE)
            if m2:
                if buf:
                    messages.append({"role": role, "content": "\n".join(buf).strip()})
                    buf = []
                role = "assistant" if m2.group(1).lower() == "assistant" else "user"
                continue
            buf.append(line)
        if buf:
            messages.append({"role": role, "content": "\n".join(buf).strip()})
        return [m for m in messages if m["content"].strip()]

    # 1bcoder ctx format without yasna wrapper (raw ctx file passed directly)
    if "=== user ===" in raw or "=== assistant ===" in raw:
        messages = []
        role = "user"
        buf: list[str] = []
        for line in raw.splitlines():
            m = re.match(r'^===\s*(user|assistant|system)\s*===\s*$', line, re.IGNORECASE)
            if m:
                if buf:
                    messages.append({"role": role, "content": "\n".join(buf).strip()})
                    buf = []
                role = "assistant" if m.group(1).lower() == "assistant" else "user"
            else:
                buf.append(line)
        if buf:
            messages.append({"role": role, "content": "\n".join(buf).strip()})
        return [m for m in messages if m["content"].strip()]

    # fallback: markdown "**User:**" / "**Assistant:**"
    messages = []
    role = "user"
    buf = []
    for line in raw.splitlines():
        m = re.match(r'\*\*(User|Assistant|Human|AI)\*\*:?\s*(.*)', line, re.IGNORECASE)
        if m:
            if buf:
                messages.append({"role": role, "content": "\n".join(buf).strip()})
                buf = []
            role = "user" if m.group(1).lower() in ("user", "human") else "assistant"
            if m.group(2):
                buf.append(m.group(2))
        else:
            buf.append(line)
    if buf:
        messages.append({"role": role, "content": "\n".join(buf).strip()})
    return messages
