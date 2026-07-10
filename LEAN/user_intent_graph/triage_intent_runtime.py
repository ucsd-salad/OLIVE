#!/usr/bin/env python3
"""Generic deterministic graph walker.

The runtime intentionally does not know domain rules. It only knows how to:

- read nodes and edges from graph.json;
- match a user utterance to likely graph nodes;
- keep a current node pointer and a path;
- treat outgoing neighbors of the current node as candidate next nodes;
- ask candidate questions in graph order;
- move to a candidate only after positive feedback;
- avoid asking the same candidate twice from the same current node;
- stop when the current node is a terminal decision/outcome node.

Any medical, triage, or diagnosis logic must live in the graph, not here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_GRAPH_PATH = Path("pipeline_out/etat_module1/event_graph/graph.json")
DEFAULT_TRACE_LOG = Path("pipeline_out/etat_module1/intent_trace.jsonl")
TERMINAL_EVENT_TYPES = {"decision", "outcome"}

YES_WORDS = {
    "yes",
    "y",
    "yeah",
    "yep",
    "true",
    "present",
    "confirmed",
    "correct",
    "affirmative",
    "是",
    "有",
    "对",
    "对的",
}
NO_WORDS = {
    "no",
    "n",
    "nope",
    "false",
    "absent",
    "negative",
    "none",
    "否",
    "没有",
    "没",
    "不是",
}
NO_PHRASES = {("not", "present")}


@dataclass(frozen=True)
class Node:
    id: str
    event_type: str
    label: str
    source_text: str = ""
    description: str = ""


@dataclass(frozen=True)
class Edge:
    id: str
    src: str
    dst: str
    relation_label: str


@dataclass
class Fact:
    node_id: str
    status: str
    source: str
    surface: str
    explanation: str = ""


@dataclass
class PendingQuestion:
    node_id: str
    question: str
    reason: str
    context_node: str | None = None


@dataclass
class SessionState:
    facts: dict[str, Fact] = field(default_factory=dict)
    pending_question: PendingQuestion | None = None
    current_node_id: str | None = None
    path: list[str] = field(default_factory=list)
    asked_edges: set[tuple[str | None, str]] = field(default_factory=set)
    turn_index: int = 0
    done: bool = False
    stop_message: str | None = None


def normalize_text(text: str) -> str:
    text = text.lower().replace("'", "").replace("-", " ").replace("/", " ")
    text = re.sub(r"[^a-z0-9.\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_identifier(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def tokenize_for_match(text: str) -> list[str]:
    normalized = normalize_text(text)
    return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", normalized)


def classify_answer(text: str) -> tuple[str | None, bool, str]:
    normalized = normalize_text(text)
    if not normalized:
        return None, False, ""
    words = normalized.split()
    first = words[0]
    if first in YES_WORDS:
        return "yes", len(words) == 1, " ".join(words[1:])
    if first in NO_WORDS:
        return "no", len(words) == 1, " ".join(words[1:])
    for phrase in NO_PHRASES:
        phrase_len = len(phrase)
        if tuple(words[:phrase_len]) == phrase:
            return "no", len(words) == phrase_len, " ".join(words[phrase_len:])
    return None, False, ""


def visible_response(result: dict[str, Any]) -> str:
    if result.get("message"):
        return result["message"]
    if result.get("decision"):
        return f"decision: {result['decision']}"
    if result.get("questions"):
        return result["questions"][0]["question"]
    return "which graph node?"


class ProtocolGraph:
    def __init__(self, nodes: dict[str, Node], edges: list[Edge]) -> None:
        self.nodes = nodes
        self.edges = edges
        self.out_edges: dict[str, list[Edge]] = {}
        self.in_edges: dict[str, list[Edge]] = {}
        for edge in edges:
            self.out_edges.setdefault(edge.src, []).append(edge)
            self.in_edges.setdefault(edge.dst, []).append(edge)

    @classmethod
    def from_json(cls, path: Path) -> "ProtocolGraph":
        data = json.loads(path.read_text(encoding="utf-8"))
        nodes = {
            item["id"]: Node(
                id=item["id"],
                event_type=item.get("eventType", "condition"),
                label=item.get("label", item["id"]),
                source_text=item.get("sourceText", ""),
                description=item.get("description", ""),
            )
            for item in data.get("nodes", [])
            if isinstance(item, dict) and item.get("id")
        }
        edges = [
            Edge(
                id=item.get("id", f"{item.get('src')}->{item.get('dst')}"),
                src=item["src"],
                dst=item["dst"],
                relation_label=item.get("relationLabel", item.get("label", "related")),
            )
            for item in data.get("edges", [])
            if isinstance(item, dict) and item.get("src") in nodes and item.get("dst") in nodes
        ]
        return cls(nodes, edges)

    def neighbors(self, node_id: str) -> list[str]:
        return [edge.dst for edge in self.out_edges.get(node_id, [])]


class TriageIntentRuntime:
    def __init__(self, graph: ProtocolGraph) -> None:
        self.graph = graph

    @classmethod
    def from_graph_path(cls, graph_path: Path = DEFAULT_GRAPH_PATH) -> "TriageIntentRuntime":
        return cls(ProtocolGraph.from_json(graph_path))

    def new_session(self) -> SessionState:
        return SessionState()

    def process_turn(self, state: SessionState, user_text: str) -> dict[str, Any]:
        answer, bare_answer, explanation = classify_answer(user_text)
        current_ids: list[str] = []
        forced_question: PendingQuestion | None = None
        state.stop_message = None

        if answer and state.pending_question:
            current_ids.extend(self._apply_feedback(state, answer, user_text, explanation))
        elif not bare_answer:
            matched = self._match_nodes(user_text)
            if matched:
                current_ids.extend(self._handle_input_match(state, matched, user_text))
                if state.pending_question and state.pending_question.reason == "confirm_starting_node":
                    forced_question = state.pending_question
            elif state.current_node_id is None:
                state.stop_message = "no graph node matched; rephrase or name a node"

        decision, record = self._decision_record(state)
        question = None if decision else forced_question or self._next_question(state)
        state.pending_question = question

        if not decision and not question and not state.stop_message:
            state.stop_message = "no unasked connected candidate nodes"

        state.turn_index += 1
        state.done = bool(decision or state.stop_message)
        return self._result(
            user_text=user_text,
            current_ids=self._dedupe_ids(current_ids),
            state=state,
            question=question,
            decision=decision,
            record=record,
        )

    def _handle_input_match(
        self,
        state: SessionState,
        matches: list[tuple[str, float]],
        user_text: str,
    ) -> list[str]:
        node_id, score = matches[0]
        self._set_fact(state, node_id, "candidate", "input_match", user_text)
        if state.current_node_id is None:
            state.current_node_id = node_id
            state.path = [node_id]
        query_tokens = tokenize_for_match(user_text)
        node = self.graph.nodes[node_id]
        exact_node_text = any(
            normalize_text(user_text) == normalize_text(field)
            for field in (node.id, node.label, node.description, node.source_text)
            if field
        )
        if not exact_node_text and len(query_tokens) <= 2:
            state.pending_question = PendingQuestion(
                node_id=node_id,
                question=self._question_for_node(node_id),
                reason="confirm_starting_node",
                context_node=state.current_node_id,
            )
            state.asked_edges.add((None, node_id))
        return [node_id]

    def _apply_feedback(
        self,
        state: SessionState,
        answer: str,
        user_text: str,
        explanation: str,
    ) -> list[str]:
        pending = state.pending_question
        assert pending is not None
        node_id = pending.node_id
        current_ids = [node_id]

        if answer == "no":
            self._set_fact(state, node_id, "no", "answer", user_text, explanation)
            if pending.reason.startswith("confirm_starting") or pending.reason.startswith("confirm_matched"):
                state.current_node_id = None
                state.path = []
            state.pending_question = None
            return current_ids

        self._set_fact(state, node_id, "yes", "answer", user_text, explanation)
        self._move_current_to(state, node_id)
        state.pending_question = None
        return current_ids

    def _next_question(self, state: SessionState) -> PendingQuestion | None:
        current_id = state.current_node_id
        if current_id is None:
            return None
        if self.graph.nodes[current_id].event_type in TERMINAL_EVENT_TYPES:
            return None

        for node_id in self.graph.neighbors(current_id):
            edge_key = (current_id, node_id)
            if edge_key in state.asked_edges:
                continue
            if self._status(state, node_id) in {"yes", "no"}:
                continue
            state.asked_edges.add(edge_key)
            return PendingQuestion(
                node_id=node_id,
                question=self._question_for_node(node_id),
                reason="connected_candidate",
                context_node=current_id,
            )
        return None

    def _move_current_to(self, state: SessionState, node_id: str) -> None:
        if node_id not in self.graph.nodes:
            return
        if state.current_node_id == node_id:
            return
        current = state.current_node_id
        if current is not None and node_id not in self.graph.neighbors(current):
            state.current_node_id = node_id
            state.path = [node_id]
            return
        state.current_node_id = node_id
        if not state.path:
            state.path = [node_id]
        elif state.path[-1] != node_id:
            state.path.append(node_id)

    def _decision_record(self, state: SessionState) -> tuple[str | None, dict[str, Any] | None]:
        current_id = state.current_node_id
        if not current_id:
            return None, None
        node = self.graph.nodes[current_id]
        if node.event_type not in TERMINAL_EVENT_TYPES:
            return None, None
        decision = self._decision_category(node)
        record = {
            "terminalNodes": [self._node_record(current_id)],
            "pathNodes": [self._node_record(node_id) for node_id in state.path if node_id in self.graph.nodes],
            "relatedActions": [],
        }
        return decision, record

    def _decision_category(self, node: Node) -> str:
        text = f"{node.id} {node.label}".lower()
        if "non-urgent" in text or "non urgent" in text or "nonurgent" in text:
            return "non-urgent"
        if "emergency" in text:
            return "emergency"
        if "priority" in text or "urgent" in text:
            return "priority"
        return node.label

    def _match_nodes(self, user_text: str) -> list[tuple[str, float]]:
        query = normalize_text(user_text)
        if not query:
            return []
        query_tokens = set(tokenize_for_match(query))
        normalized_query_id = normalize_identifier(query)
        scored: list[tuple[str, float]] = []

        for node in self.graph.nodes.values():
            fields = [node.id, node.label, node.description, node.source_text]
            field_text = normalize_text(" ".join(fields))
            field_tokens = set(tokenize_for_match(field_text))
            normalized_field_id = normalize_identifier(" ".join(fields))

            score = 0.0
            if normalized_query_id and normalized_query_id in normalized_field_id:
                score = max(score, 1.0)
            if query and query in field_text:
                score = max(score, 0.95)
            overlap = query_tokens & field_tokens
            if overlap and query_tokens:
                score = max(score, len(overlap) / len(query_tokens))
            if score > 0:
                scored.append((node.id, score))

        scored.sort(key=lambda item: (-item[1], self._node_order(item[0])))
        return scored

    def _node_order(self, node_id: str) -> int:
        for index, node in enumerate(self.graph.nodes.values()):
            if node.id == node_id:
                return index
        return len(self.graph.nodes)

    def _question_for_node(self, node_id: str) -> str:
        node = self.graph.nodes[node_id]
        label = node.label.rstrip(" ?")
        if node.event_type in TERMINAL_EVENT_TYPES:
            return f"Move to terminal node: {label}?"
        return f"{label}?"

    def _set_fact(
        self,
        state: SessionState,
        node_id: str,
        status: str,
        source: str,
        surface: str,
        explanation: str = "",
    ) -> None:
        if node_id not in self.graph.nodes:
            return
        state.facts[node_id] = Fact(node_id=node_id, status=status, source=source, surface=surface, explanation=explanation)

    @staticmethod
    def _status(state: SessionState, node_id: str) -> str | None:
        fact = state.facts.get(node_id)
        return fact.status if fact else None

    def _result(
        self,
        *,
        user_text: str,
        current_ids: list[str],
        state: SessionState,
        question: PendingQuestion | None,
        decision: str | None,
        record: dict[str, Any] | None,
    ) -> dict[str, Any]:
        result = {
            "input": user_text,
            "currentNodes": [self._current_node_record(node_id, state) for node_id in current_ids],
            "currentNode": self._node_record(state.current_node_id) if state.current_node_id else None,
            "pathNodes": [self._node_record(node_id) for node_id in state.path if node_id in self.graph.nodes],
            "candidateNodes": self._candidate_node_records(state),
            "upstreamNodes": self._neighbor_records(current_ids, "up"),
            "downstreamNodes": self._neighbor_records(current_ids, "down"),
            "questions": [self._question_record(question)] if question else [],
            "decision": decision,
            "terminal": bool(decision),
            "record": record,
            "message": state.stop_message,
        }
        result["visibleResponse"] = visible_response(result)
        return result

    def _candidate_node_records(self, state: SessionState) -> list[dict[str, Any]]:
        current_id = state.current_node_id
        if not current_id:
            return []
        records = []
        for node_id in self.graph.neighbors(current_id):
            record = self._node_record(node_id)
            record["status"] = self._status(state, node_id) or "candidate"
            record["asked"] = (current_id, node_id) in state.asked_edges
            records.append(record)
        return records

    def _current_node_record(self, node_id: str, state: SessionState) -> dict[str, Any]:
        record = self._node_record(node_id)
        fact = state.facts.get(node_id)
        record["status"] = fact.status if fact else "matched"
        if fact and fact.explanation:
            record["explanation"] = fact.explanation
        return record

    def _neighbor_records(self, node_ids: list[str], direction: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for node_id in node_ids:
            edges = self.graph.in_edges.get(node_id, []) if direction == "up" else self.graph.out_edges.get(node_id, [])
            for edge in edges:
                neighbor_id = edge.src if direction == "up" else edge.dst
                key = (node_id, neighbor_id)
                if key in seen:
                    continue
                seen.add(key)
                record = self._node_record(neighbor_id)
                record["currentNode"] = node_id
                record["relation"] = edge.relation_label
                records.append(record)
        return records

    def _node_record(self, node_id: str | None) -> dict[str, Any]:
        assert node_id is not None
        node = self.graph.nodes[node_id]
        return {"id": node.id, "label": node.label, "eventType": node.event_type}

    @staticmethod
    def _question_record(question: PendingQuestion) -> dict[str, Any]:
        return {
            "node": question.node_id,
            "question": question.question,
            "reason": question.reason,
            "contextNode": question.context_node,
        }

    def _dedupe_ids(self, node_ids: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for node_id in node_ids:
            if node_id not in self.graph.nodes or node_id in seen:
                continue
            seen.add(node_id)
            deduped.append(node_id)
        return deduped


def append_trace_log(path: Path, result: dict[str, Any]) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input": result["input"],
        "visibleResponse": result["visibleResponse"],
        "currentNode": result["currentNode"],
        "pathNodes": result["pathNodes"],
        "candidateNodes": result["candidateNodes"],
        "currentNodes": result["currentNodes"],
        "upstreamNodes": result["upstreamNodes"],
        "downstreamNodes": result["downstreamNodes"],
        "decision": result["decision"],
        "message": result["message"],
        "record": result["record"],
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def reset_trace_log(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an interactive generic graph walker.")
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH_PATH, help="Path to event_graph/graph.json.")
    parser.add_argument("--trace-log", type=Path, default=DEFAULT_TRACE_LOG, help="JSONL trace log path.")
    return parser


def run_interactive(args: argparse.Namespace) -> int:
    runtime = TriageIntentRuntime.from_graph_path(args.graph)
    state = runtime.new_session()
    reset_trace_log(args.trace_log)
    while True:
        print("user> ", end="", file=sys.stderr, flush=True)
        line = sys.stdin.readline()
        if not line:
            print("", file=sys.stderr)
            return 0
        user_text = line.strip()
        if not user_text:
            continue
        if user_text.lower() in {"exit", "quit"}:
            return 0
        result = runtime.process_turn(state, user_text)
        append_trace_log(args.trace_log, result)
        print(result["visibleResponse"])
        if state.done:
            state = runtime.new_session()


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return run_interactive(args)


if __name__ == "__main__":
    raise SystemExit(main())
