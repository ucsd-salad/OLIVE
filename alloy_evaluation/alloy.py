"""The one place that runs Alloy: execute a file, read back what each command found."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_JAR = "/Applications/Alloy.app/Contents/Resources/org.alloytools.alloy.dist.jar"


def jar() -> str:
    return os.environ.get("ALLOY_JAR", DEFAULT_JAR)


def alloy_available() -> bool:
    return shutil.which("java") is not None and Path(jar()).exists()


@dataclass
class Result:
    ok: bool                                   # compiled with no error and no warning
    error: str = ""                            # the compiler's error or warning text
    outcomes: dict[str, str] = field(default_factory=dict)       # command -> SAT | UNSAT
    instances: dict[str, dict[str, str]] = field(default_factory=dict)  # command -> Ctx fields
    worlds: dict[str, str] = field(default_factory=dict)   # command -> every atom's fields, rendered


SUMMARY = re.compile(r"^\s*\d+\.\s+(?:run|check)\s+(\S+)\s+.*?\b(UNSAT|SAT)\s*$", re.M)


def execute(path: Path, *, timeout: int = 120) -> Result:
    """Run every command in `path` with overflow forbidden.

    Alloy reports a comparison between disjoint types (`c.ageSaid = Yes`) as a
    warning and still answers every command, so a warning fails the run: a rule
    that constrains nothing would otherwise pass as equivalent to anything.
    """
    if not alloy_available():
        return Result(False, "Alloy is not available")
    out = path.with_name(path.stem + "_out")
    try:
        process = subprocess.run(
            ["java", "-jar", jar(), "exec", "-f", "-n", "-o", out.name, path.name],
            cwd=str(path.parent),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return Result(False, f"Alloy timed out after {timeout}s")
    text = (process.stdout + process.stderr).strip()
    # Messages name the file by absolute path; the model repairing it only needs the name.
    for directory in {str(path.parent), str(path.parent.resolve())}:
        text = text.replace(directory + os.sep, "")

    if process.returncode != 0:
        return Result(False, compiler_message(text) or text or "Alloy failed")
    warning = re.search(r"(?ms)^Warning\s*\n(.*?)(?=^\s*\d+\.\s+(?:run|check)\s|\Z)", text)
    # an unused variable changes nothing a rule says; every other warning does
    # (disjoint comparison, always-empty join) and fails the run
    if warning and all("This variable is unused" in w
                       for w in re.split(r"(?m)^\s*\d+\.\s", warning.group(1)) if w.strip()):
        warning = None
    if warning:
        return Result(False, "Warning: " + warning.group(1).strip())

    outcomes = {name: verdict for name, verdict in SUMMARY.findall(text)}
    instances, worlds = {}, {}
    receipt = out / "receipt.json"
    if receipt.exists():
        commands = json.loads(receipt.read_text(encoding="utf-8")).get("commands", {})
        for name, command in commands.items():
            for solution in command.get("solution", []):
                for instance in solution.get("instances", []):
                    instances[name] = context_fields(instance.get("values", {}))
                    worlds[name] = render_world(instance.get("values", {}))
                    break
                break
    return Result(True, "", outcomes, instances, worlds)


def compiler_message(text: str) -> str:
    """The first report without the Java stack trace or the CLI's own prefix."""
    lines = []
    for line in text.splitlines():
        if line.startswith("\tat ") or line.startswith("Error"):
            break
        lines.append(line)
    message = "\n".join(lines).strip()
    message = re.sub(r"^\[main\] ERROR alloy - excuting sub command CLI:exec error ", "", message)
    # The report is printed twice; keep one copy.
    half = message.find("\n" + message.splitlines()[0], 1) if message else -1
    return (message[:half] if half > 0 else message).strip()


def atom(name: str) -> str:
    """`vocab/Yes$0` -> `Yes`; integers come back as they are."""
    return name.rpartition("/")[2].partition("$")[0]


def context_fields(values: dict) -> dict[str, str]:
    """The field assignment of the single Ctx atom in an instance."""
    for key, relations in values.items():
        if atom(key) == "Ctx" and relations:
            return {
                name: ", ".join(atom(tuple_[-1]) for tuple_ in tuples)
                for name, tuples in relations.items()
            }
    return {}


def render_world(values: dict) -> str:
    """One line per atom that has field values: `Patron$0: age=1, inWater=Spa$0`.
    Atoms of the ordering utility and atoms without fields are left out."""
    lines = []
    for key, relations in values.items():
        if not relations or "/Ord" in key or "ordering/" in key:
            continue
        name = key.rpartition("/")[2]
        fields = ", ".join(
            "%s=%s" % (field, "+".join(atom(tuple_[-1]) for tuple_ in tuples) or "none")
            for field, tuples in sorted(relations.items()))
        lines.append("%s: %s" % (name, fields))
    return "\n".join(sorted(lines))


def widen_scope(scope: str, *sources: str) -> str:
    """`scope` with an Int bitwidth wide enough for every integer constant in
    `sources` (the rule for choosing it is int_bitwidth's); never narrower than
    the bitwidth the scope already names."""
    constants = [int(n) for source in sources
                 for n in re.findall(r"(?<![\w$])\d+(?![\w$])", strip_comments(source))]
    if not constants:
        return scope
    needed = max(4, max(constants).bit_length() + 2)
    current = re.search(r"(\d+)\s+Int\b", scope)
    if current:
        width = max(int(current.group(1)), needed)
        return scope[:current.start(1)] + str(width) + scope[current.end(1):]
    # `but` may only follow a default count (`for 5 but 9 Int`); otherwise the
    # scopes are a comma list (`for exactly 1 Ctx, 9 Int`)
    joiner = " but " if re.fullmatch(r"\s*for\s+\d+\s*", scope) else ", "
    return f"{scope}{joiner}{needed} Int"


def int_bitwidth(*sources: str) -> int | None:
    """Enough bits for every integer constant M to have both of its neighbours.

    With only field-versus-constant comparisons, two rules can disagree only at a
    constant or one step away from it, so a range covering [-2M, 2M) is exhaustive.
    A bitwidth that is too small makes unequal rules look equivalent. Returns None
    when no source mentions Int.
    """
    if not any(re.search(r"\bInt\b", source) for source in sources):
        return None
    constants = [
        int(number)
        for source in sources
        for number in re.findall(r"(?<![\w$])\d+(?![\w$])", strip_comments(source))
    ]
    largest = max([1, *constants])
    return max(4, largest.bit_length() + 2)


def strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return "\n".join(re.split(r"--|//", line, maxsplit=1)[0] for line in source.splitlines())


def scope(bitwidth: int | None) -> str:
    return "for exactly 1 Ctx" + (f", {bitwidth} Int" if bitwidth else "")
