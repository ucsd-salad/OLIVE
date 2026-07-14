#!/usr/bin/env python3
"""Extract a human-readable semantic event graph from Lean source.

This extractor deliberately ignores Lean syntax nodes such as constructors,
fields, quantifiers, proof terms, and helper declarations. Its graph is meant
for human review:

- every node is a readable event, state, condition, action, decision, or outcome;
- every edge is a readable relationship between two events;
- relation labels are short natural-language phrases, not AST dependency names.

The extractor is domain-agnostic. It can use an optional PDF text as grounding
context, but the extraction schema is universal rather than tailored to a
specific textbook or medical domain.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from pypdf import PdfReader

try:
    import certifi
except ImportError:  # pragma: no cover
    certifi = None


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
DEFAULT_DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEFAULT_DEEPSEEK_MAX_TOKENS = 384_000


SEMANTIC_EVENT_PROMPT = """You are a robust semantic event graph extractor.

Your job is to convert source material into a human-readable event graph.
This is NOT a Lean AST graph and NOT a declaration dependency graph.

Node policy:
- Every node must be a real event/state/action/condition/decision/outcome that a human can project into a situation.
- Node labels must be short, readable phrases.
- Good labels: "patient has emergency signs", "start emergency treatment", "child waits in queue", "ask about neck trauma".
- Bad labels: "TriageCategory.priority", "ObservedSign.confidence", "List.any", "theorem example_1".
- Avoid tiny syntax fragments, constructors, fields, helper predicates, proofs, and implementation details.
- Prefer non-trivial event collections. Do not split every word into a node.

Edge policy:
- Edges connect events with a readable relation label.
- Good edge: "patient has emergency signs" --"requires"--> "start emergency treatment".
- Good edge: "person is sick" --"take"--> "amoxicillin", only if the source actually supports that relation.
- Edge labels should be short verb phrases such as "requires", "causes", "prevents", "enables", "indicates", "classifies as", "leads to", "blocks", "updates", "is evidence for", "is followed by".
- Use relationKind as a coarse reusable category, and relationLabel as the human-facing phrase.
- Do not invent domain-specific relation categories from the current document. The extractor must generalize across domains.

Grounding:
- The Lean source is the primary representation to extract from.
- Optional PDF/context text can help recover the intended human meaning of generated Lean names.
- Do not add facts that are only plausible but not present in the Lean source or context.
- The user payload may include leanSemanticHints. These hints are mechanically
  derived from Lean declarations and may be noisy, but they are important
  coverage cues. Use them to avoid missing dependencies that are hidden by
  coding style.

Lean style normalization:
- Treat Bool-returning defs, Prop-returning defs, predicates, inductive
  constructors, enum-like results, list-building functions, if/else branches,
  match branches, and theorem implications as different surface forms of the
  same semantic dependency graph.
- Expand helper predicates recursively when they feed a higher-level decision.
  For example, if primitive observations define a helper condition, and that
  helper condition triggers a category/action, include both primitive ->
  helper and helper -> category/action edges.
- For disjunctions, conjunctions, boolean operators, and list concatenation,
  recover the individual event dependencies when they support a meaningful
  human event.
- If a branch returns or includes a constructor/value/action, connect the
  branch condition to the returned/included event. If a top-level decision is
  expressed only as a constructor such as Category.foo, convert it into a
  human decision node such as "assign category: foo".
- Theorems and lemmas are evidence for dependencies, not proof-term nodes.
  Extract the human implication they state when it connects real events.

Coverage checklist:
- Include primitive observed conditions that influence triage/classification.
- Include composite conditions/predicates that aggregate those observations.
- Include category decisions, required actions, follow-up actions, and queue or
  treatment outcomes when present.
- Include edges from primitive observations to composites, composites to
  decisions/actions, and decision branches to outcomes.

Confidence:
- confidence is P(the node/edge accurately represents a source-supported human event or relation).
- Use 0.0 to 1.0.

