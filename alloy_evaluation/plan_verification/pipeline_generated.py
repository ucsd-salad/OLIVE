"""
Alloy + LLM Verification Full Pipeline

Main line, per user query:
1. Formalize the query with the auto-formalization roundtrip (../pipeline.py):
   x -> y_original -> x' -> y_prime, accepted only when Alloy proves
   y_original <-> y_prime. The verified y_original (`pred rule[c: Ctx]` over a
   fixed query vocabulary) is the FORMAL QUERY. If the roundtrip does not verify,
   the run stops: an unverified translation is not used.
2. The LLM receives the natural-language query AND the formal query -- two
   versions of the same situation -- and writes the response plan as
   `pred GeneratedPlan`.
3. Alloy checks the plan against the safety protocol (below).

What is NOT checked mechanically: that GeneratedPlan agrees with the formal
query. The query vocabulary (`Ctx`) and the protocol's signatures are different
models, so the formal query reaches the plan only through the prompt.

- The LLM ONLY generates/repairs the 'GeneratedPlan' predicate
- compare.als is NEVER structurally modified
- Alloy is used as a safety measure, by counterexample search. The protocol's
  safety rules are one predicate, `Protocol`; only structural well-formedness
  constraints are facts. The verifier file runs, in order:

    run CounterExample { GeneratedPlan and not Protocol }
    run PlanPossible   { GeneratedPlan }

  CounterExample: Instance found    => a world that follows the plan and breaks
                                       the protocol exists => UNSAFE; the
                                       instance and the broken rules go back to
                                       the LLM
  PlanPossible:   No instance found => the plan contradicts itself or the
                                       structure of the model, so "no
                                       counterexample" would be vacuous
                                       => IMPOSSIBLE_PLAN
  otherwise                         => SAFE: every world that follows the plan
                                       satisfies the protocol
"""
import hashlib
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(BASE) not in sys.path:
    sys.path.insert(0, os.path.dirname(BASE))
import alloy as alloy_tool  # ../alloy.py
import protocol_modules as pm

JAVA_DIR = os.path.join(BASE, "AlloyCommandline")
# One Alloy for both pipelines: the roundtrip (../alloy.py) and this verifier use
# the same jar, found the same way ($ALLOY_JAR, else the Alloy.app bundle, 6.2).
JAR = alloy_tool.jar()
JAVA_FILE = os.path.join(JAVA_DIR, "AlloyCommandline.java")
CLASS_FILE = os.path.join(JAVA_DIR, "AlloyCommandline.class")

# TRUTH_PATH is the hand-written ground truth: safety_protocol.als, the faithful
# formalization of Swimming.txt.
#
# COMPARE_PATH is the verifier file built FROM it. It copies no protocol text: it
# opens safety_protocol_core.als, which protocol_modules.build_core cuts from the
# protocol at its standalone section (so `fact ProtocolHolds` never reaches a
# verifier) and writes beside it, then declares an empty `pred GeneratedPlan`
# slot and the two commands described above. build_compare_file() regenerates
# both, so running this module needs nothing but safety_protocol.als on disk.
#
# Both absolute, so the pipeline works from any working directory.
TRUTH_PATH = os.path.join(BASE, "safety_protocol.als")
COMPARE_PATH = os.path.join(BASE, "swimming_compare.als")

ALLOY_SCOPE_DEFAULT = "for 5 but 9 Int"

# .als files in BASE that are NOT protocols: generated verifier artifacts and
# dead stubs. Anything containing a `pred GeneratedPlan` slot, or the
# protocol_modules GENERATED marker (a core or an extension), is also skipped,
# since that marks a file this pipeline built rather than a ground-truth model.
PROTOCOL_EXCLUDE = {"swimming_compare.als", "compare.als"}

def _load_env_file_if_present(path=".env"):
    """Small .env fallback so python-dotenv is optional."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    _load_env_file_if_present(os.path.join(BASE, ".env"))


LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek").lower()
DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "30000"))

DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_THINKING = os.getenv("DEEPSEEK_THINKING", "enabled")
DEEPSEEK_REASONING_EFFORT = os.getenv("DEEPSEEK_REASONING_EFFORT", "low")

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-6")

_deepseek_client = None
_anthropic_client = None


def _get_deepseek_client():
    global _deepseek_client
    if _deepseek_client is None:
        from openai import OpenAI
        _deepseek_client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=DEEPSEEK_BASE_URL,
        )
    return _deepseek_client


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import Anthropic
        _anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _anthropic_client


def _call_deepseek(prompt, max_new_tokens, temperature):
    client = _get_deepseek_client()
    kwargs = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_new_tokens,
        "stream": False,
    }
    if DEEPSEEK_MODEL.startswith("deepseek-v4"):
        thinking_on = DEEPSEEK_THINKING.lower() == "enabled"
        kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if thinking_on else "disabled"}
        }
        if thinking_on:
            kwargs["reasoning_effort"] = DEEPSEEK_REASONING_EFFORT
        else:
            kwargs["temperature"] = temperature
    else:
        kwargs["temperature"] = temperature

    try:
        response = client.chat.completions.create(**kwargs)
    except TypeError:
        # Older openai SDKs may not accept `reasoning_effort`; keep the call
        # usable while preflight nudges users to upgrade.
        kwargs.pop("reasoning_effort", None)
        response = client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    if not (choice.message.content or "").strip():
        # with thinking on, a reply can spend the whole token budget reasoning
        # and come back with no answer (finish_reason "length")
        print("      [LLM] empty answer (finish_reason=%s, usage=%s)"
              % (choice.finish_reason, getattr(response, "usage", None)), flush=True)
    return choice.message.content


def _call_claude_api(prompt, max_new_tokens, temperature):
    client = _get_anthropic_client()
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_new_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# Provider-neutral LLM call. Name kept for existing call sites.
def call_claude(prompt, max_new_tokens=DEFAULT_MAX_TOKENS, temperature=0.7):
    if LLM_PROVIDER == "deepseek":
        text = _call_deepseek(prompt, max_new_tokens, temperature)
    elif LLM_PROVIDER == "claude":
        text = _call_claude_api(prompt, max_new_tokens, temperature)
    else:
        raise ValueError("Unknown LLM_PROVIDER='%s' (expected deepseek or claude)" % LLM_PROVIDER)

    with open("ai_log.txt", "a", encoding="utf-8") as f:
        f.write("[provider=%s model=%s]\n%s\n\n%s\n\n" % (
            LLM_PROVIDER,
            DEEPSEEK_MODEL if LLM_PROVIDER == "deepseek" else CLAUDE_MODEL,
            text,
            "=" * 60,
        ))

    return text

# extractig the generated plan from the Alloy compare file 

def extract_generated_plan(code):
    match = re.search(r"pred\s+GeneratedPlan\s*\{", code, re.DOTALL)
    if not match:
        return None
    start = match.start()
    i = match.end() - 1
    depth = 0
    while i < len(code):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return code[start:i + 1]
        i += 1
    return None

# replacing the generated plan from the Alloy compare file with the new plan generated by the LLM
def replace_generated_plan(original_code, new_plan):
    old_plan = extract_generated_plan(original_code)
    if not old_plan:
        return original_code
    return original_code.replace(old_plan, new_plan.strip(), 1)

# Save the argument content to a file at the specified path and return the path.
def save_file(content, path):
    with open(path, "w") as f:
        f.write(content)
    return path


# ---------------- Protocol discovery ----------------
#
# There is more than one safety protocol on disk (aquatic facility, CPR, ...).
# They cannot be merged into a single model -- safety_protocol.als and
# CPR_new.als both declare `Person` and `Bool`, so concatenating them will not
# compile. One protocol is therefore selected per verification run, and the
# semantic layer below is what picks it.

def _extract_protocol_title(content, fallback):
    """Human-readable title from the file's header comment."""
    block = re.match(r"\s*/\*(.*?)\*/", content, re.S)
    if block:
        for line in block.group(1).splitlines():
            s = line.strip().lstrip("*").strip()
            if s and not set(s) <= set("=-* "):
                return s

    for line in content.splitlines()[:10]:
        s = line.strip()
        if s.startswith("//"):
            s = s.lstrip("/").strip()
            # `// Time` sitting above `sig Time {` is a section label, not a
            # title; reject anything that just names a signature.
            if len(s) > 12 and not re.match(r"^\w+$", s):
                return s
    return fallback


