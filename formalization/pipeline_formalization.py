"""pipeline for human in the loop (both for autoformalization of doman and generated plan) 
An Alloy slicer with per-target signature context.
To run: python3 formalization_demo.py --als filename.als -- seed int
"""

from __future__ import annotations
import argparse
import os
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from anthropic import Anthropic
from controlled_language_translator import translate_slice


client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def call_claude(prompt: str, max_new_tokens: int = 4000, temperature: float = 0) -> str:
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_new_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


@dataclass
class Block:
    kind: str        # Sig / Enum / Fact / Predicate / Function / Assert / Command
    name: str
    start: int       # line index, inclusive
    end: int         # line index, inclusive
    params: str = ""
    occurrence: int = 1  # for non-defined fact or pred blocks, used to distinguish them

    @property
    def uid(self) -> str:
        """Stable identity string"""
        return f"{self.kind}::{self.name}::{self.params}::{self.occurrence}"


class AlloyBackendSlicer:
    """
    Workflow:
      1. Parse the .als file into sig blocks and target blocks(Fact/Pred/Function/Assert/Command)
      2. For each target, collect the sigs it references, including sigs to sigs relations.
      3. Present shuffled snippets one at a time via the REPL loop.
      4. On Reject: call Claude to repair the file, then hot-reload the
         parsed snapshot; the shuffled review queue is never mutated.
    """

    # ------------------------------------------------------------------ #
    # Compiled patterns                                                    
    # ------------------------------------------------------------------ #
    _SIG_RE       = re.compile(r"^\s*(?:abstract\s+|one\s+|lone\s+|some\s+)?sig\s+([A-Za-z_]\w*)\b")
    _ENUM_RE      = re.compile(r"^\s*enum\s+([A-Za-z_]\w*)\b")
    _FACT_RE      = re.compile(r"^\s*fact(?:\s+([A-Za-z_]\w*))?\b")
    _ASSERT_RE    = re.compile(r"^\s*assert\s+([A-Za-z_]\w*)\b")
    _PRED_RE      = re.compile(r"^\s*pred\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?")
    _FUN_RE       = re.compile(r"^\s*fun\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?")
    _RUN_CHECK_RE = re.compile(r"^\s*(run|check)\b(?:\s+([A-Za-z_]\w*))?")
    # match /*  */ 
    _BLOCK_CMT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
    _LINE_CMT_RE  = re.compile(r"(//|--).*")
    _WORD_RE      = re.compile(r"\b[A-Za-z_]\w*\b")

    # Dispatch table for all brace-delimited blocks.
    # Each entry: (regex, kind, is_target)
    #   is_target=True  then goes into self.targets  (reviewed by the user)
    #   is_target=False  then goes into sig_blocks    (used only as context)
    # Populated after the class body once the compiled regexes exist.
    _BRACE_BLOCKS: List[Tuple] = []

    def __init__(self, file_path: str, seed: Optional[int] = None) -> None:
        self.file_path = os.path.abspath(file_path)
        self._seed = seed
        self._rng = random.Random(seed)
        self._load_and_parse()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_snippet(self, target: Block) -> str:
        """Return the fully assembled review snippet for *target*."""
        target_code = "".join(self.source_lines[target.start: target.end + 1]).strip()
        context = self._build_context(self._target_related_sigs(target))

        header = f"// Target: {target.kind} '{target.name}'"
        if target.params:
            header += f" | Params: {target.params}"

        parts = [header, *([context] if context else []), target_code]
        return "\n\n".join(parts) + "\n"

    def find_target_by_uid(self, uid: str) -> Optional[int]:
        """Return the list index of the target whose uid matches, or None."""
        for idx, t in enumerate(self.targets):
            if t.uid == uid:
                return idx
        return None

    def shuffle_targets(self) -> None:
        """Shuffle self.targets reproducibly from the configured seed."""
        self._rng.seed(self._seed)
        self._rng.shuffle(self.targets)

    def reload(self) -> None:
        """Re-read the file and refresh the parsed snapshot."""
        self._load_and_parse()

    def repair_file(self, feedback: str) -> None:
        """Ask Claude to apply *feedback* to the current file and save it. when rejection happening"""
        prompt = f"""You are repairing an Alloy file.

                    RULES:
                    - Output ONLY the full updated file content.
                    - Apply the user feedback precisely.
                    - Do not include explanations.

                    Current file:
                    {''.join(self.source_lines)}

                    User feedback:
                    {feedback}"""
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(call_claude(prompt, temperature=0))

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _load_and_parse(self) -> None:
        """Read alloy file, build two parallel line arrays, parse into blocks.

        source_lines  — raw lines (display / snippet output only).
        _clean_lines  — clean the comment ouside of the function
        """
        raw = open(self.file_path, "r", encoding="utf-8").read()
        no_block = self._BLOCK_CMT_RE.sub(
            lambda m: "\n" * m.group(0).count("\n"), raw
        )
        clean = self._LINE_CMT_RE.sub("", no_block)

        self.source_lines: List[str] = raw.splitlines(keepends=True)
        self._clean_lines: List[str] = clean.splitlines(keepends=True)
        while len(self._clean_lines) < len(self.source_lines):  # defensive
            self._clean_lines.append("")

        self.targets, self.sig_blocks, self.module_open_lines = (
            self._parse_source_blocks()
        )

    def _find_block_end(self, start_idx: int) -> int:
        """Return the indexx*.

        The opening '{' may appear on a later line (next-line brace style), so
        we scan forward until we see it, then track depth until it returns to
        zero.  Returns start_idx if no '{' is ever found (single-line block).
        """
        depth, started = 0, False
        for i in range(start_idx, len(self._clean_lines)):
            text = self._clean_lines[i]
            depth += text.count("{")
            depth -= text.count("}")
            if "{" in text:
                started = True
            if started and depth <= 0:
                return i
        return start_idx

    def _parse_source_blocks(
        self,
    ) -> Tuple[List[Block], Dict[str, Block], List[str]]:
        targets: List[Block] = []
        sig_blocks: Dict[str, Block] = {}
        module_open_lines: List[str] = []
        target_counts: Dict[str, int] = {}

        def add_target(kind: str, name: str, start: int, end: int, params: str = "") -> None:
            base_key = f"{kind}::{name}::{params}"
            target_counts[base_key] = target_counts.get(base_key, 0) + 1
            targets.append(Block(kind, name, start, end, params, target_counts[base_key]))

        i = 0
        while i < len(self._clean_lines):
            line = self._clean_lines[i].strip()

            if line.startswith(("module ", "open ")):
                module_open_lines.append(self.source_lines[i].rstrip("\n"))
                i += 1
                continue

            # single-line run/check commands (no braces).
            m = self._RUN_CHECK_RE.match(line)
            if m:
                kind = "CheckCommand" if m.group(1) == "check" else "RunCommand"
                add_target(kind, m.group(2) or "(anonymous_command)", i, i)
                i += 1
                continue

            # all brace-delimited blocks from the dispatch table.
            matched = False
            for regex, kind, is_target in self._BRACE_BLOCKS:
                m = regex.match(line)
                if not m:
                    continue
                end = self._find_block_end(i)
                name = m.group(1) or f"(anonymous_{kind.lower()})"
                params = (m.groups()[1] or "") if len(m.groups()) > 1 else ""
                if is_target:
                    add_target(kind, name, i, end, params)
                else:
                    sig_blocks[name] = Block(kind, name, i, end)
                i = end + 1
                matched = True
                break

            if not matched:
                i += 1

        return targets, sig_blocks, module_open_lines

    def _sig_dependencies(self, sig: Block) -> set:
        code = "".join(self.source_lines[sig.start: sig.end + 1])
        return (set(self._WORD_RE.findall(code)) - {sig.name}) & self.sig_blocks.keys()

    def _target_related_sigs(self, target: Block) -> List[Block]:
        target_code = "".join(self.source_lines[target.start: target.end + 1])
        selected = set(self._WORD_RE.findall(target_code)) & self.sig_blocks.keys()
        # closure over sig-to-sig dependencies.
        changed = True
        while changed:
            changed = False
            for name in list(selected):
                deps = self._sig_dependencies(self.sig_blocks[name])
                if not deps <= selected:
                    selected |= deps
                    changed = True
        return sorted((self.sig_blocks[n] for n in selected), key=lambda b: b.start)

    def _build_context(self, sigs: List[Block]) -> str:
        parts: List[str] = []
        if self.module_open_lines:
            parts.append("\n".join(self.module_open_lines).strip())
        if sigs:
            sig_text = "\n\n".join(
                "".join(self.source_lines[s.start: s.end + 1]).strip() for s in sigs
            ).strip()
            if sig_text:
                parts.append(sig_text)
        return "\n\n".join(p for p in parts if p).strip()


