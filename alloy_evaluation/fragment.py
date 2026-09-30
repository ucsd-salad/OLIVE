"""Check the outer shape and obvious placeholders in one generated Alloy predicate."""

from __future__ import annotations

import re

from alloy import strip_comments


TOP_LEVEL = re.compile(
    r"(?:module|open|sig|abstract|one|lone|some|enum|fact|pred|fun|assert|run|check|"
    r"let|var|private)\b"
)
TEMPORAL = re.compile(
    r"\b(?:always|eventually|after|before|once|historically|until|releases|since|"
    r"triggered|steps)\b|'"
)
ARITHMETIC = re.compile(r"\b(?:plus|minus|mul|div|rem|sum)\b|#")


# The hard constraints on a formalized rule, worded for the formalization prompt.
# The prompt reads them from here, so what the model is told and what is enforced
# cannot drift apart. The first four are enforced by check_pred_shape below; the
# last two by the Alloy stage (pipeline.typecheck: the Satisfiable/Refutable runs,
# and a warning counts as a failure).
#
# Two forms. With a context signature (`struct`, e.g. Ctx) the rule is
# `pred rule[c: Ctx]` and talks about one context. With a protocol as the
# vocabulary (struct "") the rule is `pred rule { ... }`, a statement about the
# whole world in the protocol's own signatures and fields; it may quantify over
# them but may not call the protocol's predicates, which are its safety rules.
def hard_constraints(struct: str = "Ctx") -> str:
    header = f"pred rule[c: {struct}] {{ ... }}" if struct else "pred rule { ... }"
    scope_line = (f"no quantifier over `{struct}`: the rule talks only about `c`" if struct else
                  "only the vocabulary's signatures and fields: do not call any predicate or "
                  "function of the protocol (they are its rules, not facts about the situation)")
    return "\n".join(f"- {line}" for line in (
        f"exactly one top-level declaration, `{header}`: no "
        "`fact`, `sig`, `enum`, `fun`, `assert`, `run`, `check`, `open` or `let` beside it",
        scope_line,
        "no temporal operator (`always`, `eventually`, `after`, ...) and no primed field",
        "no arithmetic (`plus`, `minus`, `mul`, `div`, `rem`, `sum`) and no cardinality `#`",
        "not a constant: some %s must satisfy the rule and some must not"
        % ("context" if struct else "world"),
        "no comparison between values of different types (Alloy only warns about it; "
        "here it is rejected)",
    ))


# there should be only one pred and its name must be rule; anything that could make
# the equivalence check vacuous or scope-dependent is rejected before Alloy runs
def check_pred_shape(source: str, struct: str = "Ctx",
                     forbidden: frozenset[str] | set[str] = frozenset()) -> tuple[bool, str]:
    """`struct` "" is the protocol form; `forbidden` holds the protocol's
    predicate and function names, which that form may not call."""
    head = f"pred rule[c: {struct}]" if struct else "pred rule"
    code_lines = [line.rstrip() for line in strip_comments(source).splitlines() if line.strip()]
    if not code_lines:
        return False, f"expected `{head} {{ ... }}`, got nothing"
    header = (re.compile(rf"^pred\s+rule\s*\[\s*c\s*:\s*{struct}\s*\]\s*\{{") if struct
              else re.compile(r"^pred\s+rule\s*\{"))
    if not header.match(code_lines[0].strip()):
        return False, f"expected the generated code to start with `{head} {{`"

    normalized = "\n".join(code_lines)
    top_level = [line for line in code_lines if line == line.lstrip() and TOP_LEVEL.match(line)]
    if re.search(r"\bfact\b", normalized):
        # a fact constrains every model; one that contradicts the vocabulary leaves
        # no model at all, and then every check passes
        return False, "`fact` is not allowed: it would make the equivalence check vacuous"
    if len(top_level) != 1:
        return False, f"expected exactly one top-level declaration: `{head}`"

    body = normalized[normalized.index("{") + 1:]
    if body.count("{") + 1 != body.count("}") or not body.rstrip().endswith("}"):
        return False, "unbalanced braces in `pred rule`"
    body = body.rstrip()[:-1]

    if TEMPORAL.search(body):
        return False, "temporal operators and primed variables are not allowed in a rule"
    if struct and re.search(rf"\b(?:all|some|no|one|lone)\s+(?:disj\s+)?[\w\s,]+:\s*(?:set\s+)?{struct}\b", body):
        return False, f"quantifying over `{struct}` is not allowed: the rule may talk only about `c`"
    called = sorted(set(re.findall(r"\b\w+\b", body)) & set(forbidden))
    if called:
        return False, ("the rule calls %s: state facts with the vocabulary's signatures and "
                       "fields only; the protocol's predicates are its rules" % ", ".join(called))
    if ARITHMETIC.search(body):
        return False, "arithmetic and cardinality are not allowed; compare fields to constants"

    compact = " ".join(body.split())
    while compact.startswith("(") and compact.endswith(")"):
        compact = compact[1:-1].strip()
    if compact in {"", "none = none", "no none", "some univ"}:
        return False, "`pred rule` may not be the constant proposition True"
    if compact in {"some none", "not none = none", "none != none", "no univ"}:
        return False, "`pred rule` may not be the constant proposition False"
    return True, ""