def _extract_protocol_sigs(content):
    """Top-level signature names -- the domain fingerprint the LLM reasons over.

    Every name of a multi-name declaration counts (`one sig Safe, Unsafe extends
    Environment` declares both): the list is what the LLM is told it may use."""
    names = []
    for group in re.findall(
            r"^(?:abstract\s+|one\s+|lone\s+|some\s+|private\s+)*sig\s+([\w\s,]+?)\s*(?:\bextends\b|\bin\b|\{)",
            content, re.M):
        names.extend(name.strip() for name in group.split(",") if name.strip())
    return names


def _extract_protocol_scope(content, default=ALLOY_SCOPE_DEFAULT):
    """Reuse the protocol's own scope, so GeneratedPlan is checked at the size
    its author already validated the model at: the scope of the commands in its
    standalone section."""
    try:
        tail = pm.split_protocol(content)[1]
    except pm.ProtocolError:
        tail = content          # build_core will refuse this protocol with the reason
    scopes = re.findall(r"\bfor\s+\d+(?:\s+but\s+[^\n{}]+)?", tail)
    if not scopes:
        return default
    return max((s.strip().rstrip(",") for s in scopes), key=len)


def load_protocol(path):
    """Read one .als protocol into the descriptor the semantic layer uses."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    name = os.path.splitext(os.path.basename(path))[0]
    return {
        "name": name,
        "path": path,
        "file": os.path.basename(path),
        "title": _extract_protocol_title(content, name.replace("_", " ")),
        "sigs": _extract_protocol_sigs(content),
        "scope": _extract_protocol_scope(content),
        "lines": content.count("\n") + 1,
    }


def discover_protocols(directory=BASE):
    """Every ground-truth protocol model in `directory`.

    Skips this pipeline's own generated verifier files (anything holding a
    `pred GeneratedPlan` slot) and the known dead stubs, so dropping a new
    protocol .als into the directory is enough to make it selectable.
    """
    protocols = []
    for entry in sorted(os.listdir(directory)):
        if not entry.endswith(".als") or entry in PROTOCOL_EXCLUDE:
            continue
        path = os.path.join(directory, entry)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        if "pred GeneratedPlan" in content or pm.GENERATED in content:
            continue          # a verifier file, core or extension we built, not a source protocol
        if not _extract_protocol_sigs(content):
            continue          # no signatures: not a model
        protocols.append(load_protocol(path))
    return protocols


def compare_path_for(protocol):
    """Where the verifier file for this protocol gets written."""
    return os.path.join(BASE, "%s_compare.als" % protocol["name"])


# ---------------- Wiring: <protocol>.als -> <protocol>_compare.als ----------------

def build_compare_file(protocol=None, scope=None, truth_path=None, out_path=None,
                       extension_lines=None):
    """Build the verifier file from a ground-truth protocol.

    Writes, all in the verifier file's directory (Alloy resolves `open` there):
      <protocol>_core.als   protocol_modules.build_core: the protocol cut at its
                            standalone section and checked (no fact states the
                            rules, no command, no local open)
      <stem>_ext.als        only with extension_lines: new query words, built by
                            protocol_modules.build_extension from checked lines;
                            it opens the core, never the other way round
      <stem>.als            opens those modules, declares an empty
                            `pred GeneratedPlan` slot and the two commands

    Called with no protocol: safety_protocol.als -> swimming_compare.als at the
    default scope.
    """
    if protocol is not None:
        truth_path = truth_path or protocol["path"]
        scope = scope or protocol["scope"]
        out_path = out_path or compare_path_for(protocol)
    truth_path = truth_path or TRUTH_PATH
    scope = scope or ALLOY_SCOPE_DEFAULT
    out_path = out_path or COMPARE_PATH

    if not os.path.exists(truth_path):
        raise FileNotFoundError(
            "Ground-truth protocol not found: %s\n"
            "pipeline_generated builds its verifier file from a protocol .als."
            % truth_path
        )

    out_dir = os.path.dirname(os.path.abspath(out_path))
    core_path = pm.build_core(truth_path, out_dir)
    opens = [core_path.stem]
    stem = os.path.splitext(os.path.basename(out_path))[0]
    extension_path = os.path.join(out_dir, "%s_ext.als" % stem)
    if extension_lines:
        opens.append(pm.build_extension(extension_lines, core_path, module="%s_ext" % stem).stem)
    elif os.path.exists(extension_path):
        with open(extension_path, "r", encoding="utf-8") as f:
            stale = pm.GENERATED in f.read()
        if stale:
            os.remove(extension_path)   # a previous query's words; this verifier file does not open it

    verifier = (
        "".join("open %s\n" % module for module in opens) +
        "\n// ===========================================================\n"
        "// LLM-GENERATED PLAN (filled at experiment time)\n"
        "// -----------------------------------------------------------\n"
        "// CounterExample: a world that follows the plan and breaks the protocol.\n"
        "//   Instance found => UNSAFE.\n"
        "// PlanPossible: the plan can happen at all.\n"
        "//   No instance found => IMPOSSIBLE_PLAN (a missing counterexample would be vacuous).\n"
        "// SAFE = no CounterExample and some PlanPossible instance.\n"
        "// ===========================================================\n"
        "pred GeneratedPlan {\n"
        "  // LLM fills this in\n"
        "}\n\n"
        f"run CounterExample {{ GeneratedPlan and not Protocol }} {scope}\n"
        f"run PlanPossible {{ GeneratedPlan }} {scope}\n"
    )

    save_file(verifier, out_path)
    return out_path


def opened_modules(compare_path):
    """Paths of the local modules a verifier file opens (core, extension), in order."""
    with open(compare_path, "r", encoding="utf-8") as f:
        code = f.read()
    directory = os.path.dirname(os.path.abspath(compare_path))
    return [os.path.join(directory, module + ".als")
            for module in re.findall(r"(?m)^open\s+(\w+)\s*$", code)]


def verifier_source(compare_path):
    """What the LLM is shown as the Alloy file: every opened local module, then
    the verifier file itself. The verifier file alone holds only the plan slot."""
    parts = []
    for path in opened_modules(compare_path) + [compare_path]:
        with open(path, "r", encoding="utf-8") as f:
            parts.append("// ===== %s =====\n%s" % (os.path.basename(path), f.read().strip()))
    return "\n\n".join(parts) + "\n"


def ensure_compare_file(protocol=None, scope=None, rebuild=True, verbose=True,
                        extension_lines=None):
    """Make sure the verifier file for `protocol` is fresh.

    Rebuilding by default matters: a stale compare file still holds the previous
    run's GeneratedPlan, and verifying that instead of the current one would
    silently report the wrong result.
    """
    out_path = compare_path_for(protocol) if protocol else COMPARE_PATH
    source = protocol["path"] if protocol else TRUTH_PATH
    scope = scope or (protocol["scope"] if protocol else ALLOY_SCOPE_DEFAULT)

    if not rebuild and os.path.exists(out_path):
        return out_path

    path = build_compare_file(protocol=protocol, scope=scope, out_path=out_path,
                              extension_lines=extension_lines)
    if verbose:
        print("[wiring] %s -> %s (scope: %s)" % (
            os.path.basename(source), os.path.basename(path), scope
        ))
    return path


protocol_rules = pm.protocol_rules


def run_alloy(file_path):
    """Run every command in the verifier file; returns (compiled, output, status).

    The output holds, per command, `COMMAND <label>: Instance found | No instance
    found`, and for an instance its atoms and one `RULE <name>: holds | VIOLATED`
    line per protocol rule, which is what the repair prompt shows the LLM.
    """
    file_path = os.path.abspath(file_path)
    rules = []
    for path in opened_modules(file_path) + [file_path]:
        with open(path, "r", encoding="utf-8") as f:
            rules = rules or protocol_rules(f.read())

    # compile if needed: missing, or older than its source (a stale class would
    # silently keep the previous output format and verdict rules)
    if (not os.path.exists(CLASS_FILE)
            or os.path.getmtime(CLASS_FILE) < os.path.getmtime(JAVA_FILE)):
        compile_cmd = ["javac", "-cp", JAR, "AlloyCommandline.java"]
        result = subprocess.run(
            compile_cmd, cwd=JAVA_DIR, capture_output=True, text=True
        )
        if result.returncode != 0:
            return False, result.stderr, "ERROR"

    run_cmd = ["java", "-cp", "." + os.pathsep + JAR, "AlloyCommandline", file_path, *rules]
    result = subprocess.run(
        run_cmd, cwd=JAVA_DIR, capture_output=True, text=True
    )

    # Kodkod's INFO progress lines go to stderr; keep only what explains a failure
    stderr = "\n".join(line for line in result.stderr.splitlines()
                       if "INFO kodkod" not in line)
    output = (result.stdout + ("\n" + stderr if stderr.strip() else "")).strip()

    status = interpret_status(output)
    return status not in ("SYNTAX_ERROR", "UNKNOWN"), output, status


def command_outcome(output, label):
    """`Instance found`, `No instance found`, or None when the command did not run."""
    match = re.search(r"(?m)^COMMAND %s: (Instance found|No instance found)$" % re.escape(label),
                      output)
    return match.group(1) if match else None


def violated_rules(output):
    """The protocol rules the CounterExample instance breaks."""
    section = output.split("COMMAND CounterExample:", 1)[-1].split("COMMAND ", 1)[0]
    return re.findall(r"(?m)^RULE (\w+): VIOLATED$", section)


# SAFE only when there is no counterexample AND the plan is possible: a plan no
# world can follow has no counterexample for the wrong reason.

def is_safe(output):
    return interpret_status(output) == "SAFE"


def validate_plan_substance(plan, protocol=None):
    """Reject parseable-but-empty plans before asking Alloy.

    Alloy can only answer the formal safety question; it cannot tell whether
    the LLM actually described a usable plan. This lightweight gate catches the
    most common degenerate answers before verification.

    With `protocol`, the vocabulary check is derived from that protocol's own
    signatures, so it works for any domain. Without one it keeps the original
    aquatic-specific rules, which is what the batch experiment drivers expect.
    """
    issues = []
    body = plan or ""
    assignments = re.findall(r"\.\w+\s*=", body)
    declarations = re.findall(r"\bsome\s+[^{}|]+:", body)

    if protocol is not None:
        referenced = {s for s in protocol["sigs"] if re.search(r"\b%s\b" % re.escape(s), body)}
        if len(assignments) < 8:
            issues.append("Use at least 8 concrete field assignments.")
        if not declarations:
            issues.append("Declare concrete atoms with `some ...`.")
        if len(referenced) < 3:
            issues.append(
                "Reference at least 3 signatures from %s (available: %s)."
                % (protocol["file"], ", ".join(protocol["sigs"][:12]))
            )
        return (not issues), issues

    # only what any plan needs: concrete atoms and concrete values. Which people,
    # zones or incidents a plan must mention depends on the situation (a
    # lightning closure concerns the facility, not a zone), and Alloy's
    # counterexample search is what judges whether the plan is safe.
    if len(assignments) < 8:
        issues.append("Use at least 8 concrete field assignments.")
    if not declarations:
        issues.append("Declare concrete atoms with `some ...`.")

    return (not issues), issues


# ---------------- Semantic layer: which protocol governs this situation? ----------------
#
# Alloy answers only the FORMAL question: "does a violating instance exist?" --
# and it answers it against whichever model you hand it. Picking the wrong
# protocol produces a confident verdict about the wrong domain: verify a
# cardiac-arrest question against the aquatic facility model and you learn
# nothing about CPR, however green the result looks.
#
# So before any Alloy code is generated, the LLM states what it thinks the
# situation is about and which protocol governs it, and the human confirms.
# Nothing downstream runs until that confirmation.

_CONFIRM_ENV = "ALLOY_CONFIRM_PROTOCOL"


def _resolve_confirm_flag(explicit, default):
    """Explicit argument wins, then $ALLOY_CONFIRM_PROTOCOL, then the call-site default."""
    if explicit is not None:
        return bool(explicit)
    raw = os.getenv(_CONFIRM_ENV)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def format_protocol_menu(protocols, indent="  "):
    """Numbered protocol list, shown to the human and given to the LLM."""
    lines = []
    for i, d in enumerate(protocols, 1):
        lines.append("%s[%d] %s -- %s" % (indent, i, d["file"], d["title"]))
        lines.append("%s     covers: %s" % (
            indent, ", ".join(d["sigs"][:14]) + (", ..." if len(d["sigs"]) > 14 else "")
        ))
    return "\n".join(lines)


def classify_request(user_prompt, protocols, hint=None):
    """Ask the LLM what the situation is about and which protocol governs it.

    Returns {"topic", "protocol", "reason", "raw"}; "protocol" is a descriptor
    from `protocols`, or None when the answer could not be matched to one.
    """
    correction = ""
    if hint:
        correction = f"""
