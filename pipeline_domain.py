"""
Auto-formalization of domain, from txt or pdf to alloy as safety protocol, ground_truth alloy verifier used to comapre with LLM
generated plan.

1. Generate a complete Alloy safety protocol from a natural-language document.
2. Verify and repair that protocol with Alloy plus an LLM feedback loop.
3. Run a human audit over sliced Alloy blocks with controlled-English support.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from anthropic import Anthropic

import pipeline_generated
from controlled_language_translator import translate_slice
from pipeline_formalization import AlloyBackendSlicer


DEFAULT_OUTPUT = "safety_protocol.als"
DEFAULT_SCOPE = 5
DEFAULT_SYNTAX_ATTEMPTS = 5
DEFAULT_LOGIC_ATTEMPTS = 5


client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# Calling Claude with the prompt
def call_claude(prompt, max_new_tokens=4000, temperature=0.7):
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=max_new_tokens,
        temperature=temperature,
        messages=[
            {"role": "user", "content": prompt}
        ],
    )
    with open("ai_log.txt", "a") as f:
        f.write(message.content[0].text + "\n\n" + "=" * 60 + "\n\n")

    return message.content[0].text

_CODE_FENCE_RE = re.compile(r"```(?:alloy|als)?\s*(.*?)```", re.DOTALL | re.I)
_ALLOY_START_RE = re.compile(
    r"(?m)^\s*(?:module\b|open\b|(?:abstract\s+|one\s+|lone\s+|some\s+)?sig\b|"
    r"enum\b|fact\b|pred\b|fun\b|assert\b)"
)
_ALLOY_DECL_RE = re.compile(
    r"(?m)^\s*(?:(?:abstract\s+|one\s+|lone\s+|some\s+)?sig|enum|fact|pred|fun|assert)\b"
)
_SAFETY_ASSERT_RE = re.compile(r"(?m)^\s*assert\s+Safety\b")
_SAFETY_CHECK_RE = re.compile(r"(?m)^\s*check\s+Safety\b")


@dataclass
class AlloyRunResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        return (self.stdout or "") + (self.stderr or "")

    @property
    def syntax_ok(self) -> bool:
        output = self.combined_output
        return (
            self.returncode == 0
            and "Syntax error" not in output
            and "Type error" not in output
            and "Exception" not in output
        )

    @property
    def is_safe(self) -> bool:
        return "No instance found" in self.combined_output

    @property
    def is_unsafe(self) -> bool:
        return "Instance found" in self.combined_output


def read_document(filepath: str) -> str:
    path = Path(filepath).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input document not found: {path}")

    if path.suffix.lower() == ".pdf":
        return _read_pdf(path)

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def generate_initial_alloy(text_content: str, scope: int = DEFAULT_SCOPE) -> str:
    prompt = f"""
Generate a complete Alloy 4.2 safety protocol from the domain document.

OUTPUT ONLY RAW ALLOY CODE.
NO natural language.
NO explanations.
NO markdown.
NO code fences.
All comments must be valid Alloy comments only (`//`, `--`, or `/* ... */`).
The output must start with Alloy code and end with exactly:
check Safety for {scope}

The Alloy file MUST contain:
assert Safety {{ ... }}
check Safety for {scope}

