"""x_original           human/semi-automatic workflow -> define vocab/declaration that all alloy file should use.
    |
 (by calling llm and check return code is valid (ignored over-simplified answer and alloy typecheck/compile))
    |
    y_original.als
    |
 (deformalized in to natual language)
    |
    x'
 (by calling llm and check return code is valid(ignored over-simplified answer and alloy typecheck/compile))
    |
    y_prime.als

check if y_original <-> y_prime.als by equivalence.py (alloy check, exhaustive at one context)
    |                                   |
    if yes, proceed NLI check.          if no do stage diagnose, call llm locate file, update the file, and update following stages
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import alloy
import equivalence
import protocol_modules as pm
from fragment import check_pred_shape, hard_constraints
from nli.compare import compare as compare_nli


ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"


@dataclass
class Settings:
    model: str = DEFAULT_MODEL
    judge_model: str = ""
    temperature: float = 0.1
    judge_temperature: float = 0.0
    max_tokens: int = 2000
    max_rounds: int = 3
    max_compile_attempts: int = 5
    max_diagnosis_attempts: int = 3
    alloy_timeout: int = 120
    run_nli: bool = True
    nli_model: str = "facebook/bart-large-mnli"


class PipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class Vocabulary:
    """What a rule may be written in.

    Context form (struct set): a hand-written vocab.als with one context
    signature; a rule is `pred rule[c: <struct>]` about one context.
    Protocol form (struct ""): the protocol's own signatures and fields, plus
    checked extension words; a rule is `pred rule { ... }` about a whole world
    and may not call the protocol's predicates (`forbidden`)."""
    source: str                                   # the declarations the LLM is shown
    struct: str
    protocol: str = ""                            # protocol .als path (protocol form)
    extension: tuple[str, ...] = ()               # checked extension lines (protocol form)
    scope: str = ""                               # the protocol's own scope (protocol form)
    forbidden: frozenset[str] = frozenset()       # the protocol's predicates and functions


@dataclass
class State:
    original_rule: str
    reconstructed: str
    prime_rule: str
    vocabulary: Vocabulary


@dataclass
class Diagnosis:
    stage: str
    reason: str = ""
    hint: str = ""
    confidence: float = 0.0


EXTENSION_MODULE = "query_ext"


def opens_for(vocabulary: Vocabulary) -> list[str]:
    """The modules a rule file of this vocabulary opens."""
    if vocabulary.struct:
        return ["vocab"]
    return [pm.core_name(vocabulary.protocol)] + ([EXTENSION_MODULE] if vocabulary.extension else [])


def prepare_stage(vocabulary: Vocabulary, stage_dir: Path) -> list[str]:
    """Write the modules every rule file in stage_dir opens (Alloy resolves `open`
    beside the file): vocab.als, or the protocol core and the extension."""
    if vocabulary.struct:
        (stage_dir / "vocab.als").write_text(vocabulary.source, encoding="utf-8")
        return opens_for(vocabulary)
    core_path = pm.build_core(vocabulary.protocol, stage_dir)
    extension_path = stage_dir / f"{EXTENSION_MODULE}.als"
    if vocabulary.extension:
        pm.build_extension(list(vocabulary.extension), core_path, module=EXTENSION_MODULE)
    elif extension_path.exists() and pm.GENERATED in extension_path.read_text(encoding="utf-8"):
        extension_path.unlink()
    return opens_for(vocabulary)


def scope_for(vocabulary: Vocabulary, *rules: str) -> str:
    """Context form: one context, Int wide enough for the constants. Protocol
    form: the protocol's own scope, its Int widened for the rules' constants."""
    if vocabulary.struct:
        return alloy.scope(alloy.int_bitwidth(vocabulary.source, *rules))
    return alloy.widen_scope(vocabulary.scope, *rules)


def _outcome(stage_dir: Path, stopped_at: str) -> None:
    """Record where run() stopped: VOCAB, S1, S2, S3, EQUIVALENCE, or none."""
    (stage_dir / "roundtrip_outcome.txt").write_text(stopped_at + "\n", encoding="utf-8")