YOUR PREVIOUS ANSWER WAS REJECTED BY THE HUMAN REVIEWER. They said:
{hint}
Take that as authoritative and reconsider.
"""

    prompt = f"""
You are triaging a safety question before it is formally verified.

Decide TWO things:
1. What the situation is actually about, in one sentence.
2. Which ONE safety protocol below governs it.

AVAILABLE PROTOCOLS:
{format_protocol_menu(protocols, indent="")}
{correction}
THE SITUATION:
{user_prompt}

Answer in EXACTLY this format, three lines, nothing else:
TOPIC: <one sentence describing what the situation is about>
PROTOCOL: <exact file name from the list above>
REASON: <one or two sentences on why that protocol governs it>
"""

    try:
        raw = call_claude(prompt, max_new_tokens=600, temperature=0) or ""
    except Exception as exc:
        return {"topic": "", "protocol": None, "raw": "",
                "reason": "LLM unavailable: %s" % exc}

    def field(label):
        m = re.search(r"^%s:\s*(.+)$" % label, raw, re.M | re.I)
        return m.group(1).strip() if m else ""

    named = field("PROTOCOL")
    chosen = None
    for d in protocols:
        if d["file"].lower() == named.lower() or d["name"].lower() == named.lower():
            chosen = d
            break
    if chosen is None and named:
        for d in protocols:                       # tolerate partial answers
            if d["name"].lower() in named.lower() or named.lower() in d["file"].lower():
                chosen = d
                break

    return {
        "topic": field("TOPIC"),
        "protocol": chosen,
        "reason": field("REASON"),
        "raw": raw.strip(),
    }


def confirm_protocol(user_prompt, classification, protocols):
    """Show the LLM's reading of the situation and require an explicit `yes`.

    Returns (decision, protocol, feedback):
      "yes"   -> `protocol` is confirmed; generate the plan against it
      "pick"  -> `protocol` was overridden by the human choosing from the menu
      "no"    -> re-classify; `feedback` carries the human's correction
      "abort" -> stop

    Auto-accepts when stdin is not a TTY, so piped or batch runs never block.
    """
    chosen = classification.get("protocol")

    if not sys.stdin.isatty():
        print("[semantic check] non-interactive session; accepting %s."
              % (chosen["file"] if chosen else "no protocol"))
        return ("yes" if chosen else "abort"), chosen, ""

    bar = "=" * 68
    print("\n" + bar)
    print("SEMANTIC CHECK -- which safety protocol applies?")
    print(bar)
    print("\nYOU ASKED:\n  %s" % (user_prompt or "(no task text)").strip())

    topic = classification.get("topic") or "(the model did not state a topic)"
    print("\nTHE MODEL READS THIS AS:\n  %s" % topic)

    if chosen:
        print("\nIT WILL VERIFY AGAINST:\n  %s -- %s" % (chosen["file"], chosen["title"]))
        reason = classification.get("reason")
        if reason:
            print("  because: %s" % reason)
        print("  scope: %s" % chosen["scope"])
    else:
        print("\nIT COULD NOT PICK A PROTOCOL.")
        if classification.get("reason"):
            print("  %s" % classification["reason"])

    print("\nALL AVAILABLE PROTOCOLS:")
    print(format_protocol_menu(protocols))

    print("\n" + "-" * 68)
    print("The plan is only written after you confirm the protocol.")
    print("Type `yes` to accept, a number to pick a different protocol,")
    print("`no` to re-classify with a correction, or `abort` to stop.")

    try:
        answer = input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n[semantic check] input closed; aborting.")
        return "abort", None, ""

    if answer in ("abort", "quit", "q"):
        return "abort", None, ""

    if answer.isdigit():
        idx = int(answer)
        if 1 <= idx <= len(protocols):
            return "pick", protocols[idx - 1], ""
        print("No protocol numbered %d." % idx)
        return "no", None, "The reviewer tried to pick protocol %d, which does not exist." % idx

    if answer in ("yes", "y") and chosen:
        return "yes", chosen, ""
    if answer in ("yes", "y"):
        print("There is no protocol to accept -- pick one by number.")
        return "no", None, "The reviewer accepted, but no protocol had been selected."

    try:
        reason = input("Which protocol should it be, and why? (Enter to skip)\n> ").strip()
    except (EOFError, KeyboardInterrupt):
        reason = ""
    return "no", None, reason


def select_protocol(user_prompt, protocols=None, confirm=None, max_retries=3,
                    verbose=True):
    """The semantic layer: understand the request, pick a protocol, get a `yes`.

    Returns the confirmed protocol descriptor, or None if the human aborted.
    """
    if protocols is None:
        protocols = discover_protocols()
    if not protocols:
        raise FileNotFoundError(
            "No safety protocols found in %s. Expected at least one .als model "
            "(e.g. safety_protocol.als)." % BASE
        )

    confirm_enabled = _resolve_confirm_flag(confirm, True)
    hint = None

    for attempt in range(max_retries + 1):
        if verbose:
            print("\n[semantic] reading %d protocol(s): %s" % (
                len(protocols), ", ".join(d["file"] for d in protocols)
            ))
        classification = classify_request(user_prompt, protocols, hint=hint)

        if not confirm_enabled:
            chosen = classification.get("protocol")
            if verbose:
                print("[semantic] auto-selected %s (confirmation disabled)"
                      % (chosen["file"] if chosen else "nothing"))
            return chosen

        decision, protocol, feedback = confirm_protocol(
            user_prompt, classification, protocols
        )

        if decision == "abort":
            return None
        if decision in ("yes", "pick"):
            if verbose:
                print("[semantic] confirmed: %s" % protocol["file"])
            return protocol

        hint = feedback or "The reviewer rejected that protocol without giving a reason."
        if verbose:
            print("[semantic] re-classifying with the reviewer's correction.")

    print("Could not agree on a protocol after %d attempts." % (max_retries + 1))
    return None


_OUTPUT_CONTRACT = """
Output exactly one Alloy predicate block:
pred GeneratedPlan {
  ...
}

