# first-graph

**Your first agent graph — without a framework.** Plus a tool that finds the waits in your pipeline that carry no data, and catches agents that report "done" when they aren't.

A small, readable companion to the graph-engineering wave. Everything here runs from one command, and the tests are real.

> Output and code comments are in Russian — this is a companion to a Russian-language video. The concepts, commands, and API are language-neutral; English output is on the roadmap.

---

## Why

Most multi-step agents are written as a straight line: step one, step two, step three — each politely waiting for the last. Half of those waits are fake: a step sits after its neighbor because that's the order you typed, not because it reads the neighbor's result. Those steps can run at the same time.

> You typed "and then." Your code heard "wait."

`first-graph` computes this **deterministically, with no LLM**: from declared inputs and outputs it builds the real dependency graph and shows what can run in parallel — and, crucially, **which of those waits actually cost you time.** Not every fake arrow costs money: if a branch finishes on time anyway, cutting it changes nothing. The tool shows both, so you can't pass cosmetics off as savings.

## Try it in 30 seconds

```bash
git clone https://github.com/edvardgrishin27/first-graph
cd first-graph
python3 -m first_graph demo
```

You'll get, for each arrow, whether it's real or a wasted wait, the levels that can run at once, and the resulting speedup.

Run it on your own pipeline — describe each step as what it reads and writes:

```json
[
  { "id": "clone",  "writes": ["repo"], "duration": 1 },
  { "id": "lint",   "reads": ["repo"], "writes": ["lint_ok"],  "duration": 4 },
  { "id": "tests",  "reads": ["repo"], "writes": ["tests_ok"], "duration": 12 },
  { "id": "report", "reads": ["lint_ok", "tests_ok"],          "duration": 1 }
]
```

```bash
python3 -m first_graph arrows my-pipeline.json
python3 -m first_graph arrows my-pipeline.json --workers 4   # honest speedup with a concurrency cap
```

Exit code: `0` — nothing to parallelize, `1` — fake waits found, `2` — bad input. CI-friendly.

## The four primitives

All of graph engineering rests on four things. No framework needed — just functions, a dict, and if-statements. [`first_graph/graph.py`](first_graph/graph.py) is a working implementation you can read in five minutes:

| Primitive | What it does |
|---|---|
| **State** | a plain dict that flows along the edges |
| **Node** | a function: state in, state out |
| **Router** | inspects state and picks a path — **routing lives in code, not in the model** |
| **Fan-out** | independent nodes run at once; a failed branch returns `None` instead of sinking the run |
| **Gate** | builder and reviewer are **different** nodes, with a retry cap |

The key: the model may make the decision, but **the routing itself is code**. Same input always takes the same path, and the model can't skip a check on its own.

## The reality anchor

Agents in a graph confirm each other with words: the first writes "done, tests pass," the second reads it and replies "confirmed." Nobody ran the tests.

`anchor` doesn't ask for an opinion — it checks:

```python
anchor(state, command=["pytest", "-q"])                    # decided by exit code
anchor(state, file="dist/app.apk", newer_than="src/")      # was it actually rebuilt
anchor(state, url="https://example.com/health", expect=200)
```

The point isn't what it can do — it's what it **refuses**. You can't pass a function:

```python
anchor(state, command=lambda s: s["agent_said_ok"])
# TypeError: an anchor is external evidence (a command, a file, a URL),
#            not someone's judgment
```

The constraint lives in the code, not the docs. And: **an anchor that couldn't verify counts as failed** — command not found, network down, timeout — all "no," not "close enough." See it live:

```bash
python3 examples/anchor_demo.py
```

Three agents report success; the anchor runs the real pytest on real code with a real bug — and stops the graph. *Agents agreed. Reality didn't.*

## Is a second reviewer worth it?

Every article says: put a second reviewer on a smarter model to catch what the first missed. Reasonable. But paying twice is only worth it if it catches more **on your data**. [`first_graph/extras/second_judge.py`](first_graph/extras/second_judge.py) answers exactly that — through `claude -p`, **no API keys**, on your own Claude subscription.

```bash
python3 examples/second_judge_demo.py            # stubs, free
python3 examples/second_judge_demo.py --live      # live run on your models
```

Truth about the bug comes from pytest (the same `anchor`), not a third model. Only flawed solutions enter the comparison. And it doesn't pretend to tell self-preference from just-different-blind-spots — for a spending decision that doesn't matter, and it says so.

## Bridge to a code knowledge graph

The word "graph" in this wave means two different things — the graph of *agent orchestration* and the graph of *code knowledge* (what depends on what). Nobody connected them. [`first_graph/extras/graph_bridge.py`](first_graph/extras/graph_bridge.py) does.

Feed it a `graph.json` (node-link format, e.g. from [Graphify](https://github.com/Graphify-Labs/graphify)) and it does two things:

1. **Splits work by community, not by file.** "One agent per file" on a real repo is a thousand agents. Communities of related code give you a dozen meaningful chunks.
2. **Verifies an agent's findings against the graph.** The agent claims "A imports B" — does that edge exist? No? Then the agent made it up. `INFERRED` edges are flagged separately from `EXTRACTED` ones: a resolver's guess isn't passed off as a fact.

```bash
python3 examples/graph_bridge_demo.py
```

A reality anchor, but for claims about code: truth comes from a deterministic parser, not a second model.

## Cost by node

[`first_graph/extras/invoice.py`](first_graph/extras/invoice.py) doesn't measure anything — this library never calls a model. It takes the usage report from **your** real run and breaks it down by node. Prices require a `checked_on` date, or it refuses: a cost with no date is an unreproducible benchmark.

## Tests

```bash
python3 -m pytest tests/ -q
```

Not for show:
- [`tests/test_arrows.py`](tests/test_arrows.py) reproduces the case this was built for numerically.
- [`tests/test_anchors.py`](tests/test_anchors.py) checks not "it works" but "you can't fool it": passing an opinion fails, a check that couldn't run counts as failed.
- [`tests/test_frozen_rules.py`](tests/test_frozen_rules.py) is a frozen rule: the core stays under 800 lines and pulls in nothing outside the standard library — a rule we're not allowed to loosen for ourselves.

## Core and extras

- **Core** — `first_graph/*.py`. What you need to read to understand the tool. Under 800 lines, standard library only.
- **Extras** — `first_graph/extras/`. Useful but not required to understand it.

The core never imports extras — the dependency is strictly one-way, verified by a test. Delete `extras/` and the core still works.

## Limitations — honestly

- **It doesn't guess your dependencies.** You declare `reads` and `writes` by hand. Lie in the description and the report lies too.
- **It doesn't read your code.** It works from a pipeline description, not from source.
- **It doesn't track side effects.** Two steps that write the same file without declaring it are treated as independent — declare shared resources explicitly (the race detector catches same-level collisions on declared keys).
- **Time estimates are idealized.** The critical path ignores network and queues; use `--workers N` for a cap-aware number.
- **`graph.py` is a teaching implementation.** For production load, backoff retries, and durable state between crashes, use LangGraph or similar.

## License

MIT — take it, fork it, use it in your projects.