# main
def run(
    original: str,
    vocabulary: Vocabulary,
    stage_dir: Path,
    settings: Settings,
    client: LLM,
) -> bool:
    stage_dir.mkdir(parents=True, exist_ok=True)
    opens = prepare_stage(vocabulary, stage_dir)
    original = original.strip() + "\n"
    (stage_dir / "x.txt").write_text(original, encoding="utf-8")
    print("[X ORIGINAL]", flush=True)
    print(original.strip(), flush=True)

    vocab_ok, vocab_error = typecheck(
        "".join(f"open {module}\n" for module in opens)
        + f"\nrun Vocab {{}} {scope_for(vocabulary)}\n",
        stage_dir / "vocab_check.als",
        settings.alloy_timeout,
    )
    print("\n[VOCAB RETURN]", flush=True)
    print(f"typecheck: {str(vocab_ok).lower()}", flush=True)
    if not vocab_ok:
        print(vocab_error, flush=True)
        print("\n[PIPELINE RETURN]\nfalse", flush=True)
        _outcome(stage_dir, "VOCAB")
        return False

    original_rule = formalize(
        client, settings, vocabulary, original, stage_dir,
        stage="S1", module_name="y_original",
    )
    if original_rule is None:
        print("\n[PIPELINE RETURN]\nfalse", flush=True)
        _outcome(stage_dir, "S1")
        return False

    reconstructed = deformalize(
        client, settings, vocabulary, original_rule, stage_dir
    )
    if reconstructed is None:
        print("\n[PIPELINE RETURN]\nfalse", flush=True)
        _outcome(stage_dir, "S2")
        return False

    prime_rule = formalize(
        client, settings, vocabulary, reconstructed, stage_dir,
        stage="S3", module_name="y_prime",
    )
    if prime_rule is None:
        print("\n[PIPELINE RETURN]\nfalse", flush=True)
        _outcome(stage_dir, "S3")
        return False

    state = State(original_rule, reconstructed, prime_rule, vocabulary)
    equivalent, evidence, _ = check_equivalence(stage_dir, settings.alloy_timeout, vocabulary)

    for round_number in range(1, settings.max_rounds + 1):
        if equivalent:
            break
        diagnosis = diagnose(client, settings, original, state, evidence)
        print(f"\n[DIAGNOSIS RETURN round {round_number}]", flush=True)
        print(f"stage: {diagnosis.stage}", flush=True)
        print(f"reason: {diagnosis.reason}", flush=True)
        print(f"hint: {diagnosis.hint}", flush=True)
        print(f"confidence: {diagnosis.confidence}", flush=True)

        print(f"\n[REPAIR round {round_number}: {diagnosis.stage}]", flush=True)
        updated = repair(client, settings, original, state, diagnosis, stage_dir)
        print(f"[REPAIR RETURN]\n{str(updated is not None).lower()}", flush=True)
        if updated is None:
            break
        state = updated
        equivalent, evidence, _ = check_equivalence(stage_dir, settings.alloy_timeout, vocabulary)

    print("\n[NLI RETURN]", flush=True)
    if not settings.run_nli:
        print("disabled", flush=True)
    else:
        semantic = compare_nli(original, state.reconstructed, settings.nli_model)
        if semantic.get("available"):
            print(f"category: {semantic.get('category')}", flush=True)
            print(f"drift: {str(semantic.get('drift')).lower()}", flush=True)
        else:
            print(f"unavailable: {semantic.get('note')}", flush=True)

    print("\n[PIPELINE RETURN]", flush=True)
    print(str(equivalent).lower(), flush=True)
    _outcome(stage_dir, "none" if equivalent else "EQUIVALENCE")
    return equivalent


