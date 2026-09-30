# Swimming Safety Verification Benchmark

This benchmark asks an LLM to create a swimming-safety plan and uses Alloy to
check it against `safety_protocol.als`.

## How it works

Step 1, once per prompt, before any plan: the prompt is formalized over
`safety_protocol.als` itself as the vocabulary (its signatures and fields, not
its rules) by the auto-formalization roundtrip (`../pipeline.py`). The formal
query is released when Alloy proves y_original <-> y_prime and NLI finds no
drift between the prompt and the readback. On drift an LLM diagnoses the cause;
VOCABULARY (the protocol has no word for something the prompt says) adds checked
extension words (`QueryExt`), TRANSLATION reruns as is; at most 5 roundtrips.
Results live in `query_stages/<id>/` and are reused for the same prompt text and
protocol file (`--reformalize` recomputes). A prompt whose formal query is not
released gets no plan (`UNVERIFIED_QUERY`); `--no-formal-query` skips step 1.

Then, for each prompt and trial:

1. The LLM generates `pred GeneratedPlan { ... }` from the prompt and its formal
   query; the verifier file opens the query's extension words too.
2. Alloy checks the plan.
3. If the plan is unsafe or invalid, Alloy feedback is sent to the LLM.
4. The process stops when the plan is safe or `--max-iters` is reached.

The safety rules of `safety_protocol.als` are one predicate, `Protocol`; only
structural well-formedness constraints are facts. The verifier file runs two
commands, and their results are interpreted as follows:

| `run CounterExample { GeneratedPlan and not Protocol }` | `run PlanPossible { GeneratedPlan }` | Benchmark status |
|---|---|---|
| Instance found (a world follows the plan and breaks the protocol) | any | `UNSAFE` |
| No instance found | No instance found (the plan cannot happen) | `IMPOSSIBLE_PLAN` |
| No instance found | Instance found | `SAFE` |
| Syntax or type error | | `SYNTAX_ERROR` |

For `UNSAFE`, the repair prompt shows the LLM the counterexample world and the
protocol rules it violates.

The verifier file copies no protocol text. `protocol_modules.py` writes, beside it:

- `safety_protocol_core.als`: the protocol cut at its `// STANDALONE MODE` line
  and checked (no fact may use `Protocol`, a rule, or anything a rule is built
  from; no commands; no local `open`), so `fact ProtocolHolds` never reaches a
  verifier;
- `<verifier>_ext.als`, only when a query needs words the protocol lacks: it
  opens the core (never the other way round) and holds only checked lines of
  three fixed forms (`name: set Sig`, `name: Sig -> lone Int`,
  `name: Sig -> lone Sig`), each with a `-- meaning`.

The verifier file opens these modules; the LLM is shown all of them.

Results produced before this change used `run { GeneratedPlan }` with the
rules as facts and read "No instance found" as `SAFE`. That query finds a world
that follows the plan AND obeys the protocol, so its `SAFE` meant the plan
contradicts the protocol. Those results are not comparable with these.

## Metrics

### No-loop and with-loop

- **No-loop:** success rate of the initial plan.
- **With-loop:** success rate after verifier-guided repairs.

These metrics measure the value of feedback and repair.

### pass@k

pass@k follows Chen et al., *Evaluating Large Language Models Trained on Code*
(2021), Section 2.1 and Figure 3.

For each prompt:

- Run the complete verifier-guided pipeline `R` times.
- Give every run the same fixed verification budget `V`.
- Let `c` be the number of complete runs that reach `SAFE` within `V`.
- For each `k <= R`, compute:

```text
pass@k = 1 - C(R - c, k) / C(R, k)
```

The reported aggregate is the mean pass@k across prompts.

`k` counts complete runs, not verification iterations. `V` is fixed while `k`
ranges from 1 to `R`. There is no pass@0.

## Setup

```bash
pip install openai anthropic matplotlib numpy
brew install openjdk
```

Select one LLM provider:

```bash
export LLM_PROVIDER=deepseek
export DEEPSEEK_API_KEY=sk-...
```

or:

```bash
export LLM_PROVIDER=claude
export ANTHROPIC_API_KEY=sk-ant-...
```

## Commands

Run the loop benchmark:

```bash
python run_swimming_experiment.py --trials 10 --max-iters 10
```

Run pass@k only with `R=10` independent complete runs and a fixed repair
budget `V=5` for every run:

```bash
python run_swimming_experiment.py --passk-only --passk-n 10 --passk-kmax 10 --passk-v 5
```

Collect full repair traces and compute both analyses from the same trials:

```bash
python run_swimming_experiment.py --run-passk --passk-n 10 --passk-kmax 10 --passk-v 5
```

Run without API or Alloy dependencies:

```bash
python run_swimming_experiment.py --dry-run
python run_swimming_experiment.py --passk-only --dry-run
```

Rebuild figures from saved logs:

```bash
python run_swimming_experiment.py --plot-only
python run_swimming_experiment.py --passk-plot-only --passk-v 5
```

`--passk-plot-only` makes no LLM or Alloy calls. It derives each run's
within-budget outcome from the complete iteration traces in
`swimming_experiment_log.json`, so the same saved experiment can also be
re-scored at a smaller `V`.

## Main files

| File | Purpose |
|---|---|
| `swimming_prompts.json` | Benchmark prompts |
| `safety_protocol.als` | Alloy safety model |
| `swimming_experiment_log.json` | Full loop traces and summary metrics |
| `swimming_experiment_summary.csv` | Tabular loop results |
| `swimming_experiment_plots.png` | Loop-analysis figures |
| `swimming_passk_log.json` | pass@k samples and estimates |
| `swimming_passk_per_prompt.png` | Per-prompt pass@k curves |
| `swimming_passk_aggregate.png` | Mean pass@k across prompts |

The pass@k plots are also exported as PGF files for LaTeX.
