# ERSP — LLM Medical Triage Verification with Alloy

> **Research Project**: Can we integrate verification systems with Large Language Model pipelines to improve the safety, accuracy, and consistency of generated medical plans?

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Background & Motivation](#2-background--motivation)
3. [Architecture Overview](#3-architecture-overview)
4. [Prerequisites & Installation](#4-prerequisites--installation)
5. [Repository Structure](#5-repository-structure)
6. [Running the Pipelines](#6-running-the-pipelines)
   - [6.1 Main Verification Pipeline (`pipeline.py`)](#61-main-verification-pipeline-pipelinepy)
   - [6.2 Domain Auto-Formalization (`pipeline_domain.py`)](#62-domain-auto-formalization-pipeline_domainpy)
   - [6.3 Human-in-the-Loop Audit (`formalization/pipeline_formalization.py`)](#63-human-in-the-loop-audit-formalizationpipeline_formalizationpy)
   - [6.4 Alloy Slicer Demo (`formalization_demo.py`)](#64-alloy-slicer-demo-formalization_demopy)
7. [Working with Alloy Models](#7-working-with-alloy-models)
   - [7.1 Hand-Coded Reference Models](#71-hand-coded-reference-models)
   - [7.2 The Verifier Template (`compare.als`)](#72-the-verifier-template-compareas)
   - [7.3 Running Alloy Standalone](#73-running-alloy-standalone)
8. [The Controlled-English Translator](#8-the-controlled-english-translator)
9. [Adding a New Medical Domain](#9-adding-a-new-medical-domain)
10. [Key Design Decisions](#10-key-design-decisions)
11. [Results & Experiments](#11-results--experiments)
12. [Essential Readings & Resources](#13-essential-readings--resources)
13. [Team & Attribution](#14-team--attribution)

---

## 1. Project Overview

This project investigates whether **AI-generated medical advice can be formally verified** before being acted upon in triage and first-aid emergencies.

The core idea is a three-layer safety pipeline:

```
User prompt (natural language)
        ↓
  Claude LLM generates an Alloy "plan predicate"
        ↓
  Alloy model-checker compares the plan against
  a hand-verified reference protocol
        ↓
  If UNSAFE → LLM automatically repairs the plan
        ↓
  Human auditor reviews the final plan in
  plain English (controlled-language translation)
```

A **"safe" plan** means Alloy found **no counterexample** — i.e., the generated plan cannot violate any constraint in the reference protocol.

---

## 2. Background & Motivation

### Why Alloy?

[Alloy](https://alloytools.org/) is a lightweight formal specification language based on first-order relational logic. It uses a built-in SAT-based model-finder (Kodkod) that automatically checks whether a given set of constraints can be violated. Unlike theorem provers, Alloy is designed for fast, bounded verification — ideal for checking finite medical protocols.

### Why LLMs for Medical Advice?

LLMs like Claude can reason impressively about first-aid scenarios, but they hallucinate, skip steps, and can produce advice that contradicts clinical guidelines. We use Alloy as an independent "safety net" that catches these logical errors before a human acts on them.

### What Problems Does This Solve?

| Problem | Our Solution |
|---|---|
| LLM skips required prerequisite actions | Alloy `Dependency` facts enforce ordering |
| LLM invents steps that don't exist | Only actions defined in the reference model are valid |
| LLM advice is hard to audit | Controlled-English translator makes Alloy readable |
| Errors are discovered late | Automated repair loop fixes plans before human review |

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   User / Researcher                 │
│         (natural-language medical scenario)         │
└─────────────────────┬───────────────────────────────┘
                      │
          ┌───────────▼────────────┐
          │    pipeline.py         │  ← Main entry point
          │  (generate & verify)   │
          └───────────┬────────────┘
                      │
        ┌─────────────▼──────────────┐
        │   Claude API               │
        │   (generate GeneratedPlan) │
        └─────────────┬──────────────┘
                      │  Alloy pred
        ┌─────────────▼──────────────┐
        │  Alloy_Verifier/compare.als│  ← Reference constraints
        │  + GeneratedPlan predicate │     injected here
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │  AlloyCommandline (Java)   │  ← Runs Alloy CLI
        │  alloy4.2.jar              │
        └─────────────┬──────────────┘
                      │  SAFE / UNSAFE
        ┌─────────────▼──────────────┐
        │  Repair Loop               │  ← LLM fixes plan if UNSAFE
        │  (syntax → logic)          │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │  Human Audit               │  ← Controlled-English output
        │  (pipeline_formalization)  │
        └────────────────────────────┘
```

### Key Files at a Glance

| File | Purpose |
|---|---|
| `pipeline.py` | End-to-end generate → verify → repair loop |
| `pipeline_domain.py` | Auto-formalize a domain document into Alloy |
| `formalization/pipeline_formalization.py` | Human-in-the-loop audit REPL |
| `formalization_demo.py` | Standalone Alloy slicer demo |
| `formalization/controlled_language_translator.py` | Translates Alloy snippets → readable English |
| `formalization/alloy_operator_mapping.py` | Regex mappings for every Alloy operator |
| `Alloy_Verifier/compare.als` | **The verifier template** — edit this for each domain |
| `Alloy/*.als` | Hand-coded reference models |
| `AlloyCommandline/` | Java wrapper that runs Alloy headlessly |

---

## 4. Prerequisites & Installation

### 4.1 System Requirements

- **Python 3.9+**
- **Java 11+** (required to run Alloy headlessly)
- **Git** with submodule support

### 4.2 Clone the Repository

```bash
git clone <your-repo-url>
cd <repo-name>

# Important: initialize the Alloy CLI submodule
git submodule update --init --recursive
```

### 4.3 Install Python Dependencies

```bash
pip install anthropic python-dotenv
```

> If you need PDF ingestion support for `pipeline_domain.py`:
> ```bash
> pip install pypdf
> ```

### 4.4 Set Up Your API Key

Create a `.env` file in the project root:

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

> ⚠️ The `.env` file is already listed in `.gitignore`. Never commit your API key.

### 4.5 Compile the Alloy Java Runner

The `AlloyCommandline/` submodule contains the headless Alloy runner. It compiles automatically on first run, but you can pre-compile it:

```bash
cd AlloyCommandline
javac -cp alloy4.2.jar AlloyCommandline.java
cd ..
```

### 4.6 Verify Your Setup

```bash
# Should print something like "No instance found" or "Instance found"
cd AlloyCommandline
java -cp .:alloy4.2.jar AlloyCommandline ../Alloy/chokingtriage.als
cd ..
```

---

## 5. Repository Structure

```
.
├── .env                          # Your API key (never commit)
├── .gitignore
├── .gitmodules                   # Alloy CLI submodule reference
│
├── README.md                     # This file
├── ai_log.txt                    # Auto-generated LLM output log (appended)
│
├── pipeline.py                   # ← START HERE: main generate+verify pipeline
├── pipeline_domain.py            # Auto-formalize domain docs → Alloy
├── formalization_demo.py         # Standalone slicer demo
│
├── formalization/                # Translation & audit utilities
│   ├── pipeline_formalization.py # Human-in-the-loop REPL
│   ├── controlled_language_translator.py  # Alloy → English
│   └── alloy_operator_mapping.py # Alloy syntax → English mappings
│
├── Alloy/                        # Hand-coded reference Alloy models
│   ├── CPR.als                   # CPR protocol (Sheila)
│   ├── CPR_new.als               # Extended CPR
│   ├── chokingtriage.als         # Choking triage (John)
│   ├── Breaks:Sprains.als        # Fracture/sprain care (Aila)
│   ├── spine.als                 # Spine injury (Aila)
│   └── Swimming Drawning emergency handle.als  # Drowning (Junhao)
│
├── Alloy_Verifier/               # Verification templates
│   └── compare.als               # ← The main verifier (edit per domain)
│
├── Alloy_files/                  # Domain-specific modular Alloy
│   ├── reference.als             # Spine reference model
│   ├── generated.als             # Example generated plan
│   ├── compareOG.als             # Spine verifier template
│   └── spine.als                 # Standalone spine model
│
├── AlloyCommandline/             # Git submodule: Java Alloy headless runner
│   ├── alloy4.2.jar
│   └── AlloyCommandline.java
│
├── prompt-engineering/           # Prompt templates
│   ├── prompt engineering - alloy output from valid xml file to natural language
│   └── prompt engineering - from natural language plan into generated alloy plan
│
└── results/                      # Experimental results & notes
    ├── spine-injury-results.md
    └── tutorial.md               # Legacy tutorial (superseded by this README)
```

---

## 6. Running the Pipelines

### 6.1 Main Verification Pipeline (`pipeline.py`)

This is the **primary entry point**. It takes a natural-language medical scenario, generates an Alloy plan with Claude, and verifies it against the reference model in `Alloy_Verifier/compare.als`.

**Step 1**: Make sure `Alloy_Verifier/compare.als` matches your domain (see [Section 7.2](#72-the-verifier-template-compareas)).

**Step 2**: Edit the `prompt` variable at the bottom of `pipeline.py`:

```python
# pipeline.py, around line 160+
def main():
    prompt = "Someone just fell and their spine hurts, what should I do?"
    generate_and_verify(prompt)
```

**Step 3**: Run:

```bash
python3 pipeline.py
```

**What you'll see:**

```
A compilation for the alloy code written by LLM, to see if any syntax error, then
== Pipeline round 1 ==
[Logic Attempt 1]
No instance found.   ←  SAFE: plan doesn't violate any constraint
SAFE PLAN VERIFIED
```

Or, if the first attempt is unsafe:

```
[Logic Attempt 1]
Instance found.      ←  UNSAFE: counterexample exists
Sending to Claude for repair...
[Logic Attempt 2]
No instance found.
SAFE PLAN VERIFIED
```

**Outputs to check after each run:**
- `ai_log.txt` — every Claude response, appended
- `Alloy_Verifier/compare.als` — the `pred GeneratedPlan { ... }` block now contains the verified plan

> ⚠️ **Before running again**, clear the body of `pred GeneratedPlan {}` in `compare.als` to reset it. Otherwise the LLM starts from a non-empty plan.

---

### 6.2 Domain Auto-Formalization (`pipeline_domain.py`)

This pipeline takes a **plain-text or PDF domain document** (e.g., a first-aid manual) and:
1. Generates a complete Alloy safety protocol from it
2. Automatically verifies and repairs the protocol
3. Optionally runs a human audit

```bash
# Generate from a text document:
python3 pipeline_domain.py path/to/manual.txt --output safety_protocol.als

# Generate from a PDF:
python3 pipeline_domain.py path/to/manual.pdf --output safety_protocol.als

# Skip generation (use an existing .als file) and go straight to verification:
python3 pipeline_domain.py --skip-generation --output existing_model.als

# Skip the human audit step:
python3 pipeline_domain.py path/to/manual.txt --skip-audit

# Full control:
python3 pipeline_domain.py path/to/manual.txt \
    --output my_protocol.als \
    --scope 5 \
    --max-syntax-attempts 5 \
    --max-logic-attempts 5 \
    --seed 42
```

**The three phases it runs:**

| Phase | Description |
|---|---|
| Phase 1: Auto-Formalization | Claude reads the safety document and translate from human readable text to code |
| Phase 2: LLM-in-the-Loop Repair | LLM compares a specific scenario with auto-formalized safety protocol, and see if plan has Syntax and logic errors and fixed automatically |
| Phase 3: Human Audit | translation back each fact or assertion written into human language, and review each Alloy block in plain English |

**SAFE means**: Alloy's `check Safety` command returns "No instance found" — the protocol has no logical contradictions within the given scope.

---

### 6.3 Human-in-the-Loop Audit (`formalization/pipeline_formalization.py`)

This REPL lets you review each logical block in an Alloy file one by one, with **controlled-English translation** shown alongside the raw Alloy.

```bash
python3 formalization/pipeline_formalization.py \
    --als Alloy_Verifier/compare.als \
    --seed 42
```

You'll see something like:

```
======================================================================
Progress: 0/5 reviewed | 5 remaining
======================================================================
// Target: Predicate 'NextActionToDo'

abstract sig Action {}
...

pred NextActionToDo[a: Action] {
  no P.symptoms and a = AskForSymptoms and a not in P.done
  or
  some P.symptoms and no (P.states & MovementState) ...
}
======================================================================
Controlled English translation:
Predicate NextActionToDo with parameters [a: Action]:
1. P.symptoms is empty and a equals AskForSymptoms and a is not in P.done.
2. ...
======================================================================
Command [Accept / Reject: <feedback> / Stop] >
```

**Commands:**

| Command | What happens |
|---|---|
| `Accept` | Marks block as correct, moves to next |
| `Reject: the dependency order is wrong` | Sends your feedback to Claude, repairs the file, re-shows same block |
| `Stop` | Exits, leaving the file in its current state |

After a `Reject`, the pipeline automatically re-runs Phase 2 verification before showing you the repaired block.

---

### 6.4 Alloy Slicer Demo (`formalization_demo.py`)

A simplified, standalone version of the slicer without the repair loop. Useful for quickly inspecting what slices an `.als` file produces.

```bash
python3 formalization_demo.py --als Alloy/CPR_new.als --seed 123
```

---

## 7. Working with Alloy Models

### 7.1 Hand-Coded Reference Models

The `Alloy/` directory contains the ground-truth models written by team members. These encode the correct clinical protocol and are **not modified by the LLM pipelines**.

| File | Domain | Guidelines Used |
|---|---|---|
| `CPR.als`, `CPR_new.als` | Adult CPR | Red Cross CPR Steps |
| `chokingtriage.als` | Choking triage | Mayo Clinic First Aid |
| `Breaks:Sprains.als`, `spine.als` | Fractures & spine injury | Wilderness Medicine (Troop 1) |
| `Swimming Drawning emergency handle.als` | Drowning | AHA 2024 + CDC |

These files can be opened in the **Alloy Analyzer GUI** (download from [alloytools.org](https://alloytools.org/)) to visualize instances and run checks interactively.

### 7.2 The Verifier Template (`compare.als`)

`Alloy_Verifier/compare.als` is the **heart of the verification system**. It has a fixed structure:

```alloy
module checking

-- 1. All signature and type definitions (copied from your reference)
abstract sig Action {}
one sig DoThis, DoThat, ... extends Action {}

-- 2. Dependency graph (what must happen before what)
sig Dependency {
    state: one Action,
    requires: set Action
}

-- 3. Patient state tracker
sig PatientStatus {
    done: set Action,
    symptoms: set Symptom,
    states: set PatState
}
one sig P extends PatientStatus {}

-- 4. Reference constraints (wrapped in a predicate, NOT facts)
pred ReferenceConstraints {
    Dependencies        -- dependency graph is correct
    NoContradictoryStates
    ...
}

-- 5. Generated plan (LLM fills this in; starts empty)
pred GeneratedPlan {

}

-- 6. The verification run: find any world where the plan violates constraints
run {
    GeneratedPlan
    and not ReferenceConstraints
} for 10 Action, 10 Dependency, 1 PatientStatus
```

**The key insight**: The `run` command searches for an **instance where `GeneratedPlan` is true but `ReferenceConstraints` is false**. If Alloy finds no such instance → the plan is **SAFE**. If it finds one → the plan violates a constraint.

### 7.3 Running Alloy Standalone

You can run any `.als` file directly:

```bash
cd AlloyCommandline
java -cp .:alloy4.2.jar AlloyCommandline ../Alloy_Verifier/compare.als
```

Output meanings:

| Output | Meaning |
|---|---|
| `No instance found` | **SAFE** — no constraint violation exists |
| `Instance found` | **UNSAFE** — a counterexample exists |
| `Syntax error` | The Alloy file has a parse error |

---

## 8. The Controlled-English Translator

The translator in `formalization/controlled_language_translator.py` converts Alloy code blocks into readable English. It is **deterministic** (no LLM calls) — it uses pattern matching and a template system.

**Use it programmatically:**

```python
from formalization.controlled_language_translator import translate_slice, translate_statement

# Translate a complete Alloy snippet (with context)
snippet = """
pred NextActionToDo[a: Action] {
  no P.symptoms and a = AskForSymptoms
}
"""
print(translate_slice(snippet))

# Translate a single statement
print(translate_statement("no P.symptoms and a = AskForSymptoms"))
# → "P.symptoms is empty and a equals AskForSymptoms."
```

**Translation pipeline:**

1. Strip comments
2. Split into top-level blocks (sig, fact, pred, etc.)
3. For each block: split body into statements
4. Each statement: match against quantifiers, implications, equalities, etc.
5. Fall back to `alloy_operator_mapping.py` for symbols not handled by templates

**Supported constructs:**

- Quantifiers: `all`, `some`, `no`, `one`, `lone` with `|` separator
- Implications: `=>` and `implies`
- Boolean: `and`, `or`, `not`, `iff`
- Comparisons: `=`, `!=`, `>`, `>=`, `<`, `<=`
- Multiplicity: `no expr`, `some expr`, `one expr`, `lone expr`
- Relational: `in`, `not in`, `+`, `&`, `-`, `->`, `~`, `^`, `*`
- Temporal (Alloy 6): `always`, `eventually`, `after`, `before`, `once`, `historically`

---

## 9. Adding a New Medical Domain

Follow these steps to add a new domain (e.g., "Severe Bleeding"):

### Step 1: Create a Git Branch

```bash
git checkout -b severe-bleeding
```

### Step 2: Write the Reference Alloy Model

Create `Alloy/SevereBleeding.als`. Define:
- Abstract signatures for actions, states, conditions
- Dependency facts encoding the clinical protocol
- Predicates for valid scenarios
- Assertions for safety properties

Use the existing files as templates. Start simple — 5–10 actions is a good scope.

### Step 3: Create the Verifier Template

Copy and adapt `Alloy_Verifier/compare.als`:

```bash
cp Alloy_Verifier/compare.als Alloy_Verifier/compare_bleeding.als
```

Edit the new file:
1. Replace all action/sig definitions with your domain's
2. Update the `Dependency` predicates
3. Keep `pred GeneratedPlan {}` empty
4. Keep the `run { GeneratedPlan and not ReferenceConstraints }` block

Then update `pipeline.py` to point to your new file:

```python
# pipeline.py line ~10
COMPARE_PATH = "Alloy_Verifier/compare_bleeding.als"
```

### Step 4: Test the Alloy Model First

Before running the full pipeline, verify your model makes sense:

```bash
cd AlloyCommandline
java -cp .:alloy4.2.jar AlloyCommandline ../Alloy_Verifier/compare_bleeding.als
# Should print "No instance found" (GeneratedPlan is empty, so trivially safe)
```

### Step 5: Run the Pipeline

```bash
python3 pipeline.py
# Edit the prompt in main() first!
```

### Step 6: Document Results

Add a file `results/severe-bleeding-results.md` with notes on:
- The prompts you tested
- How many repair iterations were needed
- Whether the final plan matched clinical guidelines
- Comparison with raw ChatGPT/Claude output (no verification)

---

## 10. Key Design Decisions

### Why `ReferenceConstraints` is a Predicate, not Facts

In standard Alloy, constraints are `fact` blocks that always hold. In this project, **reference constraints are wrapped in a `pred`** so the `run` command can explicitly check `not ReferenceConstraints`. This allows us to detect when the generated plan causes a violation, rather than making violations impossible to express.

### Why the LLM Only Modifies `GeneratedPlan`

The LLM is explicitly prompted to **only change the `pred GeneratedPlan {}` block**. The rest of `compare.als` (signatures, dependencies, reference constraints) is the trusted ground truth. This isolation ensures the LLM cannot "cheat" by modifying the safety rules.

### Two-Phase Repair Loop

1. **Syntax repair**: Alloy won't run at all if there's a parse error. The first loop ensures the file at least compiles.
2. **Logic repair**: Once compilable, the second loop checks for actual constraint violations and prompts the LLM to fix the plan's logical content.

### Scope Bounds

All Alloy `run`/`check` commands specify finite scopes (e.g., `for 10 Action, 10 Dependency`). Alloy is a **bounded** model-checker — it exhaustively checks all instances up to the given size. If the scope is too small, it may miss violations. If too large, it's slow. The default scope of 5–10 per type is a practical tradeoff for medical protocols with ~10–15 actions.

---

## 11. Results & Experiments

Results from prior experiments are in the `results/` directory, diagram result could be seen in the swimming branch

**Spine Injury Experiment** (`results/spine-injury-results.md`):

Tested prompts like:
- `"Someone fell and their back hurts"` → Generated `AskForInfo` as next step ✓
- `"Someone fell, back hurts, can't move"` → Generated `Immobilize` ✓
- `"Someone fell"` (vague) → Multiple repair iterations needed

**Key finding**: The LLM's first attempt was often logically correct for clear scenarios but needed 1–2 repair iterations for ambiguous prompts. The reference model effectively caught cases where the LLM skipped prerequisite steps. **See Swimming branch result folder**

To run your own experiments and record results:

```bash
# Run pipeline with a specific prompt, save output
python3 pipeline.py 2>&1 | tee results/my-experiment-$(date +%Y%m%d).log
```
---

## 12. Essential Readings & Resources

### Alloy

| Resource | Link |
|---|---|
| Alloy official site & analyzer download | https://alloytools.org/ |
| Alloy tutorial (Daniel Jackson) | https://alloytools.org/tutorials/day-course/ |
| *Software Abstractions* (textbook) | ISBN 978-0-262-01715-9 |
| Alloy language reference | https://alloy.readthedocs.io/ |

### Medical Guidelines (used in the Alloy models)

| Model | Source |
|---|---|
| CPR | https://www.redcross.org/take-a-class/cpr/performing-cpr/cpr-steps |
| Wilderness First Aid (fractures, spine) | https://troopone.org/wp-content/uploads/2021/07/T2-Troop-1-Wilderness-Medicine-Training-Overview-v4.pdf |
| Choking | https://www.mayoclinic.org/first-aid/first-aid-choking/basics/art-20056637 |
| Drowning CPR | https://www.heart.org/en/news/2024/11/12/cpr-with-rescue-breaths-vital-to-resuscitation-after-drowning |
| Drowning prevention | https://www.cdc.gov/drowning/about/index.html |

### Claude / Anthropic API

| Resource | Link |
|---|---|
| Anthropic API docs | https://docs.anthropic.com/ |
| Python SDK reference | https://github.com/anthropic/anthropic-sdk-python |
| Prompt engineering guide | https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview |

---

## 13. Team & Attribution

| Member | Domain | Role |
|---|---|---|
| **Aila** | Fractures/Sprains, Spine Injury | Alloy main pipeline |
| **Sheila** | CPR | English Translator |
| **John** | Choking | Poster, and main pipeline |
| **Junhao** | Drowning | Testing, Translator, code slicer |

**Advisor**: Prof. Michael Coblenz, Ilana Shapiro

**Institution**: Salad Lab, UCSD

---

## Quick-Start Checklist for New Team Members

```
□ Clone repo + git submodule update --init --recursive
□ pip install anthropic python-dotenv
□ Create .env with ANTHROPIC_API_KEY=...
□ Read one of the Alloy tutorial links above (30 min)
□ Open Alloy_files/reference.als in the Alloy Analyzer GUI
  and run the predicate — explore the instance visualizer
□ Run: python3 pipeline.py
  (with a simple medical scenario in the prompt)
□ Check compare.als to see the generated plan
□ Read results/spine-injury-results.md for reference
□ Create your branch and start working on a new domain!
```

---

*Last updated: June 2026 | Research code — not for clinical use*