# Populate the dispatch table after the class body so the compiled regexes exist.
AlloyBackendSlicer._BRACE_BLOCKS = [
    (AlloyBackendSlicer._SIG_RE,    "Sig",       False),
    (AlloyBackendSlicer._ENUM_RE,   "Enum",      False),
    (AlloyBackendSlicer._FACT_RE,   "Fact",      True),
    (AlloyBackendSlicer._PRED_RE,   "Predicate", True),
    (AlloyBackendSlicer._FUN_RE,    "Function",  True),
    (AlloyBackendSlicer._ASSERT_RE, "Assert",    True),
]


# --------------------------------------------------------------------------- #
# REPL entry point                                                             #
# --------------------------------------------------------------------------- #

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AlloyBackendSlicer REPL Loop")
    p.add_argument("--als", required=True, help="Path to target .als file")
    p.add_argument("--seed", type=int, default=None, help="Optional random seed")
    return p


def main() -> None:
    args = _build_arg_parser().parse_args()

    if args.seed is None:
        args.seed = random.randint(0, 999_999)
        print(f"No seed provided. Using auto-generated seed: {args.seed}")

    print("Starting Alloy slicing…")
    slicer = AlloyBackendSlicer(file_path=args.als, seed=args.seed)
    slicer.shuffle_targets()

    # Freeze the review order as a list of UID strings.
    # This queue is never mutated: reload() can freely overwrite slicer.targets
    # with a fresh unshuffled parse without losing our shuffled order.
    review_queue: List[str] = [t.uid for t in slicer.targets]

    total = len(review_queue)
    if total == 0:
        print("No valid Fact/Pred/Fun/Assert/Command blocks found.")
        return

    print(f"\nGenerated {total} slices. Entering review loop…\n")

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

        print("=" * 70)
        print(f"Progress: {index}/{total} reviewed | {total - index} remaining")
        print("=" * 70)
        print(snippet)
        print("=" * 70)
        print("Controlled English translation:")
        print(translate_slice(snippet))
        print("=" * 70)

        cmd = input("Command [Accept / Reject: <feedback> / Stop] > ").strip()
        cmd_lower = cmd.lower()

        if cmd_lower == "accept":
            print("Block accepted.\n")
            index += 1

        elif cmd_lower.startswith("reject"):
            feedback = cmd[len("reject"):].strip(" :")
            print("Sending to Claude for repair…")
            slicer.repair_file(feedback)
            # Refresh parsed snapshot only; review_queue and index are untouched,
            # so the next iteration re-resolves the same UID against the repaired file.
            slicer.reload()
            print("File repaired. Re-reviewing same block…\n")

        elif cmd_lower == "stop":
            print("Stop received. Exiting.")
            return

        else:
            print("Unknown command. Use Accept, Reject: <feedback>, or Stop.\n")

    print("\nReview loop finished: all slices processed.")


if __name__ == "__main__":
    main()