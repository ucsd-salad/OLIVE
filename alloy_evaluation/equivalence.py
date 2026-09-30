"""Build the Alloy model that compares the two rule modules, and read its verdict."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import alloy


def rule_of(source: str) -> str:
    """The `pred rule[...] { ... }` block of a module, without the wrapper around it."""
    start = re.search(r"(?m)^pred\s+rule\b", source)
    if not start:
        return ""
    depth, opened = 0, False
    for index in range(source.index("{", start.start()), len(source)):
        if source[index] == "{":
            depth, opened = depth + 1, True
        elif source[index] == "}":
            depth -= 1
            if opened and depth == 0:
                return source[start.start():index + 1].strip()
    return ""


def renamed(rule: str, name: str) -> str:
    return re.sub(r"^pred\s+rule\b", f"pred {name}", rule.strip(), count=1)


#checking equivalence
def theorem_source(struct: str, original_rule: str, prime_rule: str,
                   bitwidth: int | None) -> str:
    """Two one-directional checks rather than one `iff`: the counterexample then also
    says which rule is the stronger one.

    `Sanity` must be satisfiable. If it is not, the world has no model at all and
    both checks pass vacuously, so their verdict means nothing.
    """
    scope = alloy.scope(bitwidth)
    return f"""open vocab

{renamed(original_rule, "ruleOriginal")}

{renamed(prime_rule, "rulePrime")}

run Sanity {{}} {scope}
check OriginalImpliesPrime {{ all c: {struct} | ruleOriginal[c] implies rulePrime[c] }} {scope}
check PrimeImpliesOriginal {{ all c: {struct} | rulePrime[c] implies ruleOriginal[c] }} {scope}
"""


def world_theorem_source(opens: list[str], original_rule: str, prime_rule: str,
                         scope: str) -> str:
    """The protocol form: both rules are statements about a whole world in the
    protocol's words (`pred rule { ... }`), compared over every world within the
    protocol's own scope. Bounded, unlike the one-context form: a disagreement
    that needs more atoms than the scope allows is not seen."""
    header = "".join(f"open {module}\n" for module in opens)
    return f"""{header}
{renamed(original_rule, "ruleOriginal")}

{renamed(prime_rule, "rulePrime")}

run Sanity {{}} {scope}
check OriginalImpliesPrime {{ ruleOriginal implies rulePrime }} {scope}
check PrimeImpliesOriginal {{ rulePrime implies ruleOriginal }} {scope}
"""


@dataclass
class Verdict:
    decided: bool                  # False when Alloy could not give a trustworthy answer
    equivalent: bool
    evidence: str
    counterexample: dict[str, str] | None = None


def decide(path: Path, source: str, timeout: int, scope_note: str = "") -> Verdict:
    path.write_text(source, encoding="utf-8")
    result = alloy.execute(path, timeout=timeout)
    if not result.ok:
        return Verdict(False, False, "Alloy did not accept the equivalence model.\n" + result.error)
    outcomes = result.outcomes
    if outcomes.get("Sanity") != "SAT":
        return Verdict(False, False, "The model has no instance at all, so any check would pass vacuously.")
    for name, holds, fails in (
        ("OriginalImpliesPrime", "y_original", "y_prime"),
        ("PrimeImpliesOriginal", "y_prime", "y_original"),
    ):
        if outcomes.get(name) == "SAT":
            example = result.instances.get(name, {})
            shown = ", ".join(f"{field} = {value}" for field, value in example.items())
            if not shown:   # the protocol form: no single context, show the world
                shown = "\n  ".join(result.worlds.get(name, "").splitlines()[:40])
            return Verdict(
                True, False,
                f"Alloy found a counterexample: {holds} holds but {fails} does not when\n"
                f"  {shown or '(no field assignment recovered)'}",
                example,
            )
        if outcomes.get(name) != "UNSAT":
            return Verdict(False, False, f"Alloy returned no verdict for `{name}`.")
    return Verdict(
        True, True,
        scope_note or "Alloy found no counterexample to `all c | ruleOriginal[c] iff "
                      "rulePrime[c]` (exhaustive: a rule reads only one context).",
    )
