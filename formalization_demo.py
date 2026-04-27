"""Alloy source slicer with per-target(composing required sig in to target blocks type for predicate function and assert) signature context.
 to run: python3 formalization_demo.py --als filename.als """

from __future__ import annotations
import argparse
import os
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple


@dataclass
#each sliced block should be defined as the following:
class Block:
    kind: str # if one is sig/predicate/function/check/run/assert
    name: str
    start: int # row number start
    end: int 
    params: str = ""


class AlloyBackendSlicer:
    #1) slice the block
    #2) find defined sig in related kind, append to that block
    #3) using random permutation, randomly giving one code snippet
    #4) either 3 option: accept(continuing going through the rest of the snippet)
                       # reject and giving opinion (the opinion will give it to llm to revise the logic)
                       # stop: quit the loop

    #determine which kind in the block
    _SIG_RE = re.compile(r"^\s*(?:abstract\s+|one\s+|lone\s+|some\s+)?sig\s+([A-Za-z_]\w*)\b") # sig/abstract 
    _ENUM_RE = re.compile(r"^\s*enum\s+([A-Za-z_]\w*)\b")
    _FACT_RE = re.compile(r"^\s*fact(?:\s+([A-Za-z_]\w*))?\b")
    _ASSERT_RE = re.compile(r"^\s*assert\s+([A-Za-z_]\w*)\b")
    _PRED_RE = re.compile(r"^\s*pred\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?")
    _FUN_RE = re.compile(r"^\s*fun\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?")
    _RUN_CHECK_RE = re.compile(r"^\s*(run|check)\b(?:\s+([A-Za-z_]\w*))?")
    _WORD_RE = re.compile(r"\b[A-Za-z_]\w*\b")

    def __init__(self, alloy_jar_path: str, seed: Optional[int] = None) -> None:
        self.alloy_jar_path = os.path.abspath(alloy_jar_path)
        self._rng = random.Random(seed)

    @staticmethod
    def _read_source_lines(file_path: str) -> List[str]:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.readlines()

    @staticmethod
    def _strip_inline_comment(line: str) -> str:
        # Ignore inline comments for detecting declarations.
        no_double_slash = line.split("//", 1)[0]
        return no_double_slash.split("--", 1)[0]

    #count blocks as braces after ignore inline comment
    def _find_block_end(self, source_lines: Sequence[str], start_idx: int) -> int:
        first = self._strip_inline_comment(source_lines[start_idx])
        if "{" not in first:
            return start_idx

        depth = 0
        for i in range(start_idx, len(source_lines)):
            text = self._strip_inline_comment(source_lines[i])
            depth += text.count("{")
            depth -= text.count("}")
            if depth <= 0:
                return i
        return len(source_lines)- 1

    # using compiler matcher, parse the alloy code into either 1) targets(things we need evaluate) 2) sig or open lines
    def _parse_source_blocks(self, source_lines: Sequence[str]) -> Tuple[List[Block], Dict[str, Block], List[str]]:
        targets: List[Block] = []
        sig_blocks: Dict[str, Block] = {}
        module_open_lines: List[str] = []

        # looping raw lines, wipe out inline comment,  categorizing by if/else for sig enum fact pred function assert and run and check
        i = 0
        while i < len(source_lines):
            raw_line = source_lines[i]
            line = self._strip_inline_comment(raw_line).strip()

            if line.startswith("module ") or line.startswith("open "):
                module_open_lines.append(raw_line.rstrip("\n"))
                i += 1
                continue

            sig_match = self._SIG_RE.match(line)
            if sig_match:
                end = self._find_block_end(source_lines, i)
                name = sig_match.group(1)
                sig_blocks[name] = Block(kind="Sig", name=name, start=i, end=end)
                i = end + 1
                continue

            enum_match = self._ENUM_RE.match(line)
            if enum_match:
                end = self._find_block_end(source_lines, i)
                name = enum_match.group(1)
                sig_blocks[name] = Block(kind="Enum", name=name, start=i, end=end)
                i = end + 1
                continue

            fact_match = self._FACT_RE.match(line)
            if fact_match:
                end = self._find_block_end(source_lines, i)
                name = fact_match.group(1) or "(anonymous_fact)"
                targets.append(Block(kind="Fact", name=name, start=i, end=end))
                i = end + 1
                continue

            pred_match = self._PRED_RE.match(line)
            if pred_match:
                end = self._find_block_end(source_lines, i)
                params = pred_match.group(2) or ""
                targets.append(Block(kind="Predicate", name=pred_match.group(1), start=i, end=end, params=params))
                i = end + 1
                continue

            fun_match = self._FUN_RE.match(line)
            if fun_match:
                end = self._find_block_end(source_lines, i)
                params = fun_match.group(2) or ""
                targets.append(Block(kind="Function", name=fun_match.group(1), start=i, end=end, params=params))
                i = end + 1
                continue

            assert_match = self._ASSERT_RE.match(line)
            if assert_match:
                end = self._find_block_end(source_lines, i)
                targets.append(Block(kind="Assert", name=assert_match.group(1), start=i, end=end))
                i = end + 1
                continue

            cmd_match = self._RUN_CHECK_RE.match(line)
            if cmd_match:
                cmd_name = cmd_match.group(2) or "(anonymous_command)"
                kind = "CheckCommand" if cmd_match.group(1) == "check" else "RunCommand"
                targets.append(Block(kind=kind, name=cmd_name, start=i, end=i))
                i += 1
                continue

            i += 1

        return targets, sig_blocks, module_open_lines

    # figure the sig relation, like extend
    def _sig_dependencies(self, sig_block: Block, sig_names: Set[str], source_lines: Sequence[str]) -> Set[str]:
        code = "".join(source_lines[sig_block.start : sig_block.end + 1])
        names = set(self._WORD_RE.findall(code))
        names.discard(sig_block.name)
        return names.intersection(sig_names)

    def _target_related_sigs(self,target: Block,sig_blocks: Dict[str, Block],source_lines: Sequence[str],) -> List[Block]:
        sig_names = set(sig_blocks.keys())
        target_code = "".join(source_lines[target.start : target.end + 1])
        selected: Set[str] = set(self._WORD_RE.findall(target_code)).intersection(sig_names)

        # Close over sig-to-sig references so dependent signatures are included.
        changed = True
        while changed:
            changed = False
            for name in list(selected):
                deps = self._sig_dependencies(sig_blocks[name], sig_names, source_lines)
                if not deps.issubset(selected):
                    selected.update(deps)
                    changed = True

        ordered = sorted((sig_blocks[name] for name in selected), key=lambda b: b.start)
        return ordered

    def _build_context(self, module_open_lines: Sequence[str], sigs: Sequence[Block], source_lines: Sequence[str]) -> str:
        parts: List[str] = []
        if module_open_lines:
            parts.append("\n".join(module_open_lines).strip())
        if sigs:
            sig_text = "\n\n".join(
                "".join(source_lines[s.start : s.end + 1]).strip() for s in sigs
            ).strip()
            if sig_text:
                parts.append(sig_text)
        return "\n\n".join(p for p in parts if p).strip()

    def extract_all_snippets(self, als_file_path: str) -> List[str]:
        abs_path = os.path.abspath(als_file_path)
        source_lines = self._read_source_lines(abs_path)
        targets, sig_blocks, module_open_lines = self._parse_source_blocks(source_lines)

        snippets: List[str] = []
        for target in targets:
            target_code = "".join(source_lines[target.start : target.end + 1]).strip()
            if not target_code:
                continue

            related_sigs = self._target_related_sigs(target, sig_blocks, source_lines)
            context = self._build_context(module_open_lines, related_sigs, source_lines)

            header = f"// Target: {target.kind} '{target.name}'"
            if target.params:
                header += f" | Params: {target.params}"

            parts = [header]
            if context:
                parts.append(context)
            parts.append(target_code)
            snippets.append("\n\n".join(parts) + "\n")

        self._rng.shuffle(snippets)
        return snippets


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AlloyBackendSlicer REPL Loop")
    parser.add_argument("--als", required=True, help="Path to target .als file")
    parser.add_argument("--jar", default="alloy4.2.jar", help="Path to alloy4.2.jar")
    parser.add_argument("--seed", type=int, default=None, help="Optional random seed")
    return parser


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()

    print("Starting Alloy slicing...")
    slicer = AlloyBackendSlicer(alloy_jar_path=args.jar, seed=args.seed)
    pool = slicer.extract_all_snippets(args.als)
        
    total_count = len(pool)
    if total_count == 0:
        print("No valid Fact/Pred/Fun/Assert/Command blocks found.")
        exit()

    print(f"\nGenerated {total_count} slices. Entering review loop...\n")
    
    completed = 0
    for current_snippet in pool:
        remaining = total_count - completed
        print("=" * 70)
        print(f"Progress: reviewed {completed}/{total_count} | remaining {remaining}")
        print("=" * 70)
        print(current_snippet)
        print("=" * 70)
        
        while True:
            cmd = input("Command [Accept / Reject: feedback / Stop] > ").strip()
            cmd_lower = cmd.lower()
            
            if cmd_lower == "accept":
                print("Block Accepted.\n")
                completed += 1
                break 
                
            elif cmd_lower.startswith("reject"):
                feedback = cmd[6:].strip(" :")
                print(f"Rejected. Feedback: '{feedback}'")
                print("Placeholder: call LLM for repair the block.\n")
                break 
                
            elif cmd_lower == "stop":
                print("Stop received. Exiting.")
                exit()
            else:
                print("Unknown command. Use Accept, Reject, or Stop.")

    print("\nReview loop finished: all slices processed.")