Domain document:
{text_content}
"""
    print("-> Sending highly-constrained prompt to Claude API...")
    response = call_claude(prompt, temperature=0)
    return _prepare_alloy_for_write(response, scope=scope)


def layer1_automated_repair(
    filepath: str,
    document_text: Optional[str] = None,
    max_syntax_attempts: int = DEFAULT_SYNTAX_ATTEMPTS,
    max_logic_attempts: int = DEFAULT_LOGIC_ATTEMPTS,
    scope: int = DEFAULT_SCOPE,
    verbose: bool = True,
) -> bool:
    if verbose:
        print("=== Phase 2: LLM-in-the-Loop Verification ===")
    return verify_and_repair_model(
        filepath=filepath,
        document_text=document_text,
        max_syntax_attempts=max_syntax_attempts,
        max_logic_attempts=max_logic_attempts,
        scope=scope,
        verbose=verbose,
    )


def verify_and_repair_model(
    filepath: str,
    document_text: Optional[str] = None,
    max_syntax_attempts: int = DEFAULT_SYNTAX_ATTEMPTS,
    max_logic_attempts: int = DEFAULT_LOGIC_ATTEMPTS,
    scope: int = DEFAULT_SCOPE,
    verbose: bool = True,
) -> bool:
    path = str(Path(filepath).expanduser().resolve())
    original_document = _format_original_document(document_text)

    for logic_attempt in range(1, max_logic_attempts + 1):
        if verbose:
            print(f"\n[Logic Attempt {logic_attempt}/{max_logic_attempts}]")

        if not _repair_syntax_loop(
            path,
            original_document,
            max_syntax_attempts,
            scope,
            verbose,
        ):
            raise RuntimeError(
                "Unable to repair Alloy syntax. The LLM may be generating invalid formats."
            )

        result = _run_alloy_cli(path)
        if verbose:
            _print_alloy_result(result)

        if result.is_safe:
            if verbose:
                print("SAFE: Alloy reported 'No instance found'.")
            return True

        model = Path(path).read_text(encoding="utf-8")
        alloy_output = result.combined_output.strip() or "(Alloy produced no output.)"
        counterexample = (
            'Project safety convention: "No instance found" means SAFE; '
            '"Instance found" means UNSAFE because Alloy found a counterexample.\n\n'
            f"Alloy raw output:\n{alloy_output}"
        )
        prompt = _build_logic_repair_prompt(
            document_text=original_document,
            code=model,
            alloy_output=counterexample,
            scope=scope,
        )

        if verbose:
            print("UNSAFE or unverifiable result. Asking Claude to repair logic...")

        repaired = call_claude(prompt, temperature=0)
        try:
            _write_alloy_file(path, repaired, scope=scope)
        except ValueError as exc:
            if verbose:
                print(f"Rejected invalid LLM logic repair output: {exc}")
            continue

    raise RuntimeError(
        f"Unable to prove the model SAFE after {max_logic_attempts} logic attempts."
    )


def layer2_human_audit(
    filepath: str,
    document_text: Optional[str] = None,
    max_syntax_attempts: int = DEFAULT_SYNTAX_ATTEMPTS,
    max_logic_attempts: int = DEFAULT_LOGIC_ATTEMPTS,
    scope: int = DEFAULT_SCOPE,
    seed: Optional[int] = None,
) -> None:
    path = str(Path(filepath).expanduser().resolve())
    print("=== Phase 3: Human-in-the-Loop Audit ===")
    slicer = AlloyBackendSlicer(file_path=path, seed=seed)
    slicer.shuffle_targets()

    review_queue: List[str] = [target.uid for target in slicer.targets]
    total = len(review_queue)

    if total == 0:
        print("No Fact/Pred/Fun/Assert/Command blocks found for audit.")
        return

    print(f"Generated {total} audit slices.\n")
    index = 0

    while index < len(review_queue):
        uid = review_queue[index]
        match_idx = slicer.find_target_by_uid(uid)

        if match_idx is None:
            print(f"Target '{uid}' no longer exists after repair. Skipping.\n")
            index += 1
            continue

        target = slicer.targets[match_idx]
        snippet = slicer.get_snippet(target)

        print("=" * 72)
        print(f"Progress: {index}/{total} accepted | {total - index} remaining")
        print("=" * 72)
        print("Original Alloy snippet:")
        print(snippet)
        print("=" * 72)
        print("Controlled English translation:")
        print(_translate_for_audit(snippet))
        print("=" * 72)

        command = input("Command [Accept / Reject: <feedback> / Stop] > ").strip()
        command_lower = command.lower()

        if command_lower == "accept":
            print("Block accepted.\n")
            index += 1
            continue

        if command_lower.startswith("reject"):
            feedback = command[len("reject") :].strip(" :")
            if not feedback:
                print("Please include feedback after Reject.\n")
                continue

            print("Sending rejection feedback to the LLM repair step...")
            _repair_from_human_feedback(
                filepath=path,
                document_text=_format_original_document(document_text),
                snippet=snippet,
                feedback=feedback,
                scope=scope,
            )

            print("Re-verifying the repaired protocol before continuing...")
            layer1_automated_repair(
                path,
                document_text=document_text,
                max_syntax_attempts=max_syntax_attempts,
                max_logic_attempts=max_logic_attempts,
                scope=scope,
                verbose=False,
            )
            slicer.reload()
            print("Repaired protocol is verified SAFE. Re-reviewing the same block.\n")
            continue

        if command_lower == "stop":
            print(f"Stop received. Final Alloy file saved at: {path}")
            return

        print("Unknown command. Use Accept, Reject: <feedback>, or Stop.\n")

    print(f"Audit complete. Final Alloy file saved at: {path}")


def main() -> None:
    args = _build_arg_parser().parse_args()
    output_path = str(Path(args.output).expanduser().resolve())

    if args.skip_generation:
        document_text = read_document(args.document) if args.document else None
        if not Path(output_path).exists():
            raise FileNotFoundError(
                f"--skip-generation was used, but output file does not exist: {output_path}"
            )
        print("=== Phase 1: Skipping Auto-Formalization ===")
        print(f"Using existing Alloy model: {output_path}")
        if args.document:
            print(f"Loaded original domain document: {Path(args.document).resolve()}")
    else:
        if not args.document:
            raise ValueError("A document path is required unless --skip-generation is used.")

        print("=== Phase 1: Initializing Auto-Formalization ===")
        document_text = read_document(args.document)
        alloy_model = generate_initial_alloy(document_text, scope=args.scope)
        _write_alloy_file(output_path, alloy_model, scope=args.scope)
        print(f"Initial Alloy safety protocol written to: {output_path}")

    layer1_automated_repair(
        output_path,
        document_text=document_text,
        max_syntax_attempts=args.max_syntax_attempts,
        max_logic_attempts=args.max_logic_attempts,
        scope=args.scope,
        verbose=True,
    )

    if args.skip_audit:
        print("=== Phase 3: Skipping Human-in-the-Loop Audit ===")
        print(f"Verified Alloy safety protocol saved at: {output_path}")
        return

    layer2_human_audit(
        output_path,
        document_text=document_text,
        max_syntax_attempts=args.max_syntax_attempts,
        max_logic_attempts=args.max_logic_attempts,
        scope=args.scope,
        seed=args.seed,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate, verify, repair, and audit an Alloy safety protocol."
    )
    parser.add_argument("document", nargs="?", help="Path to the source domain document.")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Path for the generated Alloy file. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--skip-generation",
        action="store_true",
        help="Use --output as an existing Alloy file and start at Phase 2.",
    )
    parser.add_argument(
        "--skip-audit",
        action="store_true",
        help="Stop after automated verification succeeds.",
    )
    parser.add_argument("--scope", type=int, default=DEFAULT_SCOPE)
    parser.add_argument("--max-syntax-attempts", type=int, default=DEFAULT_SYNTAX_ATTEMPTS)
    parser.add_argument("--max-logic-attempts", type=int, default=DEFAULT_LOGIC_ATTEMPTS)
    parser.add_argument("--seed", type=int, default=None)
    return parser


def _read_pdf(path: Path) -> str:
    readers = ("pypdf", "PyPDF2")
    for module_name in readers:
        try:
            module = __import__(module_name)
            reader = module.PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            if text.strip():
                return text
        except Exception:
            continue

    try:
        result = subprocess.run(
            ["pdftotext", str(path), "-"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except FileNotFoundError:
        pass

    raise RuntimeError(
        "Could not extract PDF text. Install `pypdf`/`PyPDF2` or provide a text file."
    )


def _build_syntax_repair_prompt(
    document_text: str,
    code: str,
    exact_stderr: str,
    scope: int,
) -> str:
    return f"""
