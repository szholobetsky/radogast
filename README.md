![radogast](images/radogast.png)

# Radogast — Context Drift Monitor

Universal static analyzer for AI agent sessions.

## Why Radogast

In Slavic mythology, Radogast is the solar deity of the Polabian Slavs — god of hospitality
and protection, guardian of travelers and merchants on their journeys. He is depicted in
helmet and chainmail, a prophetic bird upon his head, the head of an aurochs on his chest.
The prophetic bird watches without sleep; the sun he carries lights the path forward.

We named this tool after him because that is exactly what it does: it illuminates the path
of an AI agent through a task. A conversation has a direction — a goal stated at the start.
Radogast measures how far the current context has drifted from that origin, whether the
key ideas are present and defined, and whether the work is still moving toward the answer.
The sun does not bend. If the path has curved away, Radogast will say so.

Universal static analyzer for AI agent sessions. Monitors context drift from a target,
measures term coverage, detects process stage via marker words, and warns when a
conversation has left the task space.

Works with: 1bcoder, Claude, OpenCode, Codex, aider, Continue.dev, Gemini, pi,
nanocoder — any tool that can export message history as JSON.

## Install

```bash
pip install -e .
# with embedding support (recommended):
pip install -e ".[embed]"
```

## Quick start

```bash
# 1. Auto-generate a target from your task description
radogast target derive "develop REST API for visitor tracking at a café" -o task.yaml

# 2. Analyze a session
cat session.json | radogast analyze --target task.yaml

# 3. Watch a directory for live updates
radogast watch --target task.yaml --dir ~/.continue/history/

# 4. Start MCP server (connects to Claude, Continue.dev, Codex CLI)
radogast-mcp
```

## Target YAML format

```yaml
goal: "develop REST API for visitor tracking at a café"

key_terms: [REST, API, tracking, session, timestamp, visitor]

milestones:
  - name: domain_understood
    markers: [visitor, establishment, entry, exit, timestamp]
    evidence: "definition of visitor as an entry+exit event pair"
  - name: api_designed
    markers: [endpoint, POST, GET, response]
    evidence: "at least one endpoint with schema"

falsification:
  critical_tests:
    - "if visitor is never defined — problem not formulated"
    - "if no formula present — task unsolved"
  minimum_evidence:
    - at least one endpoint specification

out_of_scope: [authorization, billing, UI]
```

## Config (.radogast.yaml)

```yaml
windows: [1, 3, 5]           # message window sizes
drift_threshold_deg: 40       # alert above this angle
bias_threshold: 3.0           # term imbalance alert
embedding_model: "BAAI/bge-small-en-v1.5"   # fast, 22MB
hybrid: true                  # marker words + embeddings both
```

## MCP tools

| Tool | Description |
|---|---|
| `analyze_context(messages_json, target_yaml)` | Full report as JSON |
| `get_drift_score(messages_json, goal, key_terms)` | Quick angle check |
| `suggest_refocus(messages_json, target_yaml)` | Actionable suggestions |

## Output example

```
[radogast] target: develop REST API for visitor tracking

DRIFT:     23.4°  on_track
STAGE:     api_designed  votes={'api_designed': 3}

TERM COVERAGE  (4/6 defined)  ROUGE-1=0.71
  ✓ REST                  ████████████  defined
  ✓ API                   ██████████░░  defined
  ~ visitor               ████░░░░░░░░  mentioned
  ✗ average time          ░░░░░░░░░░░░  absent
  ✓ timestamp             ██████░░░░░░  defined
  ✓ session               ████████░░░░  defined

BALANCE:  bias=2.1x toward 'REST'

GLOSSARY (3/6 terms):
  REST: architectural style for web services using HTTP...
  session: pair of entry and exit events for one visitor...
  timestamp: Unix epoch in milliseconds, recorded at device level

SUGGESTED:
  → missing from context: average time — add definitions or examples
  → mentioned but not defined: visitor — add explicit definitions
```

---

## Part of the SIMARGL toolkit

radogast is one of five tools that together form an **intellectual development support system**:

| Tool | Role |
|---|---|
| **[simargl](https://github.com/szholobetsky/simargl)** | Task-to-code retrieval — given a task description, finds which files and modules are likely affected, using semantic similarity over git history |
| **[svitovyd](https://github.com/szholobetsky/svitovyd)** | Project map — scans any codebase and produces a structural map of definitions and cross-file dependencies; exposes it as an MCP server |
| **[1bcoder](https://github.com/szholobetsky/1bcoder)** | AI coding assistant for small local models — surgical context management, agents, parallel inference, proc scripts |
| **[yasna](https://github.com/szholobetsky/yasna)** | Session memory — indexes conversations from all AI agents so you can find what was discussed, when, and where |
| **[radogast](https://github.com/szholobetsky/radogast)** | Context drift monitor — measures how far an AI agent's conversation has drifted from the original task |

- **simargl** answers: *what code is related to this task?*
- **svitovyd** answers: *how is the code structured and what depends on what?*
- **1bcoder** answers: *how do I work with local models efficiently?*
- **yasna** answers: *where did I already discuss this?*
- **radogast** answers: *is the AI agent still on track toward the goal?*

Together they cover the full development loop: understand the codebase, find relevant history,
work with AI locally, remember what was decided, and verify the context stays on target.

---

## About

(c) 2026 Stanislav Zholobetskyi  
Institute for Information Recording, National Academy of Sciences of Ukraine, Kyiv  
PhD research: «Intelligent Technology for Software Development and Maintenance Support»
