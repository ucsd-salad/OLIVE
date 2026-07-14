#!/usr/bin/env python3
"""Condition graph-path priors on confirmed yes/no nodes.

For a confirmed entry node, every complete path to a decision/outcome receives
the product of its local branch priors.  Because graph.json does not provide
edge weights, outgoing branches use equal priors.

Confirmed nodes are simple path conditions:

* every yes node must occur on the path;
* every no node must not occur on the path.

For every graph event v, the returned value is exactly:

    P(v | conditions)
      = mass(compatible complete paths containing v)
        / mass(all compatible complete paths)

This is a structural conditional path probability, not a learned estimate.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_GRAPH_PATH = Path("pipeline_out/head_discomfort_toy/event_graph/graph.json")
TERMINAL_EVENT_TYPES = {"decision", "outcome"}


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


@dataclass(frozen=True)
class WeightedPath:
    """One complete entry-to-terminal path and its fixed branch-prior mass."""

    nodes: tuple[str, ...]
    node_set: frozenset[str]
    weight: float


class PathEnumerationLimitError(RuntimeError):
    """Raised rather than returning probabilities from an incomplete path set."""


class DynamicProbabilityCalculator:
    """Calculate per-event probabilities under hard yes/no path conditions."""

    def __init__(
        self,
        node_types: dict[str, str],
        edges: list[tuple[str, str]],
        *,
        node_labels: dict[str, str] | None = None,
        max_terminal_paths: int = 10_000,
    ) -> None:
        self.node_types = node_types
        self.node_labels = node_labels or {node_id: node_id for node_id in node_types}
        self.node_order = {node_id: index for index, node_id in enumerate(node_types)}
        self.outgoing: dict[str, list[str]] = defaultdict(list)
        for src, dst in edges:
            if src in node_types and dst in node_types and dst not in self.outgoing[src]:
                self.outgoing[src].append(dst)
        self.max_terminal_paths = max(1, max_terminal_paths)
        self._path_cache: dict[str, tuple[WeightedPath, ...]] = {}

    @classmethod
    def from_graph_path(
        cls,
        graph_path: Path,
        *,
        max_terminal_paths: int = 10_000,
    ) -> "DynamicProbabilityCalculator":
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        node_types = {
            item["id"]: item.get("eventType", "condition")
            for item in graph.get("nodes", [])
            if isinstance(item, dict) and item.get("id")
        }
        node_labels = {
            item["id"]: item.get("label", item["id"])
            for item in graph.get("nodes", [])
            if isinstance(item, dict) and item.get("id")
        }
        edges = [
            (item["src"], item["dst"])
            for item in graph.get("edges", [])
            if isinstance(item, dict) and item.get("src") in node_types and item.get("dst") in node_types
        ]
        return cls(
            node_types,
            edges,
            node_labels=node_labels,
            max_terminal_paths=max_terminal_paths,
        )

    def calculate(
        self,
        entry_node: str | None,
        confirmed_yes: Iterable[str] = (),
        confirmed_no: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Return P(event | confirmed_yes, confirmed_no) for every event."""
        entry = entry_node if entry_node in self.node_types else None
        yes = _dedupe(node_id for node_id in confirmed_yes if node_id in self.node_types)
        no = _dedupe(node_id for node_id in confirmed_no if node_id in self.node_types)

        if entry is not None:
            yes = [entry, *(node_id for node_id in yes if node_id != entry)]

        result: dict[str, Any] = {
            "entry": entry,
            "given": {"yes": yes, "no": no},
            "events": [],
            "priorPathCount": 0,
            "compatiblePathCount": 0,
            "priorPathMass": 0.0,
            "compatiblePathMass": 0.0,
            "contradiction": False,
        }

        if entry is None:
            result["events"] = [
                {"id": node_id, "p": None}
                for node_id in self.node_types
            ]
            return result

        paths = self._complete_paths(entry)
        compatible_paths = [
            path
            for path in paths
            if self._matches_conditions(path, yes, no)
        ]
        prior_mass = sum(path.weight for path in paths)
        compatible_mass = sum(path.weight for path in compatible_paths)

        result.update({
            "priorPathCount": len(paths),
            "compatiblePathCount": len(compatible_paths),
            "priorPathMass": round(prior_mass, 12),
            "compatiblePathMass": round(compatible_mass, 12),
            "contradiction": compatible_mass <= 0,
        })

        node_mass: dict[str, float] = defaultdict(float)
        for path in compatible_paths:
            for node_id in path.node_set:
                node_mass[node_id] += path.weight

        result["events"] = [
            {
                "id": node_id,
                "p": (
                    round(node_mass.get(node_id, 0.0) / compatible_mass, 6)
                    if compatible_mass > 0
                    else None
                ),
            }
            for node_id in self.node_types
        ]
        return result

    def _complete_paths(self, entry_node: str) -> tuple[WeightedPath, ...]:
        cached = self._path_cache.get(entry_node)
        if cached is not None:
            return cached

        paths: list[WeightedPath] = []

        def visit(
            node_id: str,
            path: tuple[str, ...],
            visited: frozenset[str],
            weight: float,
        ) -> None:
            if self.node_types[node_id] in TERMINAL_EVENT_TYPES:
                if len(paths) >= self.max_terminal_paths:
                    raise PathEnumerationLimitError(
                        f"entry {entry_node!r} has more than "
                        f"{self.max_terminal_paths} complete paths"
                    )
                paths.append(WeightedPath(path, visited, weight))
                return

            children = self.outgoing.get(node_id, [])
            if not children:
                return

            branch_prior = 1.0 / len(children)
            for child in children:
                if child in visited:
                    continue
                visit(
                    child,
                    (*path, child),
                    visited | {child},
                    weight * branch_prior,
                )

        visit(entry_node, (entry_node,), frozenset({entry_node}), 1.0)
        completed = tuple(paths)
        self._path_cache[entry_node] = completed
        return completed

    @staticmethod
    def _matches_conditions(
        path: WeightedPath,
        confirmed_yes: list[str],
        confirmed_no: list[str],
    ) -> bool:
        if path.node_set.intersection(confirmed_no):
            return False
        return set(confirmed_yes).issubset(path.node_set)

    def format_lines(
        self,
        result: dict[str, Any],
        *,
        include_conditioned: bool = False,
    ) -> list[str]:
        """Format unconditioned graph events as readable probability lines."""
        conditioned = {
            *result.get("given", {}).get("yes", []),
            *result.get("given", {}).get("no", []),
        }
        return [
            (
                f"{self.node_labels.get(event['id'], event['id'])} - probability undefined"
                if event.get("p") is None
                else f"{self.node_labels.get(event['id'], event['id'])} - probability {float(event['p']) * 100:.2f}%"
            )
            for event in result.get("events", [])
            if include_conditioned or event.get("id") not in conditioned
        ]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calculate P(event | confirmed yes/no nodes) from graph-path priors."
    )
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--entry", required=True, help="Confirmed entry node id.")
    parser.add_argument("--yes", nargs="*", default=[], help="Confirmed yes node ids.")
    parser.add_argument("--no", nargs="*", default=[], help="Confirmed no node ids.")
    parser.add_argument("--max-terminal-paths", type=int, default=10_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    calculator = DynamicProbabilityCalculator.from_graph_path(
        args.graph,
        max_terminal_paths=args.max_terminal_paths,
    )
    result = calculator.calculate(args.entry, args.yes, args.no)
    print("\n".join(calculator.format_lines(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
