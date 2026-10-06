# Azure DevOps AI Agent

An evidence-driven Azure DevOps audit and sprint-intelligence agent orchestrated by LangGraph and Gemini.

## Architecture

```text
                         Azure DevOps REST API
                                  │
                              config.py
                                  │
                               tools.py
                         ┌────────┴────────┐
                         │                 │
                  review_board      investigate_board
                         │                 │
                 board_review.py    adaptive_audit.py
                         │                 │
                   sprint_health.py      │
                         └────────┬────────┘
                                  │
                               audit.py
                                  │
                               wiki.py
                                  │
                            Azure DevOps Wiki

                         graph.py orchestrates all of the above
                         main.py is the CLI/presentation layer
```

### Module responsibilities

- `config.py` — one source for Azure DevOps settings, API version, URLs and timeout.
- `tools.py` — Azure DevOps API tools, deterministic Board Review entry point and mutation operations.
- `sprint_health.py` — deterministic sprint timing, progress, aging, deadline and workload calculations.
- `board_review.py` — deterministic board aggregation and RAID preparation.
- `adaptive_audit.py` — lightweight exploratory analysis for patterns outside the baseline checklist.
- `audit.py` — audit IDs and polished executive/operation report rendering.
- `wiki.py` — Wiki page publishing/update and API error handling.
- `graph.py` — LangGraph orchestration, adaptive tool selection and mutation confirmation.
- `state.py` — shared typed graph state.
- `model.py` — Gemini model configuration.
- `prompts.py` — agent policy, evidence rules and adaptive-investigation behavior.
- `main.py` — CLI input/output only.

## Audit model

The agent follows:

```text
DISCOVER → TRIAGE → INVESTIGATE → VALIDATE → ASSESS → REPORT
```

`review_board` provides the deterministic baseline. Gemini is allowed to notice other unusual patterns and choose additional read-only investigation when useful. `investigate_board` supports focused exploration such as deadlines, workload, duplicates, dependencies and state patterns, but the focus is only a hint rather than a fixed checklist.

The key design rule is:

> **Be flexible about what to investigate, but strict about what to claim.**

Exploratory findings are evidence-backed observations. They are not automatically classified as defects, blockers or risks. A potential duplicate title is not a proven duplicate; concentrated ownership is not proof of overload; dependency presence is not proof of blockage.

## Evidence rules

Azure DevOps is the source of truth.

- `OBSERVED` — directly returned by Azure DevOps or deterministically calculated from observed data.
- `INFERRED` — interpretation derived from observed evidence.
- `UNKNOWN` — cannot be verified from available data.

Missing timestamps, dependency information or hierarchy data are never treated as negative evidence.

Numerical Board Review metrics are calculated by Python. Gemini may select tools and interpret evidence, but it must not replace deterministic calculations with guesses.

## Board Review

The executive report adapts to the evidence. It can include sprint health, delivery outlook, deadline exposure, workload concentration, aging, RAID and exploratory observations when those sections add value. It avoids debug-style date-coverage telemetry and repeated copies of the same issue.

Delivery outlook compares observed completion pace with the pace required to finish the current unfinished scope. It is a deterministic pressure indicator, not a forecast.

## Tool-use policy

Read-only tools may run automatically. The agent should use the smallest number of tools needed to establish or reject a meaningful hypothesis and should stop when evidence is sufficient. It should not call every tool merely because the tool exists.

State-changing operations require explicit confirmation. After confirmation, the exact saved payload is executed; Gemini does not reconstruct it.

## Testing

Run from the repository directory:

```bash
python -m pytest -q test_audit_report.py test_adaptive_audit.py
python -m compileall -q .
```

The regression suite covers report formatting, deterministic metrics, deadline filtering, UNKNOWN activity handling, RAID grouping, workload denominators, adaptive exploratory findings, and dependency/duplicate evidence handling.

## Stabilization baseline

The repository is intentionally kept cohesive rather than split into many small modules.
Connection settings are centralized in `config.py`; Azure HTTP calls reuse a `requests.Session`;
report calculations remain deterministic; adaptive investigation remains read-only; and Wiki
publishing remains owned by the audit flow.

Before release, run:

```text
python -m pytest -q
python -m compileall -q .
```

The test suite is the regression gate for cleanup changes. Refactors should not alter audit
semantics, evidence classification, mutation-confirmation rules, or Wiki publication ownership.
