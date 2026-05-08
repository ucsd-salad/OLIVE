"""
Controlled English translator for sliced Alloy code.

Pipeline:
    Alloy slice
        -> controlled English template translation

Design:
    - Preserve Alloy variable names exactly.
    - Translate only fixed Alloy syntax patterns.
    - Use alloy_operator_mapping.py only as fallback.
    - Do not globally replace operators such as "." or "->".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


try:
    from alloy_operator_mapping import explain_with_patterns
except Exception:
    explain_with_patterns = None


# ---------------------------------------------------------------------
# Basic utilities
# ---------------------------------------------------------------------


def strip_inline_comment(line: str) -> str:
    """Remove Alloy line comments from one line."""
    line = line.split("//", 1)[0]
    line = line.split("--", 1)[0]
    return line.strip()


def remove_block_comments(text: str) -> str:
    """Remove /* ... */ comments."""
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_outer_parens(text: str) -> str:
    """Remove one layer of enclosing parentheses if they wrap the whole expression."""
    text = text.strip()

    changed = True
    while changed and text.startswith("(") and text.endswith(")"):
        changed = False
        depth = 0
        wraps_all = True

        for i, ch in enumerate(text):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(text) - 1:
                    wraps_all = False
                    break

        if wraps_all:
            text = text[1:-1].strip()
            changed = True

    return text


def split_top_level_once(text: str, operator: str) -> Optional[Tuple[str, str]]:
    """
    Split text once on a top-level operator.

    Top-level means outside (), [], and {}.
    """
    depth = 0
    i = 0

    while i < len(text):
        ch = text[i]

        if ch in "([{":
            depth += 1
            i += 1
            continue

        if ch in ")]}":
            depth -= 1
            i += 1
            continue

        if depth == 0 and text.startswith(operator, i):
            left = text[:i].strip()
            right = text[i + len(operator):].strip()
            return left, right

        i += 1

    return None

def split_top_level_implication(text: str) -> Optional[Tuple[str, str]]:
    """
    Split top-level Alloy implication:
        A implies B
        A => B

    Important:
    - Do this before comparison parsing.
    - Avoid treating >= or <= as implication.
    """
    depth = 0
    i = 0

    while i < len(text):
        ch = text[i]

        if ch in "([{":
            depth += 1
            i += 1
            continue

        if ch in ")]}":
            depth -= 1
            i += 1
            continue

        if depth == 0:
            if text.startswith(" implies ", i):
                return text[:i].strip(), text[i + len(" implies "):].strip()

            if text.startswith("=>", i):
                return text[:i].strip(), text[i + len("=>"):].strip()

        i += 1

    return None

def split_top_level_many(text: str, operator: str) -> List[str]:
    """
    Split text on a top-level operator.

    Example:
        A and (B and C) and D
    becomes:
        ["A", "(B and C)", "D"]
    """
    parts: List[str] = []
    depth = 0
    start = 0
    i = 0

    while i < len(text):
        ch = text[i]

        if ch in "([{":
            depth += 1
            i += 1
            continue

        if ch in ")]}":
            depth -= 1
            i += 1
            continue

        if depth == 0 and text.startswith(operator, i):
            parts.append(text[start:i].strip())
            i += len(operator)
            start = i
            continue

        i += 1

    parts.append(text[start:].strip())
    return [p for p in parts if p]


def split_top_level_commas(text: str) -> List[str]:
    return split_top_level_many(text, ",")

def split_adjacent_parenthesized_statements(text: str) -> List[str]:
    """
    Split:
        (A) (B) (C)
    into:
        [A, B, C]

    Only works when the whole text is a sequence of top-level parenthesized
    expressions.
    """
    text = text.strip()
    parts: List[str] = []
    depth = 0
    start: Optional[int] = None
    last_end = 0

    i = 0
    while i < len(text):
        ch = text[i]

        if ch == "(":
            if depth == 0:
                gap = text[last_end:i].strip()
                if gap:
                    return [text]
                start = i + 1
            depth += 1

        elif ch == ")":
            depth -= 1
            if depth == 0:
                if start is None:
                    return [text]
                parts.append(text[start:i].strip())
                last_end = i + 1

        i += 1

    if depth != 0:
        return [text]

    trailing = text[last_end:].strip()
    if trailing:
        return [text]

    return parts if parts else [text]


def strip_statement(text: str) -> str:
    text = strip_inline_comment(text)
    text = text.rstrip(";").strip()
    return strip_outer_parens(text)


# ---------------------------------------------------------------------
# Statement splitting
# ---------------------------------------------------------------------


DECL_START_RE = re.compile(
    r"^\s*(?:"
    r"(?:abstract\s+|one\s+|lone\s+|some\s+)?sig\b|"
    r"enum\b|"
    r"fact\b|"
    r"pred\b|"
    r"fun\b|"
    r"assert\b|"
    r"run\b|"
    r"check\b|"
    r"module\b|"
    r"open\b"
    r")"
)


def extract_brace_body(code: str) -> str:
    """Return the text inside the outermost braces."""
    start = code.find("{")
    end = code.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return code[start + 1:end]


def split_block_statements(body: str) -> List[str]:
    """
    Split a block body into top-level statements.

    This is intentionally conservative:
    - It treats each non-empty top-level line as one statement.
    - It keeps nested braced blocks together.
    - It strips comments.
    """
    body = remove_block_comments(body)

    statements: List[str] = []
    current: List[str] = []
    depth = 0

    def should_continue(line_text: str) -> bool:
        return bool(
            re.search(
                r"(?:\|\s*|=>\s*|\bimplies\b\s*|\bor\b\s*|\band\b\s*|\|\|\s*|&&\s*|\belse\b\s*)$",
                line_text,
            )
        )

    for raw_line in body.splitlines():
        line = strip_inline_comment(raw_line)
        if not line:
            continue

        current.append(line)

        for ch in line:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1

        if depth <= 0:
            statement = normalize_space(" ".join(current))
            if statement and not should_continue(statement):
                statements.append(statement)
                current = []
                depth = 0

    if current:
        statement = normalize_space(" ".join(current))
        if statement:
            statements.append(statement)

    return statements


def split_slice_into_units(slice_text: str) -> List[str]:
    """
    Split a sliced Alloy snippet into top-level units:
    - // Target header
    - module/open lines
    - sig/enum/fact/pred/fun/assert blocks
    - run/check commands
    """
    text = remove_block_comments(slice_text)
    lines = text.splitlines()

    units: List[str] = []
    current: List[str] = []
    depth = 0
    in_block = False

    for raw_line in lines:
        line_no_comment = strip_inline_comment(raw_line)

        if not line_no_comment:
            continue

        # Preserve target header as a unit.
        if raw_line.strip().startswith("// Target:"):
            if current:
                units.append("\n".join(current).strip())
                current = []
                depth = 0
                in_block = False
            units.append(raw_line.strip())
            continue

        # Start a new declaration unit if needed.
        if DECL_START_RE.match(line_no_comment) and not in_block:
            if current:
                units.append("\n".join(current).strip())
                current = []

        current.append(line_no_comment)

        if "{" in line_no_comment:
            in_block = True

        depth += line_no_comment.count("{")
        depth -= line_no_comment.count("}")

        if in_block and depth <= 0:
            units.append("\n".join(current).strip())
            current = []
            depth = 0
            in_block = False

        # run/check/module/open are usually single-line declarations.
        elif not in_block and re.match(r"^\s*(run|check|module|open)\b", line_no_comment):
            units.append("\n".join(current).strip())
            current = []

    if current:
        units.append("\n".join(current).strip())

    return [u for u in units if u]


# ---------------------------------------------------------------------
# Translation core
# ---------------------------------------------------------------------


@dataclass
class TranslationConfig:
    translate_context: bool = True
    include_raw_alloy: bool = True
    number_statements: bool = True
    fallback_enabled: bool = True


class ControlledEnglishTranslator:
    """
    Template-based translator for a limited Alloy subset.

    This is not a full Alloy parser.
    It is a deterministic controlled-English translator for fixed syntax.
    """

    def __init__(self, config: Optional[TranslationConfig] = None) -> None:
        self.config = config or TranslationConfig()

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def translate_slice(self, slice_text: str) -> str:
        units = split_slice_into_units(slice_text)

        outputs: List[str] = []

        for unit in units:
            if unit.startswith("// Target:"):
                outputs.append(self.translate_target_header(unit))
                continue

            if unit.startswith("module "):
                outputs.append(self.translate_module(unit))
                continue

            if unit.startswith("open "):
                outputs.append(self.translate_open(unit))
                continue

            if self.is_signature_or_enum(unit):
                if self.config.translate_context:
                    outputs.append(self.translate_declaration(unit))
                continue

            outputs.append(self.translate_declaration(unit))

        return "\n\n".join(o for o in outputs if o.strip()).strip()

    def translate_statement(self, statement: str) -> str:
        return self._translate_statement(statement)

    def translate_inline(self, expression: str) -> str:
        rendered = self._translate_statement(expression)
        return rendered[:-1] if rendered.endswith(".") else rendered

    # -----------------------------------------------------------------
    # Unit-level translation
    # -----------------------------------------------------------------

    @staticmethod
    def is_signature_or_enum(unit: str) -> bool:
        return bool(
            re.match(
                r"^\s*(?:abstract\s+|one\s+|lone\s+|some\s+)?sig\b|^\s*enum\b",
                unit,
            )
        )

    def translate_target_header(self, header: str) -> str:
        # Example:
        # // Target: Predicate 'adultCPRPlan' | Params: [p: Plan]
        m = re.match(
            r"//\s*Target:\s*(?P<kind>\w+)\s+'(?P<name>[^']+)'(?:\s*\|\s*Params:\s*(?P<params>.*))?",
            header,
        )
        if not m:
            return header

        kind = m.group("kind")
        name = m.group("name")
        params = m.group("params")

        if params:
            return f"Target: {kind} {name} with parameters {params}."

        return f"Target: {kind} {name}."

    def translate_module(self, unit: str) -> str:
        m = re.match(r"^\s*module\s+(.+)$", unit)
        if m:
            return f"Module declaration: {m.group(1).strip()}."
        return self.fallback(unit)

    def translate_open(self, unit: str) -> str:
        m = re.match(r"^\s*open\s+(.+)$", unit)
        if m:
            return f"Open declaration: {m.group(1).strip()}."
        return self.fallback(unit)

    def translate_declaration(self, unit: str) -> str:
        unit = unit.strip()

        if re.match(r"^\s*(?:abstract\s+|one\s+|lone\s+|some\s+)?sig\b", unit):
            return self.translate_sig(unit)

        if unit.startswith("enum "):
            return self.translate_enum(unit)

        if unit.startswith("fact"):
            return self.translate_fact(unit)

        if unit.startswith("pred"):
            return self.translate_pred(unit)

        if unit.startswith("fun"):
            return self.translate_fun(unit)

        if unit.startswith("assert"):
            return self.translate_assert(unit)

        if unit.startswith("run"):
            return self.translate_run(unit)

        if unit.startswith("check"):
            return self.translate_check(unit)

        return self.fallback(unit)

    def translate_sig(self, unit: str) -> str:
        """
        Translate:
            sig A {}
            abstract sig A {}
            one sig A extends B {}
            sig A { f: one T, g: set U }
        """
        header = unit[: unit.find("{")].strip() if "{" in unit else unit.strip()
        body = extract_brace_body(unit)

        m = re.match(
            r"^(?:(?P<abstract>abstract)\s+)?"
            r"(?:(?P<multiplicity>one|lone|some)\s+)?"
            r"sig\s+(?P<name>[A-Za-z_]\w*)"
            r"(?:\s+extends\s+(?P<extends>[A-Za-z_]\w*))?"
            r"(?:\s+in\s+(?P<subset>[A-Za-z_]\w*))?",
            header,
        )

        if not m:
            return self.fallback(unit)

        name = m.group("name")
        multiplicity = m.group("multiplicity")
        is_abstract = bool(m.group("abstract"))
        extends = m.group("extends")
        subset = m.group("subset")

        parts: List[str] = []

        if is_abstract:
            parts.append(f"Abstract signature {name} is declared.")
        elif multiplicity:
            parts.append(f"{multiplicity.capitalize()} signature {name} is declared.")
        else:
            parts.append(f"Signature {name} is declared.")

        if extends:
            parts.append(f"Signature {name} extends {extends}.")

        if subset:
            parts.append(f"Signature {name} is in {subset}.")

        fields = self.translate_fields(body)
        if fields:
            parts.append("Fields:")
            parts.extend(f"- {field}" for field in fields)

        return "\n".join(parts)

    def translate_enum(self, unit: str) -> str:
        m = re.match(r"^enum\s+([A-Za-z_]\w*)\s*\{(.*)\}\s*$", unit, flags=re.DOTALL)
        if not m:
            return self.fallback(unit)

        name = m.group(1)
        items = [x.strip() for x in split_top_level_commas(m.group(2)) if x.strip()]

        return f"Enum {name} contains {', '.join(items)}."

    def translate_fields(self, body: str) -> List[str]:
        if not body.strip():
            return []

        raw_fields = split_top_level_commas(normalize_space(body))
        fields: List[str] = []

        for field in raw_fields:
            m = re.match(r"^([A-Za-z_]\w*)\s*:\s*(.+)$", field)
            if not m:
                continue
            name, typ = m.groups()
            fields.append(f"{name} has type {typ.strip()}.")

        return fields

    def translate_fact(self, unit: str) -> str:
        m = re.match(r"^fact(?:\s+([A-Za-z_]\w*))?", unit)
        name = m.group(1) if m and m.group(1) else "(anonymous_fact)"
        body = extract_brace_body(unit)
        return self.translate_named_block("Fact", name, body)

    def translate_pred(self, unit: str) -> str:
        m = re.match(r"^pred\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?", unit)
        if not m:
            return self.fallback(unit)

        name = m.group(1)
        params = m.group(2) or ""
        body = extract_brace_body(unit)

        title = f"Predicate {name}"
        if params:
            title += f" with parameters {params}"
        title += ":"

        return self.translate_block_with_title(title, body)

    def translate_fun(self, unit: str) -> str:
        m = re.match(
            r"^fun\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*(?::\s*([^{]+))?",
            unit,
        )
        if not m:
            return self.fallback(unit)

        name = m.group(1)
        params = m.group(2) or ""
        return_type = m.group(3).strip() if m.group(3) else ""
        body = extract_brace_body(unit)

        title = f"Function {name}"
        if params:
            title += f" with parameters {params}"
        if return_type:
            title += f" returns {return_type}"
        title += ":"

        return self.translate_block_with_title(title, body)

    def translate_assert(self, unit: str) -> str:
        m = re.match(r"^assert\s+([A-Za-z_]\w*)", unit)
        if not m:
            return self.fallback(unit)

        name = m.group(1)
        body = extract_brace_body(unit)
        return self.translate_named_block("Assertion", name, body)

    def translate_run(self, unit: str) -> str:
        m = re.match(r"^run(?:\s+([A-Za-z_]\w*))?(.*)$", unit)
        if not m:
            return self.fallback(unit)

        name = m.group(1) or "(anonymous_command)"
        rest = m.group(2).strip()

        if rest:
            return f"Run command {name} with options {rest}."
        return f"Run command {name}."

    def translate_check(self, unit: str) -> str:
        m = re.match(r"^check(?:\s+([A-Za-z_]\w*))?(.*)$", unit)
        if not m:
            return self.fallback(unit)

        name = m.group(1) or "(anonymous_command)"
        rest = m.group(2).strip()

        if rest:
            return f"Check command {name} with options {rest}."
        return f"Check command {name}."

    def translate_named_block(self, kind: str, name: str, body: str) -> str:
        return self.translate_block_with_title(f"{kind} {name}:", body)

    def translate_block_with_title(self, title: str, body: str) -> str:
        statements = split_block_statements(body)
        lines = [title]

        if not statements:
            lines.append("No statements.")
            return "\n".join(lines)

        for idx, stmt in enumerate(statements, start=1):
            rendered = self._translate_statement(stmt)
            if self.config.number_statements:
                lines.append(f"{idx}. {rendered}")
            else:
                lines.append(rendered)

        return "\n".join(lines)

    # -----------------------------------------------------------------
    # Expression / statement translation
    # -----------------------------------------------------------------

    def _translate_statement(self, statement: str) -> str:
        text = strip_statement(statement)

        if not text:
            return ""

        # Block expression:
        # { A B C }
        if text.startswith("{") and text.endswith("}"):
            inner = text[1:-1].strip()
            statements = split_block_statements(inner)

            # Fix compressed block:
            #   (A => B) (C => D) (E => F)
            if len(statements) == 1:
                statements = split_adjacent_parenthesized_statements(statements[0])

            if not statements:
                return "The block is empty."

            rendered = self.render_block_items_multiline(statements)
            return f"All of the following hold: {rendered}."

        # let x = expr | body
        split = split_top_level_once(text, " | ")
        if text.startswith("let ") and split:
            left, body = split
            m = re.match(r"^let\s+([A-Za-z_]\w*)\s*=\s*(.+)$", left)
            if m:
                var, expr = m.groups()
                return f"Let {var} equal {expr.strip()}. Then {self.translate_inline(body)}."

        # Quantifiers:
        # all p: Plan | expr
        q = self.match_quantifier(text)
        if q:
            quantifier, var_decls, body = q
            return self.render_quantifier(quantifier, var_decls, body)

        # Conditional:
        # condition => A else B
        conditional = self.match_conditional(text)
        if conditional:
            cond, then_expr, else_expr = conditional
            return (
                f"If {self.translate_inline(cond)}, "
                f"then {self.translate_inline(then_expr)}; "
                f"otherwise {self.translate_inline(else_expr)}."
            )

        # iff / <=> before implication
        for op in [" iff ", " <=> "]:
            split = split_top_level_once(text, op)
            if split:
                left, right = split
                return f"{self.translate_inline(left)} if and only if {self.translate_inline(right)}."

        # implies / =>
        # Must be handled before equality and comparison.
        split = split_top_level_implication(text)
        if split:
            left, right = split
            return f"If {self.translate_inline(left)}, then {self.translate_inline(right)}."
        
        # or
        parts = split_top_level_many(text, " or ")
        if len(parts) > 1:
            rendered = "; ".join(self.translate_inline(p) for p in parts)
            return f"At least one of the following is true: {rendered}."

        parts = split_top_level_many(text, " || ")
        if len(parts) > 1:
            rendered = "; ".join(self.translate_inline(p) for p in parts)
            return f"At least one of the following is true: {rendered}."

        # and
        parts = split_top_level_many(text, " and ")
        if len(parts) > 1:
            rendered = "; ".join(self.translate_inline(p) for p in parts)
            return f"Both the following are true: {rendered}."

        parts = split_top_level_many(text, " && ")
        if len(parts) > 1:
            rendered = "; ".join(self.translate_inline(p) for p in parts)
            return f"Both the following are true: {rendered}."

        _TEMPORAL_UNARY = [
            ("always",      "in every current and future state"),
            ("eventually",  "in some current or future state"),
            ("after",       "in the immediately next state"),
            ("before",      "in the immediately previous state"),
            ("once",        "in some previous state including the current one"),
            ("historically","in every previous state including the current one"),
        ]
        for keyword, phrase in _TEMPORAL_UNARY:
            m = re.match(rf"^{keyword}\s+(.+)$", text, re.IGNORECASE)
            if m:
                inner = self.translate_inline(m.group(1).strip())
                return f"{inner} holds {phrase}."
        
        # Cardinality comparison:
        # #p.steps >= 1
        m = re.match(r"^#\s*(.+?)\s*(=|!=|>=|=<|<=|>|<)\s*(-?\d+)$", text)
        if m:
            expr, op, number = m.groups()
            op_text = self.render_comparator(op)
            return f"The cardinality of {expr.strip()} {op_text} {number}."

        # Multiplicity expression:
        # some A
        # no A
        # one A
        # lone A
        m = re.match(r"^(some|no|one|lone)\s+(.+)$", text)
        if m and ":" not in text:
            multiplicity, expr = m.groups()
            return self.render_multiplicity_expr(multiplicity, expr.strip())

        # Negated membership:
        # not A in B
        m = re.match(r"^not\s+(.+?)\s+in\s+(.+)$", text)
        if m:
            left, right = m.groups()
            return f"{left.strip()} is not in {right.strip()}."

        # Extension form if AI produces it:
        # A not in B
        m = re.match(r"^(.+?)\s+not\s+in\s+(.+)$", text)
        if m:
            left, right = m.groups()
            return f"{left.strip()} is not in {right.strip()}."

        # Plain negation:
        # not E
        m = re.match(r"^not\s+(.+)$", text)
        if m:
            return f"It is not true that {self.translate_inline(m.group(1))}."

        # Sequence equality:
        # p.steps = A -> B -> C
        # Special meaning only for .steps / steps.
        m = re.match(r"^(.+?)\s*=\s*(.+->.+)$", text)
        if m:
            left, right = m.groups()
            left = left.strip()
            items = [x.strip() for x in right.split("->") if x.strip()]

            if left == "steps" or left.endswith(".steps"):
                return f"{left} equals sequence({', '.join(items)})."

            return f"{left} equals {' arrow '.join(items)}."

        # Inequality
        m = re.match(r"^(.+?)\s*!=\s*(.+)$", text)
        if m:
            left, right = m.groups()
            return f"{left.strip()} does not equal {right.strip()}."

        # Alloy alternative not-equal form
        m = re.match(r"^(.+?)\s*!\s*=\s*(.+)$", text)
        if m:
            left, right = m.groups()
            return f"{left.strip()} does not equal {right.strip()}."

        # Comparisons
        m = re.match(r"^(.+?)\s*(>=|=<|<=|>|<)\s*(.+)$", text)
        if m:
            left, op, right = m.groups()
            return f"{left.strip()} {self.render_comparator(op)} {right.strip()}."

        # Equality
        m = re.match(r"^(.+?)\s*=\s*(.+)$", text)
        if m:
            left, right = m.groups()
            return f"{left.strip()} equals {right.strip()}."

        # Membership
        m = re.match(r"^(.+?)\s+in\s+(.+)$", text)
        if m:
            left, right = m.groups()
            return f"{left.strip()} is in {right.strip()}."

        # Relational operations fallback but still controlled.
        relational = self.translate_relational_expr(text)
        if relational:
            return relational + "."

        return self.fallback(text)

    def match_quantifier(self, text: str) -> Optional[Tuple[str, str, str]]:
        """
        Match:
            all p: Plan | body
            some disj a, b: Action | body
            all p: Plan, q: Plan | body
        """
        split = split_top_level_once(text, " | ")
        if not split:
            return None

        prefix, body = split
        m = re.match(r"^(all|some|no|one|lone)\s+(.+)$", prefix)
        if not m:
            return None

        quantifier = m.group(1)
        var_decls = m.group(2).strip()

        if ":" not in var_decls:
            return None

        return quantifier, var_decls, body

    def render_quantifier(self, quantifier: str, var_decls: str, body: str) -> str:

        var_decls = re.sub(r"\bdisj\b", "pairwise distinct", var_decls)

        body_text = self.translate_inline(body)

        quantifier_text = {
            "all": "For every",
            "some": "There exists some",
            "no": "There is no",
            "one": "There is exactly one",
            "lone": "There is at most one",
        }[quantifier]

        if quantifier == "all":
            return f"{quantifier_text} {var_decls}, {body_text}."

        return f"{quantifier_text} {var_decls} such that {body_text}."

    def match_conditional(self, text: str) -> Optional[Tuple[str, str, str]]:
        """
        Match Alloy conditional:
            condition => thenExpr else elseExpr
        """
        first = split_top_level_once(text, " => ")
        if not first:
            return None

        cond, rest = first
        second = split_top_level_once(rest, " else ")
        if not second:
            return None

        then_expr, else_expr = second
        return cond, then_expr, else_expr

    @staticmethod
    def render_comparator(op: str) -> str:
        return {
            "=": "equals",
            "!=": "does not equal",
            ">": "is greater than",
            ">=": "is greater than or equal to",
            "<": "is less than",
            "<=": "is less than or equal to",
            "=<": "is less than or equal to",
        }[op]

    @staticmethod
    def render_multiplicity_expr(multiplicity: str, expr: str) -> str:
        if multiplicity == "some":
            return f"{expr} is non-empty."
        if multiplicity == "no":
            return f"{expr} is empty."
        if multiplicity == "one":
            return f"{expr} has exactly one element."
        if multiplicity == "lone":
            return f"{expr} has at most one element."
        return f"{multiplicity} {expr}."

    def translate_relational_expr(self, text: str) -> Optional[str]:
        """
        Controlled fallback for common relational expressions.

        This keeps variable names intact.
        """
        text = strip_outer_parens(text)

        for op, phrase in [
            ("++", "override"),
            ("<:", "domain-restrict"),
            (":>", "range-restrict"),
            ("&", "intersect"),
            ("+", "plus"),
            ("-", "minus"),
        ]:
            split = split_top_level_once(text, f" {op} ")
            if split:
                left, right = split
                return f"{left} {phrase} {right}"

        if text.startswith("~"):
            return f"transpose of {text[1:].strip()}"

        if text.startswith("^"):
            return f"transitive closure of {text[1:].strip()}"

        if text.startswith("*"):
            return f"reflexive transitive closure of {text[1:].strip()}"

        return None

    def fallback(self, text: str) -> str:
        text = normalize_space(text)
        
        if self.config.fallback_enabled and explain_with_patterns is not None:
            try:
                explained = explain_with_patterns(text)
                if explained and explained != text:
                    return explained
            except Exception:
                pass

        return text
    
    def render_block_items_multiline(self, statements: List[str], indent: str = "    ") -> str:
        """
        Render block statements as readable multiline controlled English.

        Example:
            If A, then B;
            If C, then D.
        """
        rendered_items = []

        for idx, stmt in enumerate(statements):
            item = self.translate_inline(stmt)

            if idx < len(statements) - 1:
                rendered_items.append(f"{indent}{item};")
            else:
                rendered_items.append(f"{indent}{item}.")

        return "\n".join(rendered_items)


# ---------------------------------------------------------------------
# Convenience module-level functions
# ---------------------------------------------------------------------


_DEFAULT_TRANSLATOR = ControlledEnglishTranslator()


def translate_statement(statement: str) -> str:
    return _DEFAULT_TRANSLATOR.translate_statement(statement)


def translate_inline(expression: str) -> str:
    return _DEFAULT_TRANSLATOR.translate_inline(expression)


def translate_slice(slice_text: str) -> str:
    return _DEFAULT_TRANSLATOR.translate_slice(slice_text)


# def translate_all_slices(snippets: List[str]) -> str:
#     """
#     Render output as:
#         Alloy slice
#         Controlled English translation
#         Alloy slice
#         Controlled English translation
#         ...
#     """
#     chunks: List[str] = []

#     for i, snippet in enumerate(snippets, start=1):
#         translation = translate_slice(snippet)

#         chunks.append(f"===== Slice {i}: Alloy =====")
#         chunks.append(snippet.strip())
#         chunks.append("")
#         chunks.append(f"===== Slice {i}: Controlled English =====")
#         chunks.append(translation.strip())
#         chunks.append("")

#     return "\n".join(chunks).strip()


if __name__ == "__main__":
    demo = """
// Target: Predicate 'adultCPRPlan' | Params: [p: Plan]

one sig AdultCPR extends Scenario {}

pred adultCPRPlan[p: Plan] {
  p.scenario = AdultCPR
  p.steps = CheckSceneSafety -> CallEMS -> StartChestCompressions -> UseAED
  not UseAED in p.forbiddenActions
  Unresponsive in p.conditions implies StartChestCompressions in p.requiredActions
  all q: Plan | one q.scenario
  #p.steps > 0
}
"""

    print(translate_slice(demo))