def formalize(
    client: LLM,
    settings: Settings,
    vocabulary: Vocabulary,
    specification: str,
    stage_dir: Path,
    *,
    stage: str,
    module_name: str,
    repair_prompt: str = "",
) -> str | None:
    if vocabulary.struct:
        system = f"""Translate the supplied text into one Alloy 6 predicate over the
supplied fixed vocabulary. Return exactly:
```alloy
pred rule[c: {vocabulary.struct}] {{
  ...
}}
```
Translate only what the text says: state every fact it states and nothing else, and
leave any field the text does not mention unconstrained. Preserve every condition,
exception, threshold, and implication direction. Write fields as `c.field` and enum
values by their bare name (`c.breathing = No`), using `and`, `or`, `not`, `implies`,
`iff`, `=`, `!=`, `in`, and comparisons of integer fields against constants.
The rule is rejected unless it meets every one of these constraints:
{hard_constraints(vocabulary.struct)}
Do not repeat vocabulary declarations. Reply with one Alloy block only."""
    else:
        system = f"""Translate the supplied text into one Alloy 6 predicate over the
supplied fixed vocabulary, which is a safety protocol's signatures and fields. The
predicate states the situation the text describes, as facts about atoms of those
signatures. Return exactly:
```alloy
pred rule {{
  ...
}}
```
Translate only what the text says: state every fact it states and nothing else, and
leave any field the text does not mention unconstrained. Preserve every condition,
exception, threshold, and implication direction. Introduce the people, places and
objects the text mentions with quantifiers over the vocabulary's signatures, e.g.
`some p: Patron, s: Spa | p.age = 1 and p.inWater = s`; write enum values by their
bare name (`True`, `Green`); use `and`, `or`, `not`, `implies`, `iff`, `=`, `!=`,
`in`, and comparisons of integer fields against constants, in the units and scaling
the vocabulary's comments give. A word of the extension (`QueryExt`) is used as
`x in QueryExt.word` or `x.(QueryExt.word)`. The text may ask a question or request
a plan; formalize only the situation it describes, not the question.
The rule is rejected unless it meets every one of these constraints:
{hard_constraints("")}
Do not repeat vocabulary declarations. Reply with one Alloy block only."""
    prompt = repair_prompt or f"""Formalize this text:

{specification.strip()}

Fixed vocabulary:
```alloy
{vocabulary.source.strip()}
```"""
    header = f"pred rule[c: {vocabulary.struct}]" if vocabulary.struct else "pred rule"
    current_system = system

    for attempt in range(1, settings.max_compile_attempts + 1):
        reply = client.complete(
            current_system,
            prompt,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        )
        model_code = reply.strip()
        if "```" in model_code:
            chunks = model_code.split("```")
            model_code = chunks[1].partition("\n")[2].strip() or chunks[1].strip()

        shape_ok, error = check_pred_shape(model_code, vocabulary.struct, vocabulary.forbidden)
        print(f"\n[{stage} DEF SHAPE attempt {attempt}]", flush=True)
        print(f"shape: {str(shape_ok).lower()}", flush=True)
        if not shape_ok:
            print(f"rejected: {error}", flush=True)
        else:
            rule = model_code.strip()
            scope = scope_for(vocabulary, rule)
            # both runs must find an instance: a rule no context satisfies, or one
            # every context satisfies, says nothing about the text
            if vocabulary.struct:
                source = f"""open vocab

{rule}

run Satisfiable {{ some c: {vocabulary.struct} | rule[c] }} {scope}
run Refutable {{ some c: {vocabulary.struct} | not rule[c] }} {scope}
"""
            else:
                source = ("".join(f"open {module}\n" for module in opens_for(vocabulary))
                          + f"\n{rule}\n\nrun Satisfiable {{ rule }} {scope}\n"
                          + f"run Refutable {{ not rule }} {scope}\n")
            typecheck_ok, error = typecheck(
                source, stage_dir / f"{module_name}.als", settings.alloy_timeout
            )
            print(f"typecheck: {str(typecheck_ok).lower()}", flush=True)
            if typecheck_ok:
                print(f"\n[{stage} RETURN]", flush=True)
                print(rule, flush=True)
                return rule
            print(f"rejected: {error}", flush=True)

        if attempt == settings.max_compile_attempts:
            break
        # a rejection goes down its own path: first diagnose it, then repair the
        # rule with that diagnosis -- not another first-shot translation
        diagnosis = diagnose_rejection(client, settings, vocabulary, specification,
                                       model_code, error)
        print(f"\n[{stage} REJECTION DIAGNOSIS]\n{diagnosis}", flush=True)
        current_system = REPAIR_SYSTEM.format(header=header,
                                              constraints=hard_constraints(vocabulary.struct))
        prompt = f"""Text the predicate formalizes:
{specification.strip()}

Fixed vocabulary:
```alloy
{vocabulary.source.strip()}
```

Rejected predicate:
```alloy
{model_code}
```

Checker error:
{error}

Diagnosis of the error:
{diagnosis}"""

    print(f"\n[{stage} RETURN]\nfalse", flush=True)
    # the last rejection, for whoever decides what to do next
    (stage_dir / f"{stage}_last_error.txt").write_text(str(error), encoding="utf-8")
    return None