Do not include markdown, prose, explanations, or any code outside the predicate.
The predicate must be a concrete, non-trivial plan for the specific TASK:
- include the patron or guest described by the TASK;
- include the relevant Facility and zone/incident;
- include staff or supervision response actors;
- set enough fields to show what is allowed, denied, closed, evacuated, or required.
Do not answer with a placeholder such as `some Patron`, one hygiene field, or an
empty/avoidant plan.
"""

# The contract above names patrons, zones and facilities, which only makes sense
# for the aquatic protocol. Any other protocol gets the same demands expressed in
# its own vocabulary. Passing no protocol keeps the original wording, which is
# what the batch experiment drivers were tuned against.
_GENERIC_OUTPUT_CONTRACT = """
Output exactly one Alloy predicate block:
pred GeneratedPlan {{
  ...
}}

Do not include markdown, prose, explanations, or any code outside the predicate.
The predicate must be a concrete, non-trivial plan for the specific TASK:
- introduce the concrete actors and objects the TASK describes;
- use the signatures and fields of {file} and no others;
- set enough fields to show what is required, permitted, denied, or must happen next.
Available signatures: {sigs}
Do not answer with a placeholder, a single field, or an empty/avoidant plan.
"""


def output_contract(protocol=None):
    """The output contract, phrased in the selected protocol's vocabulary."""
    if protocol is None:
        return _OUTPUT_CONTRACT
    return _GENERIC_OUTPUT_CONTRACT.format(
        file=pm.core_name(protocol["path"]) + ".als",   # the module the LLM is shown
        sigs=", ".join(protocol["sigs"]),
    )


