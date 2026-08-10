# Evals

A second, opt-in tier on top of `backend/tests/`.

## Tier 1 (`tests/`) vs Tier 2 (`evals/`)

`tests/` is deterministic unit tests plus LLM-*stubbed* contract tests — free, fast,
part of the `ruff check && pytest` CI gate, and expected to pass on every commit.

`evals/` calls the **real** Anthropic API and scores quality/grounding/trajectory
rather than asserting exact output. These are non-deterministic, cost real tokens,
and produce a judged score rather than a hard pass/fail contract — they are not part
of the CI gate. `testpaths` in `pyproject.toml` is `["tests"]`, so a plain `pytest`
never collects anything under `evals/`.

## Running

Provider defaults to Gemini for both the agent and the judge (`GEMINI_API_KEY` via
`.env` or the shell). A case skips cleanly if the selected provider's key isn't
configured. `evals/harness.py`'s `build_agent_llm`/`build_judge_llm` are separate
builders — grading is never done by the same LLM instance that produced the output
being graded — each independently overridable via `EVAL_AGENT_PROVIDER` /
`EVAL_JUDGE_PROVIDER` (`anthropic` | `gemini` | `openai`).

```bash
pytest evals -m eval                                    # all evals, gemini/gemini
EVAL_JUDGE_PROVIDER=anthropic pytest evals -m eval       # gemini agent, anthropic judge
pytest evals -m eval -k trajectories                     # one category
pytest evals -m eval -k correct_answer_no_remediation    # one case
```

## What's covered

- **`test_trajectories.py`** (`datasets/trajectories.yaml`, `graders/trajectory.py`)
  — glass-box: does the real model's tool-call order for a turn match the intended
  policy (evaluate before remediating, PII gate before persisting a fact, session-open
  turns never call `evaluate_response`)? Ground truth is the ordered list of tool
  calls/persisted events, not LangGraph node visits — the orchestrator's own tool
  order is agent-decided, not fixed graph edges (see
  `app/agent/orchestrator/__init__.py`'s module docstring), so this is checking
  whether the real model still reproduces the intended policy, which a fixed-graph
  test can't exercise.

- **`test_grounding.py`** (`datasets/remediation_grounding.yaml`, `graders/grounding.py`)
  — faithfulness: runs the real SOP retrieval + the real paraphrasing LLM call
  (`deliver_reply`), then an LLM judge checks every factual claim in the composed
  explanation is entailed by its cited excerpt (entailed / unsupported /
  contradicted). Also covers the abstain path — a question with no matching SOP
  content must produce a refusal, never a fabricated citation.

- **`test_conversation_quality.py`** (`datasets/conversation_quality.yaml`, `graders/judge.py`)
  — general LLM-as-judge: does the rendered reply read the way a frontline employee
  would expect (short, professional, friendly, engaging), does it correctly reflect
  the turn's actual grading classification, and does its next step match what
  actually happened this turn. Three dimensions, scored 1-5, pass threshold 4.

## Adding a case

Append an entry to the relevant `datasets/*.yaml` file — no code change needed
unless you're introducing a new grading dimension. Use a real `kc_id` from
`app/kg/graph.yaml` (`SAF.001` has no prerequisites, so it's always assessable).

## Non-goals

No third-party eval framework (DeepEval/Braintrust/promptfoo/LangSmith) — plain
pytest + Pydantic-graded LLM judges is enough for this scope. No adversarial/safety
eval set yet (flagged as a possible future addition, not built). No scheduled CI job
wiring — run manually for now.