REJECTION_DIAGNOSE_SYSTEM = """An Alloy predicate that formalizes a text was rejected by the checker.
Read the checker's error, the rejected predicate and the fixed vocabulary
(including any extension words in `QueryExt`) and say exactly what is wrong and
how to fix it with the vocabulary as it is. Reply with exactly three lines:
WHERE: <the offending expression, copied from the predicate>
WHY: <why it is rejected, in terms of the vocabulary's signatures and fields>
FIX: <the replacement expression, using only signatures and fields of the
vocabulary; an extension word is used as `x in QueryExt.word` or
`x.(QueryExt.word)`>"""


REPAIR_SYSTEM = """You are repairing a rejected Alloy predicate. You are given the text it
formalizes, the fixed vocabulary, the rejected predicate, the checker's error
and a diagnosis of that error. Apply the diagnosis: change what it says to
change and keep every other part of the predicate as it is. Return the complete
corrected predicate, exactly in this form:
```alloy
{header} {{
  ...
}}
```
It must still meet every one of these constraints:
{constraints}
Reply with one Alloy block only."""


def diagnose_rejection(client: "LLM", settings: Settings, vocabulary: Vocabulary,
                       specification: str, rejected: str, error: str) -> str:
    """WHERE / WHY / FIX for one rejected rule (a separate call: its own task)."""
    reply = client.complete(
        REJECTION_DIAGNOSE_SYSTEM,
        f"""Text:
{specification.strip()}

Fixed vocabulary:
```alloy
{vocabulary.source.strip()}
```

Rejected predicate:
```alloy
{rejected}
```

Checker error:
{error}""",
        temperature=settings.judge_temperature,
        max_tokens=settings.max_tokens,
        model=settings.judge_model or settings.model,
    )
    return reply.strip()


DEFORMALIZE_SYSTEM = """Read the supplied formal statement and say the same thing
in ordinary language. Mirror its logical structure exactly: `and` is "and", `or` is
"or", `implies` is "if ... then", `not` is "not", `=` is "is", `!=` is "is not". Never
turn one into another; in particular, never restate a conjunction as a conditional.
Preserve every condition, threshold, exception, and implication direction. Do not
mention Alloy, code, types, fields, or identifiers. Add nothing the statement does
not say. Reply with plain prose."""


def deformalize(
    client: LLM,
    settings: Settings,
    vocabulary: Vocabulary,
    rule: str,
    stage_dir: Path,
    repair_prompt: str = "",
) -> str | None:
    reply = client.complete(
        DEFORMALIZE_SYSTEM,
        repair_prompt or f"""State the requirement expressed by this rule.

Fixed vocabulary:
```alloy
{vocabulary.source.strip()}
```

Rule:
```alloy
{rule.strip()}
```""",
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    ).strip()
    if reply.startswith("```"):
        lines = reply.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines.pop()
        reply = "\n".join(lines).strip()
    if not reply:
        print("\n[S2 RETURN]\nfalse", flush=True)
        return None
    (stage_dir / "x_prime.txt").write_text(reply + "\n", encoding="utf-8")
    print("\n[S2 RETURN]", flush=True)
    print(reply, flush=True)
    return reply