def describe_domain(protocol=None):
    """Short domain phrase for the generation prompt."""
    if protocol is None:
        return "an aquatic-facility safety scenario"
    return "a safety scenario governed by %s (%s)" % (
        protocol["file"], protocol["title"]
    )


# Step 1 of the main line: the roundtrip turns the query into its verified
# formal version. Imported lazily so the plan-only path needs nothing from it.

QUERY_ATTEMPTS = 5

RELEASE_DIAGNOSE_SYSTEM = """A user's message was formalized over a fixed vocabulary -- a safety
protocol's signatures and fields, plus any extension words. Either an NLI check
found that the readback of the formalization does not say what the user said, or
the formalization could not be written at all (every attempt was rejected with the
error shown). Decide why, choosing exactly one cause:

VOCABULARY: the user states something about the situation that the vocabulary has
  no signature or field for, so no translation over this vocabulary could keep it.
  When the rejection says a join always yields an empty set (a field used on a
  signature that does not have it, e.g. `m.inWater` for an Adult m), the missing
  word is exactly that field for that signature: declare it, e.g.
  `adultInWater: Adult -> lone WaterZone`.
TRANSLATION: the vocabulary can express what the user stated, but the translation
  lost, added or changed something.
NONE: (only when there is a readback) every fact about the situation the user
  stated is in the readback; the difference NLI saw is only wording, or a question
  the user asks, which is not a fact to formalize. This is a false alarm.

Choose VOCABULARY only after checking every signature and field that could express
the missing statement. Only statements about the situation count: a question, a
request for a plan, or background that is not part of the situation is not
something to formalize.

Reply with exactly these lines:
CAUSE: VOCABULARY|TRANSLATION|NONE
MISSING: <what the user said that the readback lost or changed>
CLOSEST: <the existing signatures or fields you checked, and why none can express it>
DECLARATIONS:
<only for VOCABULARY: the new words, one per line, in this format>
""" + pm.EXTENSION_FORMAT


def _roundtrip_module():
    parent = os.path.dirname(BASE)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    import pipeline as roundtrip
    return roundtrip


def _parse_release_diagnosis(reply):
    """CAUSE / MISSING / CLOSEST, and every line after DECLARATIONS:."""
    fields, declarations, in_declarations = {}, [], False
    for line in reply.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            continue
        key, separator, value = stripped.partition(":")
        if not in_declarations and separator and key.strip().upper() in ("CAUSE", "MISSING", "CLOSEST"):
            fields[key.strip().upper()] = value.strip()
        elif not in_declarations and separator and key.strip().upper() == "DECLARATIONS":
            in_declarations = True
            if value.strip():
                declarations.append(value.strip())
        elif in_declarations and stripped:
            declarations.append(stripped)
    cause = fields.get("CAUSE", "").upper()
    return {
        "cause": cause if cause in ("VOCABULARY", "TRANSLATION", "NONE") else "",
        "missing": fields.get("MISSING", ""),
        "closest": fields.get("CLOSEST", ""),
        "declarations": declarations if cause == "VOCABULARY" else [],
    }


def diagnose_release(client, settings, user_prompt, attempt_dir, vocabulary, category,
                     compile_error=""):
    """Why the attempt was not released: VOCABULARY (with new words),
    TRANSLATION, or NONE (an NLI false alarm; only with a readback)."""
    from pathlib import Path
    attempt_dir = Path(attempt_dir)
    rule = ""
    if (attempt_dir / "y_original.als").exists():
        rule = _roundtrip_module().equivalence.rule_of(
            (attempt_dir / "y_original.als").read_text(encoding="utf-8"))
    if compile_error:
        evidence = f"""Last rejected formalization:
```alloy
{rule}
```

Every attempt was rejected; the last rejection:
{compile_error.strip()}
"""
    else:
        readback = (attempt_dir / "x_prime.txt").read_text(encoding="utf-8").strip()
        evidence = f"""Formalization (y_original):
```alloy
{rule}
```

Readback (x_prime):
{readback}

NLI category of the message against the readback: {category}
"""
    prompt = f"""User message:
{user_prompt.strip()}

{evidence}
Fixed vocabulary:
```alloy
{vocabulary.source.strip()}
```"""
    diagnosis = {"cause": "", "missing": "", "closest": "", "declarations": [], "raw": ""}
    for _ in range(settings.max_diagnosis_attempts):
        reply = client.complete(RELEASE_DIAGNOSE_SYSTEM, prompt,
                                temperature=settings.judge_temperature,
                                max_tokens=settings.max_tokens,
                                model=settings.judge_model or settings.model)
        diagnosis = {**_parse_release_diagnosis(reply), "raw": reply}
        if diagnosis["cause"]:
            return diagnosis
    return diagnosis


def correct_declarations(client, settings, declarations, problems):
    """One more try at extension lines the fixed-format check refused."""
    reply = client.complete(
        "Rewrite the rejected extension lines so that every line meets the format below. "
        "Reply with the corrected lines only, one per line, nothing else.\n\n" + pm.EXTENSION_FORMAT,
        "Rejected lines:\n" + "\n".join(declarations) + "\n\nWhy they were rejected:\n- "
        + "\n- ".join(problems),
        temperature=settings.judge_temperature, max_tokens=settings.max_tokens,
        model=settings.judge_model or settings.model)
    return [line.strip() for line in reply.splitlines()
            if line.strip() and not line.strip().startswith("```")]


def _write_json(path, payload):
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def previous_formalization(user_prompt, protocol_path, stage_dir):
    """The result of an earlier formalize_query for exactly this query and this
    protocol file (same text, same SHA-256), or the string "none" when there is
    no such result. A released result comes back as load_formal_query's dict,
    a not-released one as None."""
    import json
    summary_path = os.path.join(stage_dir, "query_release.json")
    if not os.path.exists(summary_path):
        return "none"
    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)
    with open(protocol_path, "r", encoding="utf-8") as f:
        sha = hashlib.sha256(f.read().encode("utf-8")).hexdigest()
    if (summary.get("query") != user_prompt.strip()
            or summary.get("protocol_sha256") != sha or "released" not in summary):
        return "none"
    if not summary["released"]:
        return None
    return load_formal_query(os.path.join(stage_dir, "attempt-%d" % summary["released_attempt"],
                                          "y_original.als"))