Return JSON only:
{
  "nodes": [
    {
      "id": "short_snake_case_id",
      "label": "human readable event",
      "eventType": "condition|state|action|decision|outcome|rule|entity|evidence",
      "description": "one sentence",
      "sourceText": "short exact or near-exact source snippet",
      "confidence": 0.0,
      "confidenceReason": "brief grounding reason"
    }
  ],
  "edges": [
    {
      "src": "source node id",
      "dst": "target node id",
      "relationKind": "requires|causes|enables|prevents|indicates|classifies_as|leads_to|blocks|updates|includes|contrasts|evidence_for|refines|follows|other",
      "relationLabel": "human-facing verb phrase",
      "description": "one sentence",
      "sourceText": "short exact or near-exact source snippet",
      "confidence": 0.0,
      "confidenceReason": "brief grounding reason"
    }
  ]
}

Hard output contract:
- The assistant message.content MUST contain the JSON object above.
- Never leave message.content empty.
- Do not put the JSON in reasoning_content, tool calls, markdown, comments, or prose.
- The first non-whitespace character of message.content must be {.
- The last non-whitespace character of message.content must be }.
- The top-level JSON object must contain "nodes" and "edges" arrays.
"""


STRICT_JSON_RETRY_PROMPT = """The previous response was unusable because message.content was empty or not valid JSON.

Retry the entire extraction from the same source material.
Return only the final JSON object in message.content.
Do not explain, do not use markdown fences, and do not return an empty string.
The response must start with { and end with }.
"""


class DeepSeekContentError(RuntimeError):
    """Raised when the API response arrived but assistant content is unusable."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract a human-readable semantic event graph from Lean.")
    parser.add_argument("lean_file", type=Path, help="Path to the generated .lean file.")
    parser.add_argument("--module", help="Graph module name. Defaults to the Lean file stem.")
    parser.add_argument("--out-dir", type=Path, default=Path("event_graph_out"))
    parser.add_argument("--pdf", type=Path, help="Optional source PDF for semantic grounding.")
    parser.add_argument("--pdf-max-chars", type=int, default=0, help="Maximum PDF context chars; <=0 disables truncation.")
    parser.add_argument("--lean-max-chars", type=int, default=0, help="Maximum Lean source chars; <=0 disables truncation.")
    parser.add_argument("--deepseek-model", default=DEFAULT_DEEPSEEK_MODEL)
    parser.add_argument("--deepseek-base-url", default=DEFAULT_DEEPSEEK_BASE_URL)
    parser.add_argument("--deepseek-api-key-env", default=DEFAULT_DEEPSEEK_API_KEY_ENV)
    parser.add_argument("--deepseek-timeout", type=int, default=900)
    parser.add_argument("--deepseek-max-retries", type=int, default=4)
    parser.add_argument("--deepseek-content-retries", type=int, default=3)
    parser.add_argument("--deepseek-max-tokens", type=int, default=DEFAULT_DEEPSEEK_MAX_TOKENS)
    parser.add_argument("--deepseek-ca-file", type=Path)
    parser.add_argument(
        "--no-confidence",
        action="store_true",
        help="Extract nodes/edges without writing LLM confidence fields.",
    )

    return parser.parse_args()