def check_equivalence(
    stage_dir: Path,
    timeout: int,
    vocabulary: Vocabulary | None = None,
) -> tuple[bool, str, dict[str, str] | None]:
    """Equivalent, the evidence for the diagnosis, and the counterexample if any.
    Without `vocabulary` the stage is a context-form one and vocab.als is read."""
    vocabulary = vocabulary or load_vocabulary(stage_dir / "vocab.als")
    original_rule, prime_rule = (
        equivalence.rule_of(path.read_text(encoding="utf-8")) if path.exists() else ""
        for path in (stage_dir / "y_original.als", stage_dir / "y_prime.als")
    )
    if not original_rule or not prime_rule:
        verdict = equivalence.Verdict(False, False, "A rule module is missing.")
    elif vocabulary.struct:
        bitwidth = alloy.int_bitwidth(vocabulary.source, original_rule, prime_rule)
        verdict = equivalence.decide(
            stage_dir / "equivalence.als",
            equivalence.theorem_source(vocabulary.struct, original_rule, prime_rule, bitwidth),
            timeout,
        )
    else:
        scope = scope_for(vocabulary, original_rule, prime_rule)
        verdict = equivalence.decide(
            stage_dir / "equivalence.als",
            equivalence.world_theorem_source(opens_for(vocabulary), original_rule, prime_rule, scope),
            timeout,
            scope_note=("Alloy found no counterexample to `ruleOriginal iff rulePrime` "
                        f"within `{scope}`, the protocol's own scope."),
        )
    print("\n[EQUIVALENCE RETURN]", flush=True)
    print(f"typecheck: {str(verdict.decided).lower()}", flush=True)
    print(f"equivalent: {str(verdict.equivalent).lower()}", flush=True)
    print(verdict.evidence, flush=True)
    return verdict.equivalent, verdict.evidence, verdict.counterexample


DIAGNOSE_SYSTEM = """Audit this translation pipeline:
S1: original natural language -> original Alloy rule
S2: original Alloy rule -> reconstructed natural language
S3: reconstructed natural language -> roundtrip Alloy rule

Weigh all three stages together, then report the one that lost the meaning. Do not
walk through them in order and do not settle on the first stage that looks
imperfect: a stage is the culprit only if repairing that stage alone would remove
the disagreement. The fix hint may mention only adjacent artifacts: S1 uses
x/y_original, S2 uses y_original/x_prime, and S3 uses x_prime/y_prime. Return
exactly four plain-text lines:
STAGE: S1|S2|S3
ROOT_CAUSE: ...
SCOPED_FIX_HINT: ...
CONFIDENCE: 0.0"""


def diagnose(
    client: LLM,
    settings: Settings,
    original: str,
    state: State,
    evidence: str,
) -> Diagnosis:
    prompt = f"""x:
{original.strip()}

y_original:
```alloy
{state.original_rule}
```

x_prime:
{state.reconstructed}

y_prime:
```alloy
{state.prime_rule}
```

Fixed vocabulary:
```alloy
{state.vocabulary.source.strip()}
```

Formal evidence:
{evidence}"""
    for _ in range(settings.max_diagnosis_attempts):
        reply = client.complete(
            DIAGNOSE_SYSTEM,
            prompt,
            temperature=settings.judge_temperature,
            max_tokens=settings.max_tokens,
            model=settings.judge_model or settings.model,
        )
        fields: dict[str, str] = {}
        for line in reply.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                fields[key.strip().upper()] = value.strip()
        stage = fields.get("STAGE", "").upper()
        if stage not in {"S1", "S2", "S3"}:
            continue
        try:
            confidence = max(0.0, min(1.0, float(fields.get("CONFIDENCE", "0"))))
        except ValueError:
            confidence = 0.0
        return Diagnosis(
            stage,
            fields.get("ROOT_CAUSE", ""),
            fields.get("SCOPED_FIX_HINT", ""),
            confidence,
        )
    return Diagnosis("UNKNOWN")