def formalize_query(user_prompt, protocol_path, stage_dir, settings=None, client=None,
                    attempts=QUERY_ATTEMPTS):
    """Step 1 of the main line: formalize the query over the protocol's own
    vocabulary, extending it where the protocol has no word, until the formal
    query is released or `attempts` roundtrips have been run.

    Released = Alloy proved y_original <-> y_prime AND NLI finds no drift
    between the query and the readback x' (drift = Unrelated or Contradiction).
    After a roundtrip that is not released:
      - Alloy not equivalent        -> the next attempt reruns the roundtrip;
      - NLI drift                   -> the LLM diagnoses the cause:
          VOCABULARY  the protocol has no word for something the user said: the
                      new declarations it proposes pass protocol_modules'
                      fixed-format check (corrected up to twice when refused)
                      and join the extension; the next attempt reruns the
                      roundtrip over protocol + extension;
          TRANSLATION the next attempt reruns the roundtrip as it is;
      - NLI unavailable             -> stop: nothing can release the query.
    Each attempt runs in <stage_dir>/attempt-<n>/. Returns
    {"rule", "extension", "path"} for the released formal query, or None. The
    whole history is written to <stage_dir>/query_release.json, and the released
    attempt's own record beside its y_original.als (what load_formal_query reads).
    """
    from dataclasses import replace
    from pathlib import Path
    roundtrip = _roundtrip_module()

    stage = Path(stage_dir)
    stage.mkdir(parents=True, exist_ok=True)
    settings = settings or roundtrip.Settings()
    client = client or roundtrip.LLM(settings.model)
    protocol_text = Path(protocol_path).read_text(encoding="utf-8")
    core = pm.split_protocol(protocol_text)[0]
    extension, history = [], []
    # what this result was computed from, so a later run can tell whether it still applies
    origin = {"query": user_prompt.strip(), "protocol": os.path.abspath(protocol_path),
              "protocol_sha256": hashlib.sha256(protocol_text.encode("utf-8")).hexdigest()}

    for attempt in range(1, attempts + 1):
        attempt_dir = stage / ("attempt-%d" % attempt)
        vocabulary = roundtrip.load_protocol_vocabulary(protocol_path, extension)
        print("\n[QUERY ATTEMPT %d/%d] extension words: %d" % (attempt, attempts, len(extension)),
              flush=True)
        # the roundtrip's own NLI step only prints; the release decision computes it once, here
        equivalent = roundtrip.run(user_prompt, vocabulary, attempt_dir,
                                   replace(settings, run_nli=False), client)
        semantic = {}
        readback = attempt_dir / "x_prime.txt"
        if equivalent and readback.exists():
            semantic = roundtrip.compare_nli(user_prompt.strip(),
                                             readback.read_text(encoding="utf-8").strip(),
                                             settings.nli_model)
        record = {"attempt": attempt, "extension": list(extension), "equivalent": bool(equivalent),
                  "nli_category": semantic.get("category"), "drift": semantic.get("drift")}

        if equivalent and semantic.get("drift") is False:
            record.update(released=True, reason="released")
            history.append(record)
            _write_json(attempt_dir / "query_release.json", record)
            _write_json(stage / "query_release.json",
                        {**origin, "released": True, "released_attempt": attempt,
                         "extension": list(extension), "attempts": history})
            print("\n[QUERY RELEASE]\nreleased at attempt %d" % attempt, flush=True)
            return load_formal_query(attempt_dir / "y_original.als")

        record["released"] = False
        diagnosis = None
        if not equivalent:
            outcome = attempt_dir / "roundtrip_outcome.txt"
            stopped = outcome.read_text(encoding="utf-8").strip() if outcome.exists() else ""
            record["stopped_at"] = stopped
            record["reason"] = {
                "VOCAB": "the vocabulary did not compile",
                "S1": "S1 produced no rule that passed the shape check and Alloy",
                "S2": "S2 produced no readback",
                "S3": "S3 produced no rule that passed the shape check and Alloy",
            }.get(stopped, "Alloy did not prove y_original <-> y_prime")
            error_file = attempt_dir / ("%s_last_error.txt" % stopped)
            if stopped in ("S1", "S3") and error_file.exists():
                # a rule that cannot be written may be a missing word, too
                diagnosis = diagnose_release(client, settings, user_prompt, attempt_dir, vocabulary,
                                             None, compile_error=error_file.read_text(encoding="utf-8"))
        elif semantic.get("drift") is None:
            record["reason"] = "NLI unavailable: %s" % semantic.get("note", "")
            history.append(record)
            _write_json(attempt_dir / "query_release.json", record)
            break
        else:
            record["reason"] = "NLI drift: %s" % semantic.get("category")
            diagnosis = diagnose_release(client, settings, user_prompt, attempt_dir,
                                         vocabulary, semantic.get("category"))
            if diagnosis["cause"] == "NONE":
                # the situation facts are all there: NLI saw only wording or a question
                record.update(diagnosis={k: diagnosis[k] for k in ("cause", "missing", "closest")},
                              released=True, reason="released: NLI drift judged a false alarm")
                history.append(record)
                _write_json(attempt_dir / "query_release.json", record)
                _write_json(stage / "query_release.json",
                            {**origin, "released": True, "released_attempt": attempt,
                             "extension": list(extension), "attempts": history})
                print("\n[QUERY RELEASE]\nreleased at attempt %d (NLI false alarm)" % attempt, flush=True)
                return load_formal_query(attempt_dir / "y_original.als")
        if diagnosis is not None:
            record["diagnosis"] = {k: diagnosis[k] for k in ("cause", "missing", "closest", "declarations")}
            print("\n[RELEASE DIAGNOSIS]\ncause: %s\nmissing: %s" % (diagnosis["cause"], diagnosis["missing"]),
                  flush=True)
            if diagnosis["cause"] == "VOCABULARY":
                declarations = diagnosis["declarations"]
                for _ in range(3):      # the proposal, then at most two corrections
                    accepted, problems = pm.check_extension_lines(extension + declarations, core)
                    if not problems:
                        break
                    declarations = correct_declarations(client, settings, declarations, problems)
                if problems:
                    record["extension_rejected"] = problems
                else:
                    extension = extension + declarations
                    record["extension_added"] = declarations
                print("extension: %s" % ("; ".join(record.get("extension_added", []))
                                         or "rejected: " + "; ".join(problems)), flush=True)
        history.append(record)
        _write_json(attempt_dir / "query_release.json", record)

    _write_json(stage / "query_release.json",
                {**origin, "released": False, "released_attempt": None,
                 "extension": list(extension), "attempts": history})
    print("\n[QUERY RELEASE]\nnot released after %d attempt(s)" % len(history), flush=True)
    return None


# The formal query as a prompt section. It is written in the protocol's own
# signatures and fields (plus any extension words, which the verifier file opens
# too), the same words GeneratedPlan uses.

def formal_query_section(formal_query):
    if not formal_query or not formal_query.strip():
        return ""
    return f"""
FORMAL QUERY:
The predicate below is the formal version of the TASK, written in the protocol's
own signatures and fields (and, where the protocol had no word, in extension words
declared in `QueryExt`, which the Alloy file below opens). It was produced by an
auto-formalization roundtrip and released by it: formalizing its read-back gave a
predicate Alloy proved equivalent, and an NLI check found the read-back consistent
with the TASK. The TASK text and this predicate describe the same situation; the
predicate states the facts the user stated, and a field it leaves out was not
stated. Read both to understand the situation, then write GeneratedPlan as the
response plan to it: state the same situation facts in the same words, plus the
actions the protocol requires. Do not assume situation facts that contradict or
go beyond them.
{formal_query.strip()}
"""