def normalize_space(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def truncate_text(text: str, max_chars: int | None, label: str) -> str:
    if max_chars is None or max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n[TRUNCATED {label}: {len(text) - max_chars} chars omitted]"


def read_pdf_text(pdf_path: Path | None, max_chars: int | None) -> str:
    if not pdf_path:
        return ""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    reader = PdfReader(str(pdf_path))
    chunks: list[str] = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        chunks.append(f"\n\n[PDF page {page_index}]\n{text.strip()}")
    return truncate_text("\n".join(chunks).strip(), max_chars, str(pdf_path))


TOP_LEVEL_BOUNDARY_RE = re.compile(
    r"(?m)^[ \t]*(?:(?:private|protected|noncomputable|partial)\s+)*"
    r"(?P<keyword>inductive|structure|def|abbrev|theorem|lemma|instance|namespace|end)\b"
    r"(?:\s+(?P<name>[A-Za-z_][A-Za-z0-9_'.?]*))?"
)


def strip_lean_comments(source: str) -> str:
    without_block_comments = re.sub(r"/-.*?-/", "", source, flags=re.DOTALL)
    return re.sub(r"--.*", "", without_block_comments)


def line_number_at(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def unique_preserve_order(values: list[str], limit: int = 40) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = normalize_space(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def extract_constructor_refs(text: str, limit: int = 40) -> list[str]:
    refs = re.findall(r"\b[A-Z][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)+\b", text)
    return unique_preserve_order(refs, limit)


def extract_field_refs(text: str, limit: int = 40) -> list[str]:
    refs = re.findall(r"\b[a-z][A-Za-z0-9_']*\.[A-Za-z_][A-Za-z0-9_']*\b", text)
    return unique_preserve_order(refs, limit)


def split_condition_clauses(condition: str, limit: int = 24) -> list[str]:
    cleaned = normalize_space(condition)
    cleaned = cleaned.replace("(", " ").replace(")", " ")
    pieces = re.split(r"\s*(?:\|\||&&|∨|∧|,|;)\s*", cleaned)
    return unique_preserve_order([piece.strip() for piece in pieces], limit)


def extract_top_level_declarations(source: str) -> list[dict[str, Any]]:
    clean_source = strip_lean_comments(source)
    matches = list(TOP_LEVEL_BOUNDARY_RE.finditer(clean_source))
    declarations: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        keyword = match.group("keyword")
        name = match.group("name")
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(clean_source)
        if keyword not in {"inductive", "structure", "def", "abbrev", "theorem", "lemma"} or not name:
            continue
        text = clean_source[start:end].strip()
        if not text:
            continue
        declarations.append(
            {
                "keyword": keyword,
                "name": name,
                "startLine": line_number_at(clean_source, start),
                "endLine": line_number_at(clean_source, end),
                "text": text,
            }
        )
    return declarations


def extract_inductive_constructors(decl_text: str) -> list[str]:
    constructors = re.findall(r"\|\s*([A-Za-z_][A-Za-z0-9_']*)\b", decl_text)
    return unique_preserve_order(constructors)


def extract_structure_fields(decl_text: str) -> list[str]:
    fields: list[str] = []
    for line in decl_text.splitlines()[1:]:
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_']*)\s*:", line)
        if match:
            fields.append(match.group(1))
    return unique_preserve_order(fields, limit=80)


def extract_called_declarations(text: str, known_names: set[str], current_name: str, limit: int = 40) -> list[str]:
    calls: list[str] = []
    for name in sorted(known_names, key=len, reverse=True):
        if name == current_name:
            continue
        if re.search(rf"\b{re.escape(name)}\b", text):
            calls.append(name)
    return unique_preserve_order(calls, limit)


def extract_branch_hints(text: str, limit: int = 24) -> list[dict[str, Any]]:
    normalized = normalize_space(text)
    branch_hints: list[dict[str, Any]] = []
    pattern = re.compile(r"\bif\s+(.+?)\s+then\s+(.+?)(?=\s+else\b|$)")
    for match in pattern.finditer(normalized):
        condition = normalize_space(match.group(1))
        then_value = normalize_space(match.group(2))
        if not condition or not then_value:
            continue
        branch_hints.append(
            {
                "condition": condition[:300],
                "conditionClauses": split_condition_clauses(condition),
                "then": then_value[:300],
                "thenConstructors": extract_constructor_refs(then_value),
                "thenFieldRefs": extract_field_refs(then_value),
            }
        )
        if len(branch_hints) >= limit:
            break
    return branch_hints


def extract_condition_to_list_hints(text: str, limit: int = 32) -> list[dict[str, Any]]:
    normalized = normalize_space(text)
    hints: list[dict[str, Any]] = []
    pattern = re.compile(r"\bif\s+(.+?)\s+then\s+\[([^\]]+)\]")
    for match in pattern.finditer(normalized):
        condition = normalize_space(match.group(1))
        list_value = normalize_space(match.group(2))
        constructors = extract_constructor_refs(list_value)
        if not condition or not constructors:
            continue
        hints.append(
            {
                "condition": condition[:300],
                "conditionClauses": split_condition_clauses(condition),
                "includedConstructors": constructors,
            }
        )
        if len(hints) >= limit:
            break
    return hints


def build_lean_semantic_hints(source: str, max_chars: int = 64_000) -> dict[str, Any]:
    declarations = extract_top_level_declarations(source)
    known_def_names = {
        decl["name"]
        for decl in declarations
        if decl["keyword"] in {"def", "abbrev", "theorem", "lemma"}
    }

    declaration_hints: list[dict[str, Any]] = []
    for decl in declarations:
        text = decl["text"]
        keyword = decl["keyword"]
        item: dict[str, Any] = {
            "kind": keyword,
            "name": decl["name"],
            "lines": [decl["startLine"], decl["endLine"]],
            "sourcePreview": normalize_space(text[:360]),
        }
        if keyword == "inductive":
            constructors = extract_inductive_constructors(text)
            if constructors:
                item["constructors"] = constructors
        elif keyword == "structure":
            fields = extract_structure_fields(text)
            if fields:
                item["fields"] = fields
        else:
            field_refs = extract_field_refs(text)
            constructor_refs = extract_constructor_refs(text)
            calls = extract_called_declarations(text, known_def_names, decl["name"])
            branches = extract_branch_hints(text)
            list_hints = extract_condition_to_list_hints(text)
            clauses = split_condition_clauses(text, limit=40)
            if field_refs:
                item["fieldRefs"] = field_refs
            if constructor_refs:
                item["constructorRefs"] = constructor_refs
            if calls:
                item["usesDeclarations"] = calls
            if branches:
                item["branchDependencies"] = branches
            if list_hints:
                item["conditionToListDependencies"] = list_hints
            if clauses:
                item["possibleConditionClauses"] = clauses

        if len(item) > 4:
            declaration_hints.append(item)

    hints = {
        "purpose": (
            "Mechanically extracted Lean coverage hints. Use as a checklist for "
            "events and dependency edges; ignore noise and keep final graph human-readable."
        ),
        "styleCoverage": [
            "inductive constructors that represent categories, signs, actions, or outcomes",
            "structure Bool/enum fields that represent primitive observations",
            "Prop/Bool helper predicates that represent composite conditions",
            "if/then/list branches that connect conditions to returned categories or actions",
            "theorems/lemmas that state human implications",
        ],
        "declarations": declaration_hints,
    }
    encoded = json.dumps(hints, ensure_ascii=False, indent=2)
    if len(encoded) > max_chars:
        hints["truncated"] = True
        for item in hints["declarations"]:
            if "sourcePreview" in item:
                item["sourcePreview"] = item["sourcePreview"][:180]
            if "possibleConditionClauses" in item:
                item["possibleConditionClauses"] = item["possibleConditionClauses"][:12]
            if "branchDependencies" in item:
                item["branchDependencies"] = item["branchDependencies"][:12]
            if "conditionToListDependencies" in item:
                item["conditionToListDependencies"] = item["conditionToListDependencies"][:16]
        encoded = json.dumps(hints, ensure_ascii=False, indent=2)
        while len(encoded) > max_chars and len(hints["declarations"]) > 1:
            hints["declarations"].pop()
            encoded = json.dumps(hints, ensure_ascii=False, indent=2)
    return hints


def ssl_context(ca_file: Path | None) -> ssl.SSLContext:
    if ca_file:
        return ssl.create_default_context(cafile=str(ca_file))
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def deepseek_chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout_seconds: int,
    max_retries: int,
    max_tokens: int,
    context: ssl.SSLContext,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "stream": False,
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code < 500 or attempt == max_retries:
                raise RuntimeError(f"DeepSeek API error {exc.code}: {detail}") from exc
            last_error = exc
        except (urllib.error.URLError, http.client.IncompleteRead, json.JSONDecodeError) as exc:
            if attempt == max_retries:
                raise RuntimeError(f"DeepSeek API read/network error after retries: {exc}") from exc
            last_error = exc
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"DeepSeek API call failed after retries: {last_error}")


def deepseek_response_summary(response: dict[str, Any]) -> str:
    try:
        choice = response["choices"][0]
        message = choice.get("message") or {}
        summary = {
            "finish_reason": choice.get("finish_reason"),
            "message_keys": sorted(message.keys()),
            "content_length": len(str(message.get("content") or "")),
            "usage": response.get("usage"),
        }
    except (KeyError, IndexError, TypeError, AttributeError):
        summary = {"shape": type(response).__name__, "keys": sorted(response.keys()) if isinstance(response, dict) else []}
    return json.dumps(summary, ensure_ascii=False, sort_keys=True)


def strip_markdown_fences(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def extract_first_json_object(content: str) -> str | None:
    start = content.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start:index + 1]
    return None


def parse_json_content(content: str) -> dict[str, Any]:
    cleaned = strip_markdown_fences(content)
    if not cleaned:
        raise DeepSeekContentError("DeepSeek returned empty message.content.")
    candidates = [cleaned]
    embedded = extract_first_json_object(cleaned)
    if embedded and embedded != cleaned:
        candidates.append(embedded)
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(parsed, dict):
            raise DeepSeekContentError("DeepSeek content JSON must be a top-level object.")
        return parsed
    preview = cleaned[:1200]
    raise DeepSeekContentError(f"DeepSeek did not return valid graph JSON: {preview}") from last_error


def normalize_raw_graph_shape(parsed: dict[str, Any]) -> dict[str, Any]:
    candidate = parsed
    if "graph" in parsed and isinstance(parsed["graph"], dict):
        candidate = parsed["graph"]
    if not isinstance(candidate.get("nodes"), list) or not isinstance(candidate.get("edges"), list):
        keys = sorted(candidate.keys())
        raise DeepSeekContentError(
            f'DeepSeek graph JSON must contain top-level "nodes" and "edges" arrays; got keys={keys}'
        )
    return candidate


def parse_deepseek_content(response: dict[str, Any]) -> dict[str, Any]:
    try:
        message = response["choices"][0]["message"]
        raw_content = message.get("content") if isinstance(message, dict) else None
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise RuntimeError(f"Unexpected DeepSeek response shape: {response}") from exc
    content = raw_content if isinstance(raw_content, str) else str(raw_content or "")
    content = content.strip()
    if not content:
        raise DeepSeekContentError(f"DeepSeek returned empty message.content. {deepseek_response_summary(response)}")
    return normalize_raw_graph_shape(parse_json_content(content))


def make_messages(
    module: str,
    lean_source: str,
    pdf_text: str,
    retry_reason: str | None = None,
    no_confidence: bool = False,
) -> list[dict[str, str]]:
    payload = {
        "module": module,
        "task": "Extract a semantic event graph. Nodes must be human-readable events only.",
        "leanSource": lean_source,
        "leanSemanticHints": build_lean_semantic_hints(lean_source),
        "optionalSourceContext": pdf_text or None,
    }
    if retry_reason:
        payload["previousFailure"] = retry_reason
    prompt = SEMANTIC_EVENT_PROMPT
    if no_confidence:
        prompt += (
            "\n\nNo-confidence mode:\n"
            "- This overrides the generic schema above for confidence fields.\n"
            "- Do not estimate probability/confidence.\n"
            "- Omit confidence and confidenceReason fields from every node and edge.\n"
            "- Focus only on the current nodes and edges.\n"
        )
    if retry_reason:
        prompt += "\n\n" + STRICT_JSON_RETRY_PROMPT
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def request_semantic_graph(
    *,
    base_url: str,
    api_key: str,
    model: str,
    module: str,
    lean_source: str,
    pdf_text: str,
    timeout_seconds: int,
    network_retries: int,
    content_retries: int,
    max_tokens: int,
    context: ssl.SSLContext,
    no_confidence: bool,
) -> dict[str, Any]:
    retry_reason: str | None = None
    attempts = max(0, content_retries) + 1
    for attempt in range(1, attempts + 1):
        response = deepseek_chat_completion(
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=make_messages(module, lean_source, pdf_text, retry_reason, no_confidence),
            timeout_seconds=timeout_seconds,
            max_retries=network_retries,
            max_tokens=max_tokens,
            context=context,
        )
        try:
            parsed = parse_deepseek_content(response)
        except DeepSeekContentError as exc:
            retry_reason = str(exc)
            if attempt >= attempts:
                raise
            print(
                f"DeepSeek returned empty/invalid content; retrying full semantic extraction "
                f"({attempt}/{attempts - 1}). Reason: {retry_reason[:500]}",
                file=sys.stderr,
            )
            continue
        return parsed
    raise DeepSeekContentError("DeepSeek content retry loop ended without a usable graph.")


def slugify(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    if not slug:
        slug = fallback
    if slug[0].isdigit():
        slug = f"event_{slug}"
    return slug[:72]


def stable_edge_id(src: str, dst: str, label: str) -> str:
    digest = hashlib.sha1(f"{src}|{dst}|{label}".encode("utf-8")).hexdigest()[:12]
    return f"edge:{digest}"


def clamp_confidence(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return default


def sanitize_event_type(value: Any) -> str:
    event_type = normalize_space(value).lower().replace("-", "_")
    allowed = {"condition", "state", "action", "decision", "outcome", "rule", "entity", "evidence"}
    return event_type if event_type in allowed else "state"


def sanitize_relation_kind(value: Any) -> str:
    relation = normalize_space(value).lower().replace("-", "_").replace(" ", "_")
    allowed = {
        "requires",
        "causes",
        "enables",
        "prevents",
        "indicates",
        "classifies_as",
        "leads_to",
        "blocks",
        "updates",
        "includes",
        "contrasts",
        "evidence_for",
        "refines",
        "follows",
        "other",
    }
    return relation if relation in allowed else "other"


def sanitize_graph(
    raw: dict[str, Any],
    module: str,
    source_file: Path,
    no_confidence: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    raw_nodes = raw.get("nodes")
    raw_edges = raw.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise RuntimeError("DeepSeek graph JSON must contain nodes and edges lists.")

    nodes: list[dict[str, Any]] = []
    id_map: dict[str, str] = {}
    used_ids: set[str] = set()
    for index, item in enumerate(raw_nodes, start=1):
        if not isinstance(item, dict):
            continue
        label = normalize_space(item.get("label"))
        if not label:
            continue
        raw_id = normalize_space(item.get("id")) or label
        node_id = slugify(raw_id, f"event_{index:03d}")
        if node_id in used_ids:
            node_id = f"{node_id}_{index:03d}"
        used_ids.add(node_id)
        id_map[raw_id] = node_id
        id_map[normalize_space(item.get("id"))] = node_id
        id_map[label] = node_id
        node = {
            "id": node_id,
            "nodeKind": "event",
            "eventType": sanitize_event_type(item.get("eventType")),
            "label": label,
            "description": normalize_space(item.get("description")),
            "sourceText": normalize_space(item.get("sourceText")),
            "sourceFile": str(source_file),
            "module": module,
            "probabilityTarget": True,
            "displayByDefault": True,
        }
        if not no_confidence:
            node["confidence"] = clamp_confidence(item.get("confidence"), 0.0)
            node["confidenceReason"] = normalize_space(item.get("confidenceReason"))
        nodes.append(node)
        events.append({"event": "semantic_event_node_recorded", "nodeId": node_id, "label": label})

    node_ids = {node["id"] for node in nodes}
    edges: list[dict[str, Any]] = []
    used_edge_ids: set[str] = set()
    for index, item in enumerate(raw_edges, start=1):
        if not isinstance(item, dict):
            continue
        raw_src = normalize_space(item.get("src"))
        raw_dst = normalize_space(item.get("dst"))
        src = id_map.get(raw_src, raw_src)
        dst = id_map.get(raw_dst, raw_dst)
        if src not in node_ids or dst not in node_ids or src == dst:
            events.append({
                "event": "semantic_relation_skipped",
                "reason": "unknown_or_self_endpoint",
                "src": raw_src,
                "dst": raw_dst,
            })
            continue
        relation_kind = sanitize_relation_kind(item.get("relationKind"))
        relation_label = normalize_space(item.get("relationLabel")) or relation_kind.replace("_", " ")
        edge_id = stable_edge_id(src, dst, relation_label)
        if edge_id in used_edge_ids:
            edge_id = f"{edge_id}_{index:03d}"
        used_edge_ids.add(edge_id)
        edge = {
            "id": edge_id,
            "src": src,
            "dst": dst,
            "edgeKind": relation_kind,
            "relationKind": relation_kind,
            "relationLabel": relation_label,
            "label": relation_label,
            "description": normalize_space(item.get("description")),
            "sourceText": normalize_space(item.get("sourceText")),
            "sourceFile": str(source_file),
            "module": module,
            "layer": "semantic",
            "probabilityTarget": True,
            "displayByDefault": True,
        }
        if not no_confidence:
            edge["confidence"] = clamp_confidence(item.get("confidence"), 0.0)
            edge["confidenceReason"] = normalize_space(item.get("confidenceReason"))
        edges.append(edge)
        events.append({
            "event": "semantic_event_edge_recorded",
            "edgeId": edge_id,
            "src": src,
            "dst": dst,
            "relationLabel": relation_label,
        })

    return nodes, edges, events


def write_outputs(
    *,
    out_dir: Path,
    module: str,
    source_file: Path,
    pdf_file: Path | None,
    model: str,
    no_confidence: bool,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    graph = {
        "metadata": {
            "extractorMode": "semantic_event_graph",
            "module": module,
            "sourceFile": str(source_file),
            "pdfFile": str(pdf_file) if pdf_file else None,
            "model": model,
            "confidenceMode": "external_or_preserved" if no_confidence else "llm_estimated",
            "nodePolicy": "nodes are human-readable events, states, actions, conditions, decisions, or outcomes",
            "edgePolicy": "edges are human-readable relations between events",
            "domainPolicy": "domain-agnostic extraction; no document-specific relation schema is hardcoded",
        },
        "nodes": nodes,
        "edges": edges,
        "events": events,
    }
    graph_path = out_dir / "graph.json"
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Graph extracted: nodes={len(nodes)}, edges={len(edges)}.")


def main() -> None:
    args = parse_args()
    source_file = args.lean_file.resolve()
    if not source_file.exists():
        raise SystemExit(f"Lean file not found: {source_file}")
    api_key = os.environ.get(args.deepseek_api_key_env)
    if not api_key:
        raise SystemExit(f"Set {args.deepseek_api_key_env} before running semantic extraction.")

    module = args.module or source_file.stem
    lean_source = truncate_text(source_file.read_text(encoding="utf-8"), args.lean_max_chars, str(source_file))
    pdf_file = args.pdf.resolve() if args.pdf else None
    pdf_text = read_pdf_text(pdf_file, args.pdf_max_chars)
    context = ssl_context(args.deepseek_ca_file.resolve() if args.deepseek_ca_file else None)

    raw_graph = request_semantic_graph(
        base_url=args.deepseek_base_url,
        api_key=api_key,
        model=args.deepseek_model,
        module=module,
        lean_source=lean_source,
        pdf_text=pdf_text,
        timeout_seconds=args.deepseek_timeout,
        network_retries=args.deepseek_max_retries,
        content_retries=args.deepseek_content_retries,
        max_tokens=args.deepseek_max_tokens,
        context=context,
        no_confidence=args.no_confidence,
    )
    nodes, edges, events = sanitize_graph(raw_graph, module, source_file, no_confidence=args.no_confidence)
    write_outputs(
        out_dir=args.out_dir,
        module=module,
        source_file=source_file,
        pdf_file=pdf_file,
        model=args.deepseek_model,
        no_confidence=args.no_confidence,
        nodes=nodes,
        edges=edges,
        events=events,
    )


if __name__ == "__main__":
    main()