def repair(
    client: LLM,
    settings: Settings,
    original: str,
    state: State,
    diagnosis: Diagnosis,
    stage_dir: Path,
) -> State | None:
    vocabulary = state.vocabulary
    feedback = " ".join(part for part in (diagnosis.reason, diagnosis.hint) if part)

    if diagnosis.stage not in {"S1", "S2", "S3"}:
        diagnosis = Diagnosis("S1", "diagnosis unavailable", "regenerate carefully", 0.0)
        feedback = "diagnosis unavailable; regenerate carefully"

    original_rule = state.original_rule
    reconstructed = state.reconstructed

    if diagnosis.stage == "S1":
        s1_prompt = f"""Repair S1 only.
x:
{original.strip()}
y_original:
{state.original_rule}
diagnosis:
{feedback}
vocabulary:
{vocabulary.source.strip()}
Return only the corrected `pred rule`."""
        original_rule = formalize(
            client, settings, vocabulary, original, stage_dir,
            stage="S1", module_name="y_original", repair_prompt=s1_prompt,
        )
        if original_rule is None:
            return None

    s2_prompt = ""
    if diagnosis.stage == "S2":
        s2_prompt = f"""Repair S2 only.
y_original:
{state.original_rule}
x_prime:
{state.reconstructed}
diagnosis:
{feedback}
vocabulary:
{vocabulary.source.strip()}
Return only the corrected plain-language requirement."""

    if diagnosis.stage in {"S1", "S2"}:
        reconstructed = deformalize(
            client,
            settings,
            vocabulary,
            original_rule,
            stage_dir,
            repair_prompt=s2_prompt,
        )
        if reconstructed is None:
            return None

    s3_prompt = ""
    if diagnosis.stage == "S3":
        s3_prompt = f"""Repair S3 only.
x_prime:
{state.reconstructed}
y_prime:
{state.prime_rule}
diagnosis:
{feedback}
vocabulary:
{vocabulary.source.strip()}
Return only the corrected `pred rule`."""

    prime_rule = formalize(
        client, settings, vocabulary, reconstructed, stage_dir,
        stage="S3", module_name="y_prime", repair_prompt=s3_prompt,
    )
    return State(original_rule, reconstructed, prime_rule, vocabulary) if prime_rule else None


def alloy_available() -> bool:
    return alloy.alloy_available()


RUN_MEANING = {
    "Satisfiable": "nothing satisfies `rule` (no context, no world): it is the constant proposition False",
    "Refutable": "everything satisfies `rule` (every context, every world): it is the constant proposition True",
    "Vocab": "the vocabulary admits no context or world at all",
}