# The first generation step where we prompt the LLM to generate a plan from scratch based on the user prompt. 

def generate_plan(user_prompt, compare_path=COMPARE_PATH, protocol=None,
                  formal_query=None):
    full_code = verifier_source(compare_path)

    prompt = f"""
You are generating an Alloy predicate for {describe_domain(protocol)}.

TASK:
{user_prompt}
{formal_query_section(formal_query)}
RULES:
{output_contract(protocol)}
- Use ONLY variables, signatures, and fields already defined in the file below.
- Do NOT invent new names.

FULL Alloy file:
{full_code}
"""

    return call_claude(prompt, temperature=0.7)


COUNTEREXAMPLE_GOAL = """Alloy checks GeneratedPlan against `pred Protocol` in the file below by
searching for a counterexample: a world that follows GeneratedPlan but violates
Protocol. It found one (shown below). Modify GeneratedPlan so that no
counterexample exists, while it still answers the TASK."""


def interpret_status(alloy_output):
    """Interpret the verifier's two commands (see the module docstring).

    A type warning counts as a syntax error: the runner stops at it, because a
    comparison between disjoint types is constantly false and silently changes
    what the plan says (the roundtrip applies the same rule to `pred rule`)."""
    if ("Syntax error" in alloy_output or "Type error" in alloy_output
            or "Type warning:" in alloy_output):
        return "SYNTAX_ERROR"
    counterexample = command_outcome(alloy_output, "CounterExample")
    possible = command_outcome(alloy_output, "PlanPossible")
    if counterexample == "Instance found":
        return "UNSAFE"
    if counterexample == "No instance found" and possible == "No instance found":
        return "IMPOSSIBLE_PLAN"
    if counterexample == "No instance found" and possible == "Instance found":
        return "SAFE"
    return "UNKNOWN"


def counterexample_feedback(alloy_output):
    """What the repair prompt says about the verdict: the broken rules and the
    counterexample world, or why the plan cannot happen."""
    status = interpret_status(alloy_output)
    if status == "UNSAFE":
        broken = violated_rules(alloy_output)
        section = alloy_output.split("COMMAND CounterExample:", 1)[-1].split("COMMAND ", 1)[0]
        instance = section.split("BEGIN INSTANCE", 1)[-1].split("END INSTANCE", 1)[0].strip()
        return (
            "Alloy found a COUNTEREXAMPLE: a world that satisfies GeneratedPlan but "
            "violates Protocol.\n"
            "Protocol rules violated in that world: %s\n"
            "The counterexample world (atoms and field values):\n%s"
            % (", ".join(broken) or "(not identified)", instance[:6000])
        )
    if status == "IMPOSSIBLE_PLAN":
        return (
            "GeneratedPlan cannot be satisfied at all: it contradicts itself or the "
            "structural facts of the model (e.g. a zone outside every facility, a "
            "one-way buddy pair, a type mismatch that is always false). A plan no "
            "world can follow is not a plan, so the missing counterexample means nothing."
        )
    return alloy_output


def run_with_trace(user_prompt, compare_path=COMPARE_PATH, max_iters=6, verbose=True,
                   rebuild=False, protocol=None, formal_query=None):
    """Generate and iteratively repair a plan, returning a structured trace.

    Verdicts (see the module docstring):
      SAFE            = no CounterExample instance, and a PlanPossible instance.
      UNSAFE          = a CounterExample instance: the plan admits a protocol violation.
      IMPOSSIBLE_PLAN = no PlanPossible instance: the plan cannot happen at all.
    UNSAFE and IMPOSSIBLE_PLAN both go to a logic repair, which shows the LLM the
    counterexample world and the violated rules (or why the plan is impossible).

    The semantic layer (protocol selection) is NOT run here -- it belongs to the
    interactive entry point. This function verifies against whatever
    `compare_path` it is handed, which is what the batch drivers need.
    `protocol` is optional and only sharpens the substance check.

    `rebuild` defaults to OFF: the experiment drivers build their own compare
    file before calling this. Pass rebuild=True to derive `compare_path` from
    the protocol first.
    """
    if rebuild:
        build_compare_file(protocol=protocol, out_path=compare_path)

    iterations = []
    status = None
    plan = ""
    alloy_logs = ""
    raw_response = ""
    substance_feedback = ""

    for it in range(1, max_iters + 1):
        if it == 1 or status == "EMPTY_RESPONSE":
            # a reply with no text at all carries nothing to repair: generate afresh
            kind = "initial"
            raw_response = generate_plan(user_prompt, compare_path=compare_path,
                                         protocol=protocol, formal_query=formal_query)
        elif status == "SYNTAX_ERROR":
            kind = "syntax_repair"
            code = verifier_source(compare_path)
            raw_response = call_claude(f"""
Fix ONLY this Alloy predicate so it compiles.

RULES:
- Output ONLY: pred GeneratedPlan {{ ... }}
- Do NOT include any other code

Current:
{plan}

Previous response:
{raw_response}

Error:
{alloy_logs}

Reference code:
{code}
""", temperature=0)
        elif status == "NON_SUBSTANTIVE":
            kind = "substance_repair"
            code = verifier_source(compare_path)
            raw_response = call_claude(f"""
Your previous reply compiled as a predicate-shaped block, but it was not a
substantive plan for the TASK.

TASK:
{user_prompt}
{formal_query_section(formal_query)}
Problems to fix:
{substance_feedback}

RULES:
{output_contract(protocol)}
- Use ONLY variables, signatures, and fields already defined in the file below.
- Do NOT invent new names.

Previous plan:
{plan}

Reference code:
{code}
""", temperature=0)
        else:
            kind = "logic_repair"
            code = verifier_source(compare_path)
            raw_response = call_claude(f"""
You are repairing an Alloy plan.

{COUNTEREXAMPLE_GOAL}

TASK:
{user_prompt}
{formal_query_section(formal_query)}
RULES:
{output_contract(protocol)}
- Only use variables, signatures, and fields already defined in the file below.
- Do NOT invent new names.

Reference code:
{code}

Current plan:
{plan}

Verifier result:
{counterexample_feedback(alloy_logs)}
""", temperature=0)

        new_plan = extract_generated_plan(raw_response or "")
        if not new_plan:
            empty = not (raw_response or "").strip()
            status = "EMPTY_RESPONSE" if empty else "SYNTAX_ERROR"
            plan = ""
            alloy_logs = ("The LLM returned no text." if empty
                          else "Could not extract pred GeneratedPlan from LLM response.")
            iterations.append({
                "iter": it,
                "kind": kind,
                "status": status,
                "plan": "",
                "raw_response": raw_response or "",
                "alloy_output": alloy_logs,
                "ran_alloy": False,
            })
            if verbose:
                print(f"      iter {it} ({kind}): {status}")
            continue

        plan = new_plan
        substantive, issues = validate_plan_substance(plan, protocol=protocol)
        if not substantive:
            status = "NON_SUBSTANTIVE"
            substance_feedback = "\n".join(f"- {issue}" for issue in issues)
            alloy_logs = substance_feedback
            iterations.append({
                "iter": it,
                "kind": kind,
                "status": status,
                "plan": plan,
                "raw_response": raw_response or "",
                "alloy_output": alloy_logs,
                "ran_alloy": False,
            })
            if verbose:
                print(f"      iter {it} ({kind}): {status}")
            continue

        with open(compare_path, "r") as f:
            code = f.read()
        updated = replace_generated_plan(code, plan)
        save_file(updated, compare_path)

        success, alloy_logs, run_status = run_alloy(compare_path)
        status = interpret_status(alloy_logs)
        if not success and status == "UNKNOWN":
            status = run_status

        iterations.append({
            "iter": it,
            "kind": kind,
            "status": status,
            "plan": plan,
            "raw_response": raw_response or "",
            "alloy_output": alloy_logs,
            "ran_alloy": True,
        })
        if verbose:
            print(f"      iter {it} ({kind}): {status}")

        if status == "SAFE":
            return {
                "iterations": iterations,
                "final_status": "SAFE",
                "total_iters": it,
            }

    return {
        "iterations": iterations,
        "final_status": status or "UNKNOWN",
        "total_iters": max_iters,
    }

