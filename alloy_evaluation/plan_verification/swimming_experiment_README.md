# Swimming Safety Verification Benchmark

This benchmark asks an LLM to create a swimming-safety plan and uses Alloy to
check it against `safety_protocol.als`.

The dataset's `staff_safety_questions_v3` prompts each contain a situation followed by
exactly one situation-specific question about a pool-staff safety decision. Wording
varies with the scenario rather than using a fixed question. These are adaptations,
not verbatim forum posts. Source excerpts/URLs are retained separately, with disclosed
benchmark additions and verification status. Prompts 1, 2, and 10 remain excluded.
Question wording does not prescribe plan output or supply the required safety actions. Start a
fresh evaluation after this revision; do not combine its samples with older prompts.

## How it works

Step 1, once per prompt, before any plan: the prompt is formalized over
`safety_protocol.als` itself as the vocabulary (its signatures and fields, not
its rules) by the auto-formalization roundtrip (`../pipeline.py`). The formal
Before the roundtrip, Claude maps source-grounded concepts to existing vocabulary
and proposes missing extension declarations (`QueryExt`). This preparation is an
extension to the paper, bounded by the diagnosis-attempt setting.
Preparation accepts JSON with optional Markdown wrapping. Retries receive the
previous proposal, all validation errors, and the allowed signature names; missing
concepts require mappings rather than unsupported types or silently omitted facts.
Declarations are format-checked and typechecked by Alloy at roundtrip entry. The vocabulary is
then frozen for S1, S2, S3 and all scoped repairs. Instructions, intentions, history,
parenthood, and current compliance must have distinct meanings.
Release requires formal equivalence AND an NLI classification of `Equivalent` between
the original situation and the readback. `Strengthened`, `Weakened`, `Related`,
`Unrelated`, and `Contradiction` block release. NLI failures retry S1 -> S2 -> S3
directly using the unchanged original, previous predicate/readback, and NLI label
and scores. No Claude root-cause diagnosis or stage attribution is requested for
NLI failures. The retry forbids invented ages, times, supervision and on-duty staff,
and substituting chaperones for parents. Claude translates; it cannot override the
gate. Missing NLI dependencies block release as an infrastructure
error, not a valid failed sample. This gate is an extension to the paper, which uses
NLI post-hoc and defines its narrower drift measure as Unrelated/Contradiction.
For decided Alloy counterexamples, diagnosis still repairs the selected stage and
regenerates its dependents. Both paths share the roundtrip-attempt cap:
the initial check plus at most cap-minus-one scoped repairs, not separate full
regenerations. Syntax retries retain their separate cap.
There is no NLI override. `nli_result.json` saves scores and `nl_fidelity.json` saves
the gate result; `roundtrip_result.json` separates formal agreement from release.
`--alloy-timeout` applies to both roundtrip and plan verification (default 600 seconds).
An Alloy timeout or other undecided equivalence check stops that query without
translation diagnosis or repair. Saved results distinguish TIMEOUT from DIFFERENT;
only a decided counterexample or an NLI failure supplies translation-repair evidence.
`vocabulary_preparation.json` and `roundtrip_repairs.json` save preparation and repair
evidence. Agreement is bounded by the Alloy scope; NLI is fallible and is not a proof
of fidelity. `[FULL USER PROMPT]` logs the complete question, while `[X ORIGINAL]`
logs just the factual situation sent to formalization, not a truncated prompt.
New query vocabulary does not automatically connect those concepts to protocol rules.
Failed release remains an unsuccessful full-pipeline sample, not an omitted sample.
Start a fresh evaluation after this policy change; old release decisions are not
reused and evaluation manifests record the policy version.
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

### Full-Pipeline-Only Evaluation

For the full-pipeline metric without additional stage-specific LLM sampling:

```bash
python3 -u alloy_evaluation/plan_verification/full_pipeline_passk_evaluator.py --pass-at-k 5 > results/full_pipeline_eval.log 2>&1
```

This runs the same query formalization, plan generation, and capped internal
repair loops, but never branches off independent syntax/logic repair samples.
It saves all traces under `results/full_pipeline_passk/` and produces only the
per-prompt and average full-pipeline pass@k charts (PNG and PDF).
Defaults: usable prompts 3-9, five independent samples per prompt, roundtrip cap
5, syntax-repair cap 5, logic-repair cap 5, and Alloy timeout 600 seconds (10 minutes).

Resume this script's saved run with `--resume --out-dir <folder>`, or regenerate
charts without LLM calls using `--plot-only --log <folder>/full_pipeline_passk_log.json`.
Stage-evaluator output folders are not interchangeable with this script's runs.

### Eligible Prompts

Prompts 1, 2, and 10 are marked `eval_usable: false` and excluded from new
evaluations. Their incident states contradict the protocol under the current
single-state, query-preserving verifier. Their text and exclusion reasons
remain in `swimming_prompts.json`. The default evaluation uses IDs 3 through 9.
Eligibility does not certify translation fidelity or eliminate known model gaps.

Run the seven-prompt Claude evaluation with five independent runs per prompt:

```bash
python3 -u alloy_evaluation/plan_verification/stage_passk_evaluator.py --pass-at-k 5 > results/seven_prompt_eval.log 2>&1
```

Use a fresh output directory, not a resume of a different prompt set. Generated
data is saved under `results/stage_passk/`. `--prompt-ids 3` selects a single
eligible prompt; explicitly selecting an unusable prompt is rejected.

Plan verification defaults to `--alloy-timeout 600`: all three solver checks
share 600 seconds per invocation. This timeout is recorded in the experiment
configuration. Use a fresh output folder when changing it; do not combine
samples from different verification budgets into one pass@k estimate.

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
python3 -m pip install --user --upgrade pip
python3 -m pip install "anthropic==0.86.0" "transformers==4.57.6" torch matplotlib numpy
brew install openjdk
```

The NLI gate uses PyTorch and Transformers for BART-MNLI. Its
first check downloads and caches `facebook/bart-large-mnli`; it makes no Claude
API call. Unavailable NLI blocks release; formal agreement alone is insufficient.

All LLM stages use Claude through Anthropic, including query formalization,
roundtrip judgment, plan generation, and repair. One `CLAUDE_MODEL` setting
controls the entire pipeline (default: `claude-opus-4-6`).

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export CLAUDE_MODEL=claude-opus-4-6
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