Fix the Alloy 4.2 syntax errors.

OUTPUT ONLY RAW ALLOY CODE.
NO natural language.
NO explanations.
NO markdown.
NO code fences.
All comments must be valid Alloy comments only (`//`, `--`, or `/* ... */`).
The output must start with Alloy code and end with exactly:
check Safety for {scope}

Keep:
assert Safety {{ ... }}
check Safety for {scope}

Original domain document:
{document_text}

Broken Alloy code:
{code}

Compiler error:
{exact_stderr}
"""


def _build_logic_repair_prompt(
    document_text: str,
    code: str,
    alloy_output: str,
    scope: int,
) -> str:
    return f"""
Fix the Alloy 4.2 model logic so `check Safety` is safe.

OUTPUT ONLY RAW ALLOY CODE.
NO natural language.
NO explanations.
NO markdown.
NO code fences.
All comments must be valid Alloy comments only (`//`, `--`, or `/* ... */`).
The output must start with Alloy code and end with exactly:
check Safety for {scope}

Keep:
assert Safety {{ ... }}
check Safety for {scope}

Original domain document:
{document_text}

Unsafe Alloy code:
{code}

Alloy output:
{alloy_output}
"""


def _repair_syntax_loop(
    filepath: str,
    original_document: str,
    max_attempts: int,
    scope: int,
    verbose: bool,
) -> bool:
    for attempt in range(1, max_attempts + 1):
        _normalize_verification_command(filepath, scope)
        result = _run_alloy_cli(filepath)

        if verbose:
            print(f"[Syntax Attempt {attempt}/{max_attempts}]")
            _print_alloy_result(result)

        if result.syntax_ok:
            if verbose:
                print("Syntax check passed.")
            return True

        code = Path(filepath).read_text(encoding="utf-8")
        exact_stderr = (
            result.stderr.strip()
            or result.combined_output.strip()
            or "(stderr was empty)"
        )
        prompt = _build_syntax_repair_prompt(
            document_text=original_document,
            code=code,
            exact_stderr=exact_stderr,
            scope=scope,
        )

        if verbose:
            print("Syntax failed. Asking Claude to repair the model...")

        repaired = call_claude(prompt, temperature=0)
        try:
            _write_alloy_file(filepath, repaired, scope=scope)
        except ValueError as exc:
            if verbose:
                print(f"Rejected invalid LLM repair output: {exc}")

    return False


def _repair_from_human_feedback(
    filepath: str,
    document_text: str,
    snippet: str,
    feedback: str,
    scope: int,
) -> None:
    current_file = Path(filepath).read_text(encoding="utf-8")
    prompt = f"""