# The full pipeline of generating the initial plan, repairing syntax errors , then repairing logic errors if the generated plan is not safe

def generate_and_verify(user_prompt, rounds=1, confirm=None, rebuild=True,
                        protocol=None, formal_query=None, formalize=True,
                        query_stage_dir=None, max_iters=10):
    """The main line: protocol -> formal query over it -> plan -> verification.

    `formal_query` is a released query ({"rule", "extension", ...}, e.g. from
    load_formal_query); without one, and unless `formalize` is False, the query
    is formalized over the selected protocol first, and nothing is generated
    when the formalization is not released."""
    # ---- semantic layer: understand the request, agree on a protocol ----
    # Nothing below runs until the human confirms which protocol governs this
    # situation, because the verdict is only meaningful against the right model.
    if protocol is None:
        protocol = select_protocol(user_prompt, confirm=confirm)
        if protocol is None:
            print("No protocol confirmed; nothing was generated or verified.")
            return False

    # ---- step 1: the formal query, over the protocol's own vocabulary ----
    if formal_query is None and formalize:
        query_stage_dir = query_stage_dir or os.path.join(BASE, "query_stage")
        formal_query = formalize_query(user_prompt, protocol["path"], query_stage_dir)
        if formal_query is None:
            print("The query's formalization was not released (see "
                  "query_release.json); no plan was generated.")
            return False
    if formal_query:
        print("\nFORMAL QUERY (released):\n%s" % formal_query["rule"])

    # ---- wire the verifier file up from the confirmed protocol, opening the
    # formal query's extension words so the plan can use them too ----
    compare_path = ensure_compare_file(
        protocol=protocol, rebuild=rebuild,
        extension_lines=(formal_query or {}).get("extension") or None)

    # ---- generate, verify, repair: the same loop the experiment drivers run,
    # so both entry points share every prompt and every verdict rule ----
    for round_no in range(1, rounds + 1):
        print(f"\n == Pipeline round {round_no} ==")
        trace = run_with_trace(user_prompt, compare_path=compare_path,
                               max_iters=max_iters, verbose=True,
                               protocol=protocol,
                               formal_query=(formal_query or {}).get("rule"))
        final = trace["iterations"][-1] if trace["iterations"] else {}
        if trace["final_status"] == "SAFE":
            print("SAFE PLAN VERIFIED against %s" % protocol["file"])
            print(final.get("plan", ""))
            return True
        print("Round %d ended %s after %d iterations." % (
            round_no, trace["final_status"], trace["total_iters"]))
        if final.get("alloy_output"):
            print(counterexample_feedback(final["alloy_output"]))

    print("Failed to produce safe plan")
    return False


# ------------------ Main ------------------

def load_formal_query(path):
    """A released formal query: {"rule", "extension", "path"}.

    `rule` is the `pred rule { ... }` block of the attempt's y_original.als
    (without the `open` lines and runs around it); `extension` holds the
    extension lines it was formalized with. Only a released query may be used:
    formalize_query writes query_release.json beside y_original.als, and a
    module without a record saying `"released": true` is refused, so a formal
    query read from disk meets the same release criterion as one produced now."""
    import json
    path = os.path.abspath(path)
    record = os.path.join(os.path.dirname(path), "query_release.json")
    if not os.path.exists(record):
        raise ValueError("%s has no query_release.json beside it: it was not produced "
                         "by formalize_query, so it has not met the release criterion" % path)
    with open(record, "r", encoding="utf-8") as f:
        release = json.load(f)
    if not release.get("released"):
        raise ValueError("%s was not released: %s" % (path, release.get("reason", "")))
    with open(path, "r", encoding="utf-8") as f:
        code = f.read()
    match = re.search(r"(?m)^pred\s+rule\b", code)
    if not match:
        raise ValueError("no `pred rule` in %s" % path)
    depth = 0
    for i in range(code.index("{", match.start()), len(code)):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return {"rule": code[match.start():i + 1],
                        "extension": list(release.get("extension", [])),
                        "path": path}
    raise ValueError("unbalanced `pred rule` in %s" % path)


def main():
    import argparse

    #insert prompt below: (e.g. "someone just fell and their spine hurts, what do i do?")
    prompt = "Documented news incident at a real community pool: a 13-year-old boy at Old Orchard Park community pool in Frisco, Texas dove head-first into the SHALLOW END of the pool (trying to flee a wasp), struck the bottom, fractured his C4 and C5 vertebrae, and was left without motor or sensory function below the level of injury (now described as quadriplegic). Imagine the same scenario at OUR facility: a teenage patron performs a head-first dive into the shallow zone of one of our pools. Generate a plan describing whether this behavior is permitted at our facility, where head-first dives ARE permitted (depth/zone), and what the lifeguard's required intervention must be."

    parser = argparse.ArgumentParser(description="Generate an Alloy plan and verify it against a safety protocol")
    parser.add_argument("--query", default=prompt,
                        help="the natural-language query, or a path to a file holding it")
    parser.add_argument("--formal-query", default="",
                        help="a y_original.als released by an earlier run (query_release.json "
                             "beside it), instead of formalizing --query now")
    parser.add_argument("--no-formal-query", action="store_true",
                        help="skip step 1 and generate the plan from the text alone")
    arguments = parser.parse_args()

    query = arguments.query
    if os.path.exists(query):
        with open(query, "r", encoding="utf-8") as f:
            query = f.read().strip()
    formal_query = load_formal_query(arguments.formal_query) if arguments.formal_query else None

    generate_and_verify(query, formal_query=formal_query,
                        formalize=not arguments.no_formal_query)


if __name__ == "__main__":
    main()