def typecheck(source: str, path: Path, timeout: int = 120) -> tuple[bool, str]:
    """Compiles with no error and no warning, and every `run` finds an instance."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    result = alloy.execute(path, timeout=timeout)
    if not result.ok:
        return False, result.error
    for name, outcome in result.outcomes.items():
        if outcome != "SAT" and re.search(rf"(?m)^run\s+{re.escape(name)}\b", source):
            return False, RUN_MEANING.get(name, f"`run {name}` has no instance")
    return True, ""


def load_vocabulary(path: str | Path) -> Vocabulary:
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    if not re.match(r"\s*(?:--[^\n]*\n\s*)*module\s+vocab\b", source):
        raise PipelineError("vocabulary must begin with `module vocab`")
    structures = re.findall(r"(?m)^sig\s+([A-Za-z_][A-Za-z0-9_']*)\s*\{", source)
    if len(structures) != 1:
        raise PipelineError("vocabulary must contain exactly one context sig")
    return Vocabulary(source.strip() + "\n", structures[0])


def load_protocol_vocabulary(protocol_path: str | Path, extension: list[str] | tuple[str, ...] = ()) -> Vocabulary:
    """The protocol form: the protocol's signatures and fields (its rules left
    out), plus checked extension words."""
    protocol_path = Path(protocol_path).resolve()
    text = protocol_path.read_text(encoding="utf-8")
    try:
        core = pm.split_protocol(text)[0]
    except pm.ProtocolError as error:
        raise PipelineError(str(error)) from error
    source = pm.vocabulary_view(core)
    extension = tuple(line for line in extension if line.strip())
    if extension:
        accepted, problems = pm.check_extension_lines(list(extension), core)
        if problems:
            raise PipelineError("extension rejected:\n- " + "\n- ".join(problems))
        source += (f"\n// ===== extension module {EXTENSION_MODULE} (opens the protocol) =====\n"
                   + pm.extension_block(accepted))
    return Vocabulary(source, "", str(protocol_path), extension,
                      pm.protocol_scope(text), frozenset(pm.predicate_names(core)))


@dataclass
class LLM:
    model: str
    api_key: str = ""
    base_url: str = ""

    def __post_init__(self) -> None:
        from openai import OpenAI

        self.api_key = (
            self.api_key
            or os.environ.get("ROUNDTRIP_API_KEY", "")
            or os.environ.get("DEEPSEEK_API_KEY", "")
            or os.environ.get("OPENAI_API_KEY", "")
        ).strip()
        if not self.api_key:
            raise PipelineError(
                "set ROUNDTRIP_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY"
            )
        self.base_url = (
            self.base_url
            or os.environ.get("ROUNDTRIP_BASE_URL", "")
            or os.environ.get("DEEPSEEK_BASE_URL", "")
            or os.environ.get("OPENAI_BASE_URL", "")
            or DEFAULT_BASE_URL
        ).strip()
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=180)

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float,
        max_tokens: int,
        model: str | None = None,
    ) -> str:
        import openai

        selected_model = model or self.model
        parameters: dict = {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
        }
        if "reasoner" not in selected_model:
            parameters["temperature"] = temperature

        transient = (
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.InternalServerError,
        )
        response = None
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                response = self.client.chat.completions.create(**parameters)
                break
            except transient as error:
                last_error = error
                time.sleep(min(2**attempt, 30) + random.random())
            except openai.APIStatusError as error:
                raise PipelineError(
                    f"{selected_model} rejected the request: HTTP {error.status_code}"
                ) from error
        if response is None:
            raise PipelineError(f"{selected_model} failed after retries: {last_error}")
        text = (response.choices[0].message.content or "").strip()
        if not text:
            raise PipelineError(f"{selected_model} returned an empty response")
        return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Alloy roundtrip verification and scoped repair")
    parser.add_argument("input", help="path to the original x text")
    parser.add_argument("-v", "--vocab", required=True, help="hand-written Alloy vocabulary")
    parser.add_argument("--stage-dir", default="", help="directory for all stage artifacts")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--judge-model", default="")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--no-nli", action="store_true")
    arguments = parser.parse_args(argv)

    input_path = Path(arguments.input)
    vocabulary_path = Path(arguments.vocab)
    if not input_path.exists() or not vocabulary_path.exists():
        parser.error("input and vocabulary files must exist")
    if not alloy_available():
        print("Alloy is not available", file=sys.stderr)
        return 2
    try:
        vocabulary = load_vocabulary(vocabulary_path)
        settings = Settings(
            model=arguments.model,
            judge_model=arguments.judge_model,
            max_rounds=arguments.rounds,
            run_nli=not arguments.no_nli,
        )
        client = LLM(settings.model)
    except PipelineError as error:
        print(str(error), file=sys.stderr)
        return 2

    stage_dir = Path(arguments.stage_dir) if arguments.stage_dir else (
        input_path.parent if input_path.name == "x.txt" else ROOT / "stages" / input_path.stem
    )
    try:
        equivalent = run(
            input_path.read_text(encoding="utf-8"),
            vocabulary,
            stage_dir,
            settings,
            client,
        )
    except PipelineError as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0 if equivalent else 1


if __name__ == "__main__":
    raise SystemExit(main())