You are repairing a complete Alloy safety protocol after human review.

The human reviewer rejected this Alloy slice.

CRITICAL RULES:
1. You MUST strictly adhere to the Original Domain Document provided below.
2. DO NOT invent generic templates like Process/Resource.
3. DO NOT remove existing domain constraints unless they directly contradict the human feedback and Original Domain Document.
4. Output ONLY the full updated raw `.als` file content. NO conversational text, NO markdown fences.
5. Keep an assertion named exactly `Safety`.
6. Keep `check Safety for {scope}` as the first and only run/check command.

Original Domain Document:
{document_text}

Current full Alloy file:
{current_file}

Rejected slice:
{snippet}

Human feedback:
{feedback}
"""
    repaired = call_claude(prompt, temperature=0)
    _write_alloy_file(filepath, repaired, scope=scope)


def _run_alloy_cli(filepath: str) -> AlloyRunResult:
    file_path = str(Path(filepath).expanduser().resolve())
    java_dir = Path(pipeline_generated.JAVA_DIR)
    jar = Path(pipeline_generated.JAR)
    java_file = Path(pipeline_generated.JAVA_FILE)
    class_file = Path(pipeline_generated.CLASS_FILE)

    if not Path(file_path).exists():
        raise FileNotFoundError(f"Alloy file not found: {file_path}")
    if not java_dir.is_dir():
        raise FileNotFoundError(f"Alloy command-line directory not found: {java_dir}")
    if not jar.exists():
        raise FileNotFoundError(f"Alloy jar not found: {jar}")
    if not java_file.exists() and not class_file.exists():
        raise FileNotFoundError(
            f"AlloyCommandline.java or .class not found in: {java_dir}"
        )

    if not class_file.exists():
        compile_result = subprocess.run(
            ["javac", "-cp", "alloy4.2.jar", "AlloyCommandline.java"],
            cwd=str(java_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            return AlloyRunResult(
                compile_result.returncode,
                compile_result.stdout,
                compile_result.stderr,
            )

    run_result = subprocess.run(
        [
            "java",
            "-cp",
            f".{os.pathsep}alloy4.2.jar",
            "AlloyCommandline",
            file_path,
        ],
        cwd=str(java_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    return AlloyRunResult(run_result.returncode, run_result.stdout, run_result.stderr)


def _normalize_verification_command(filepath: str, scope: int) -> None:
    path = Path(filepath)
    code = path.read_text(encoding="utf-8")
    if not _SAFETY_ASSERT_RE.search(code):
        return

    normalized = _normalize_verification_command_text(code, scope)
    if normalized != code:
        path.write_text(normalized, encoding="utf-8")


def _normalize_verification_command_text(code: str, scope: int) -> str:
    if not _SAFETY_ASSERT_RE.search(code):
        return code.rstrip() + "\n"

    lines = code.splitlines(keepends=True)
    kept: List[str] = []
    depth = 0
    skipping_command_depth: Optional[int] = None

    for line in lines:
        clean_line = _strip_inline_comment(line)
        clean = clean_line.strip()

        if skipping_command_depth is not None:
            skipping_command_depth += clean_line.count("{")
            skipping_command_depth -= clean_line.count("}")
            if skipping_command_depth <= 0:
                skipping_command_depth = None
            continue

        if depth == 0 and re.match(r"^(run|check)\b", clean):
            command_depth = clean.count("{") - clean.count("}")
            if command_depth > 0:
                skipping_command_depth = command_depth
            continue

        kept.append(line)
        depth += clean_line.count("{")
        depth -= clean_line.count("}")
        depth = max(depth, 0)

    return "".join(kept).rstrip() + f"\n\ncheck Safety for {scope}\n"


def _strip_inline_comment(line: str) -> str:
    no_double_slash = line.split("//", 1)[0]
    return no_double_slash.split("--", 1)[0]


def _format_original_document(document_text: Optional[str]) -> str:
    if document_text and document_text.strip():
        return document_text.strip()
    return "[Original domain document missing. Preserve current domain intent.]"


def _prepare_alloy_for_write(
    response: str,
    scope: int,
    require_safety: bool = True,
) -> str:
    candidate = _clean_llm_alloy_response(response)
    candidate = _normalize_verification_command_text(candidate, scope)
    _validate_alloy_payload(candidate, require_safety=require_safety)
    return candidate


def _clean_llm_alloy_response(response: str) -> str:
    text = response.strip()
    if not text:
        raise ValueError("LLM returned an empty response; refusing to overwrite Alloy file.")

    fence = _CODE_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    else:
        start = _first_alloy_start(text)
        if start is None:
            raise ValueError("LLM output does not contain an Alloy top-level declaration.")
        text = text[start:].strip()

    if "```" in text:
        raise ValueError("LLM output still contains markdown fences after cleaning.")

    return text.rstrip() + "\n"


def _validate_alloy_payload(content: str, require_safety: bool = True) -> None:
    if not content.strip():
        raise ValueError("Cleaned Alloy content is empty.")
    if not _ALLOY_DECL_RE.search(content):
        raise ValueError("Cleaned output does not contain Alloy declarations.")
    invalid_line = _find_invalid_natural_language_line(content)
    if invalid_line:
        raise ValueError(
            "Cleaned output appears to contain non-Alloy natural language: "
            f"{invalid_line}"
        )
    if require_safety and not _SAFETY_ASSERT_RE.search(content):
        raise ValueError("Cleaned Alloy model is missing `assert Safety`.")
    if require_safety and not _SAFETY_CHECK_RE.search(content):
        raise ValueError("Cleaned Alloy model is missing `check Safety`.")


def _find_invalid_natural_language_line(content: str) -> Optional[str]:
    uncommented = _remove_alloy_comments(content)
    suspicious = re.compile(
        r"(?i)^\s*(?:"
        r"i understand|here is|here's|certainly|sure|the fixed code|"
        r"explanation|note:|why this works|this works because|"
        r"i changed|i have|the above|in this model|"
        r"let me know|hope this helps"
        r")\b"
    )
    alloy_line = re.compile(
        r"^\s*(?:"
        r"module\b|open\b|abstract\b|one\b|lone\b|some\b|sig\b|enum\b|"
        r"fact\b|pred\b|fun\b|assert\b|check\b|run\b|all\b|no\b|some\b|one\b|"
        r"lone\b|let\b|disj\b|else\b|and\b|or\b|implies\b|iff\b|not\b|in\b|"
        r"this\b|set\b|seq\b|Int\b|String\b|none\b|univ\b|iden\b|"
        r"[A-Za-z_]\w*\s*[:=.]|[{}()\[\],|&+~^!*<>=#-]|$"
        r")"
    )
    # Alloy expression operators that almost never appear in English prose.
    # A line containing any of these (e.g. `A + B + C` continuation lines) is
    # treated as valid Alloy even when it does not start with a keyword.
    alloy_operator_anywhere = re.compile(r"->|<:|:>|=>|<=>|[+&|~^]")
    for line in uncommented.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if suspicious.search(stripped):
            return stripped[:120]
        if alloy_line.search(stripped):
            continue
        if alloy_operator_anywhere.search(stripped):
            continue
        words = re.findall(r"[A-Za-z]{3,}", stripped)
        if len(words) >= 4:
            return stripped[:120]
    return None


def _remove_alloy_comments(content: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    lines = []
    for line in without_block.splitlines():
        line = line.split("//", 1)[0]
        line = line.split("--", 1)[0]
        lines.append(line)
    return "\n".join(lines)


def _first_alloy_start(text: str) -> Optional[int]:
    match = _ALLOY_START_RE.search(text)
    return match.start() if match else None


def _write_alloy_file(
    filepath: str,
    content: str,
    scope: int = DEFAULT_SCOPE,
    require_safety: bool = True,
) -> None:
    prepared = _prepare_alloy_for_write(
        content,
        scope=scope,
        require_safety=require_safety,
    )
    pipeline_generated.save_file(prepared, filepath)


def _print_alloy_result(result: AlloyRunResult) -> None:
    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.stderr.strip():
        print(result.stderr.rstrip())
    if not result.stdout.strip() and not result.stderr.strip():
        print("(Alloy produced no output.)")


def _translate_for_audit(snippet: str) -> str:
    try:
        return translate_slice(snippet)
    except Exception as exc:
        return f"[Translation unavailable: {exc}]"


if __name__ == "__main__":
    main()
