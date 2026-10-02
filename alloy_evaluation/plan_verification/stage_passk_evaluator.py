"""Chen-style pass@k charts for the swimming pipeline.

Every chart labeled pass@k in this script follows Chen et al.: for a fixed
problem, draw n independent samples, count c successful samples, and estimate
pass@k as 1 - C(n-c, k) / C(n, k).

Stage-specific repair samples are branched from the same captured failing
state. Each sample runs a capped loop; k counts independent loops. Stage curves
are conditional on encountering a failure, averaged over those fixed cases.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pipeline_generated as pipeline
import run_swimming_experiment as swimming


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = BASE_DIR.parents[1] / "results" / "stage_passk"
SYNTAX_STATUSES = {"SYNTAX_ERROR", "EMPTY_RESPONSE"}
LOGIC_STATUSES = {"UNSAFE", "IMPOSSIBLE_PLAN", "QUERY_MISMATCH", "INVALID_PLAN"}
COMPILED_STATUSES = {"COMPILED", "SAFE", "UNSAFE", "IMPOSSIBLE_PLAN", "QUERY_MISMATCH"}


def pass_at_k(n: int, c: int, k: int) -> float | None:
    if n <= 0 or k < 1 or k > n:
        return None
    if n - c < k:
        return 1.0
    product = 1.0
    for i in range(n - c + 1, n + 1):
        product *= 1.0 - k / i
    return 1.0 - product


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    temporary.replace(path)


def load_prompts(path: Path, prompt_ids: list[int] | None = None) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        prompts = json.load(handle).get("prompts", [])
    if not prompts:
        raise SystemExit(f"no prompts found in {path}")
    if prompt_ids is not None:
        missing = set(prompt_ids) - {prompt["id"] for prompt in prompts}
        if missing:
            raise SystemExit(f"unknown prompt IDs: {sorted(missing)}")
        prompts = [prompt for prompt in prompts if prompt["id"] in prompt_ids]
        unusable = [prompt["id"] for prompt in prompts if not prompt.get("eval_usable", True)]
        if unusable:
            raise SystemExit(f"unusable prompt IDs: {unusable}; see eval_exclusion_reason in {path}")
    prompts = [prompt for prompt in prompts if prompt.get("eval_usable", True)]
    if not prompts:
        raise SystemExit(f"no usable prompts found in {path}")
    return prompts


def first_iteration(trace: dict[str, Any], statuses: set[str]) -> dict[str, Any] | None:
    return next((item for item in trace.get("iterations", [])
                 if item.get("status") in statuses), None)



def next_plan_call(status: str | None, counters: dict[str, int],
                   args: argparse.Namespace) -> str | None:
    """Choose the next plan-loop call under separate per-stage caps."""
    if status is None:
        if counters["initial"] >= 1:
            return None
        counters["initial"] += 1
        return "initial"
    if status in SYNTAX_STATUSES:
        if counters["syntax_repair"] >= args.syntax_cap:
            return None
        counters["syntax_repair"] += 1
        return "syntax_repair"
    if status not in LOGIC_STATUSES or counters["logic_repair"] >= args.logic_cap:
        return None
    counters["logic_repair"] += 1
    return "logic_repair"


def run_with_stage_caps(user_prompt: str, compare_path: Path, formal_query: str,
                        args: argparse.Namespace, *, failure: dict[str, Any] | None = None,
                        stage: str | None = None, checkpoint: Path | None = None) -> dict[str, Any]:
    """A copy of the plan loop with explicit per-stage caps.

    The production helper has one max_iters counter.  For evaluation we need the
    caps to be named so a complete pipeline sample has a clear budget.
    """
    counters = {"initial": 0, "syntax_repair": 0, "logic_repair": 0}
    iterations: list[dict[str, Any]] = []
    failure = failure or {}
    status: str | None = failure.get("status")
    plan = failure.get("plan", "")
    raw_response = failure.get("raw_response", "")
    alloy_logs = failure.get("alloy_output", "")
    if args.resume and checkpoint and checkpoint.exists():
        saved = read_json(checkpoint)
        if "final_status" in saved:
            if saved.get("iterations"):
                saved_plan = saved["iterations"][-1].get("plan") or "pred GeneratedPlan {}"
                code = compare_path.read_text(encoding="utf-8")
                pipeline.save_file(pipeline.replace_generated_plan(code, saved_plan), str(compare_path))
            print(f"      [resume] reusing completed loop: {checkpoint}", flush=True)
            return saved
        iterations = saved.get("iterations", [])
        counters = saved.get("stage_counts", counters)
        if iterations:
            last = iterations[-1]
            status, plan = last["status"], last["plan"]
            raw_response, alloy_logs = last["raw_response"], last["alloy_output"]
        print(f"      [resume] continuing after {len(iterations)} saved iterations", flush=True)
    code = compare_path.read_text(encoding="utf-8")
    pipeline.save_file(pipeline.replace_generated_plan(code, plan or "pred GeneratedPlan {}"),
                       str(compare_path))

    def finish(reason: str) -> dict[str, Any]:
        result = {"iterations": iterations, "final_status": status or "CAP_EXCEEDED",
                  "stage_counts": counters, "stopped_reason": reason}
        if checkpoint:
            write_json(checkpoint, result)
        return result

    while True:
        if status == "SAFE" or (stage == "syntax" and status in COMPILED_STATUSES):
            return finish("stage succeeded")
        if stage == "syntax" and status not in SYNTAX_STATUSES:
            return finish("syntax stage ended without a compiled result")
        kind = next_plan_call(status, counters, args)
        if kind is None:
            return finish(f"{status or 'initial'} stopped or cap exhausted")
        print(f"      [plan] iteration {len(iterations) + 1}: {kind}", flush=True)

        if kind == "initial":
            raw_response = pipeline.generate_plan(
                user_prompt, compare_path=str(compare_path), formal_query=formal_query)
        elif kind == "syntax_repair":
            code = pipeline.verifier_source(str(compare_path))
            raw_response = pipeline.call_claude(f"""
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
""", temperature=args.stage_temperature)
        else:
            code = pipeline.verifier_source(str(compare_path))
            raw_response = pipeline.call_claude(f"""
You are repairing an Alloy plan.

{pipeline.COUNTEREXAMPLE_GOAL}

TASK:
{user_prompt}
{pipeline.formal_query_section(formal_query)}
RULES:
{pipeline.output_contract(None)}
- Only use variables, signatures, and fields already defined in the file below.
- Do NOT invent new names.

Reference code:
{code}

Current plan:
{plan}

Verifier result:
{pipeline.counterexample_feedback(alloy_logs)}
""", temperature=args.stage_temperature)

        new_plan = pipeline.extract_generated_plan(raw_response or "")
        if not new_plan:
            status = "EMPTY_RESPONSE" if not (raw_response or "").strip() else "SYNTAX_ERROR"
            plan = ""
            alloy_logs = ("The LLM returned no text." if status == "EMPTY_RESPONSE"
                          else "Could not extract pred GeneratedPlan from LLM response.")
            iterations.append({
                "iter": len(iterations) + 1,
                "kind": kind,
                "status": status,
                "plan": "",
                "raw_response": raw_response or "",
                "alloy_output": alloy_logs,
                "ran_alloy": False,
            })
            if checkpoint:
                write_json(checkpoint, {"iterations": iterations, "stage_counts": counters})
            continue

        plan = new_plan
        code = compare_path.read_text(encoding="utf-8")
        pipeline.save_file(
            pipeline.replace_generated_plan(code, plan), str(compare_path))
        success, alloy_logs, run_status = pipeline.run_alloy(
            str(compare_path), syntax_only=stage == "syntax")
        status = pipeline.interpret_status(alloy_logs)
        if not success:
            status = run_status
        print(f"      [plan] verdict: {status}", flush=True)

        iterations.append({
            "iter": len(iterations) + 1,
            "kind": kind,
            "status": status,
            "plan": plan,
            "raw_response": raw_response or "",
            "alloy_output": alloy_logs,
            "ran_alloy": status != "INVALID_PLAN",
        })
        if checkpoint:
            write_json(checkpoint, {"iterations": iterations, "stage_counts": counters})


def branch_stage_samples(run_dir: Path, compare_path: Path, trace: dict[str, Any],
                         prompt: dict[str, Any], formal_query: dict[str, Any],
                         args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    syntax_failure = first_iteration(trace, SYNTAX_STATUSES)
    logic_failure = first_iteration(trace, LOGIC_STATUSES)
    syntax_samples: list[dict[str, Any]] = []
    logic_samples: list[dict[str, Any]] = []

    for stage, failure, samples in (("syntax", syntax_failure, syntax_samples),
                                     ("logic", logic_failure, logic_samples)):
        if not failure:
            continue
        stage_dir = run_dir / f"{stage}_samples"
        stage_dir.mkdir(exist_ok=True)
        for module in pipeline.opened_modules(str(compare_path)):
            shutil.copyfile(module, stage_dir / Path(module).name)
        write_json(stage_dir / "failure.json", failure)
        for i in range(1, args.stage_samples + 1):
            print(f"    [{stage} repair] independent attempt {i}/{args.stage_samples}", flush=True)
            sample_path = stage_dir / f"sample_{i}.als"
            shutil.copyfile(compare_path, sample_path)
            # Every branch resets to the same failure; no repair history is shared.
            result = run_with_stage_caps(
                prompt["prompt"], sample_path, formal_query.get("rule", ""), args,
                failure=failure, stage=stage, checkpoint=sample_path.with_suffix(".json"))
            result["success"] = (result["final_status"] in COMPILED_STATUSES
                                 if stage == "syntax" else result["final_status"] == "SAFE")
            write_json(sample_path.with_suffix(".json"), result)
            samples.append(result)

    return syntax_samples, logic_samples


def run_sample(prompt: dict[str, Any], rep: int, args: argparse.Namespace) -> dict[str, Any]:
    pid = prompt["id"]
    run_dir = args.out_dir / "runs" / f"prompt_{pid}" / f"rep_{rep}"
    query_dir = run_dir / "query"
    run_dir.mkdir(parents=True, exist_ok=True)
    record_path = run_dir / "record.json"
    if args.resume and record_path.exists():
        cached = read_json(record_path)
        if cached.get("stages_complete", True):
            print(f"  [resume] reusing prompt {pid}, run {rep}", flush=True)
            return cached

    print(f"  [prompt {pid:>2}, rep {rep}] query roundtrip", flush=True)
    situation = prompt.get("situation") or swimming.situation_of(prompt["prompt"])
    formal_query = (pipeline.previous_formalization(situation, swimming.TRUTH_FILE, str(query_dir))
                    if args.resume else "none")
    if formal_query == "none":
        formal_query = pipeline.formalize_query(
            situation, swimming.TRUTH_FILE, str(query_dir), attempts=args.roundtrip_cap)
    else:
        print("    [resume] reusing saved query result", flush=True)
    release = read_json(query_dir / "query_release.json")

    record: dict[str, Any] = {
        "rep": rep,
        "prompt_id": pid,
        "prompt": prompt,
        "formal_query": formal_query,
        "category": prompt.get("category", "uncategorised"),
        "query_released": bool(formal_query),
        "query_release_attempt": release.get("released_attempt"),
        "query_attempts": release.get("attempts", []),
        "plan_status": "UNVERIFIED_QUERY",
        "plan_iterations": [],
        "syntax_samples": [],
        "logic_samples": [],
        "full_success": False,
    }
    if not formal_query:
        record["stages_complete"] = True
        write_json(run_dir / "record.json", record)
        return record

    compare_path = run_dir / "swimming_compare.als"
    pipeline.build_compare_file(
        truth_path=swimming.TRUTH_FILE,
        out_path=str(compare_path),
        scope=args.scope,
        extension_lines=formal_query.get("extension") or None,
        formal_query=formal_query.get("rule"),
    )

    print(f"  [prompt {pid:>2}, rep {rep}] full plan loop", flush=True)
    trace = run_with_stage_caps(
        prompt["prompt"], compare_path, formal_query.get("rule", ""), args,
        checkpoint=run_dir / "plan_trace.json")
    record.update({
        "plan_status": trace.get("final_status"),
        "plan_stage_counts": trace.get("stage_counts", {}),
        "plan_stopped_reason": trace.get("stopped_reason", ""),
        "plan_iterations": trace.get("iterations", []),
        "full_success": trace.get("final_status") == "SAFE",
        "stages_complete": False,
    })
    write_json(record_path, record)
    syntax_samples, logic_samples = branch_stage_samples(
        run_dir, compare_path, trace, prompt, formal_query, args)
    record.update({"syntax_samples": syntax_samples, "logic_samples": logic_samples,
                   "stages_complete": True})
    write_json(run_dir / "record.json", record)
    return record


def make_payload(args: argparse.Namespace, per_prompt: dict[str, Any]) -> dict[str, Any]:
    return {
        "config": {
            "definition": "Chen et al. pass@k over independent samples",
            "verification": "feasible, safe, query-preserving; specification calls prohibited",
            "provider": pipeline.LLM_PROVIDER,
            "plan_model": pipeline.CLAUDE_MODEL,
            "roundtrip_model": pipeline.CLAUDE_MODEL,
            "stage_unit": "independent capped repair loop from a fixed captured failure",
            "stage_aggregation": "mean pass@k over captured failures per prompt; conditional on stage entry",
            "reps": args.reps,
            "stage_samples": args.stage_samples,
            "pass_kmax": args.pass_kmax,
            "roundtrip_cap": args.roundtrip_cap,
            "initial_cap": args.initial_cap,
            "syntax_cap": args.syntax_cap,
            "logic_cap": args.logic_cap,
            "stage_temperature": args.stage_temperature,
            "plan_max_tokens": pipeline.DEFAULT_MAX_TOKENS,
            "scope": args.scope,
            "n_prompts": len(per_prompt),
        },
        "per_prompt": per_prompt,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


def run_experiment(prompts: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.out_dir / "experiment_config.json"
    manifest = {"config": make_payload(args, {})["config"], "prompts": prompts,
                "protocol_sha256": hashlib.sha256(Path(swimming.TRUTH_FILE).read_bytes()).hexdigest()}
    manifest["config"].pop("n_prompts")
    if args.resume and manifest_path.exists() and read_json(manifest_path) != manifest:
        raise ValueError("Resume settings, prompts, or protocol differ from the saved experiment")
    if args.resume and not manifest_path.exists():
        print("[resume] legacy run has no configuration manifest; using the supplied settings.", flush=True)
    write_json(manifest_path, manifest)
    per_prompt = {
        str(prompt["id"]): {"id": prompt["id"],
                            "prompt": prompt,
                            "category": prompt.get("category", "uncategorised"),
                            "runs": []}
        for prompt in prompts
    }
    for rep in range(1, args.reps + 1):
        print(f"\n========== independent pipeline run {rep}/{args.reps} ==========", flush=True)
        for prompt in prompts:
            record = run_sample(prompt, rep, args)
            per_prompt[str(prompt["id"])]["runs"].append(record)
            write_json(args.out_dir / "stage_passk_log.json", make_payload(args, per_prompt))
            require_valid_infrastructure(record)
    return make_payload(args, per_prompt)


def require_valid_infrastructure(run: dict[str, Any]) -> None:
    failed = run.get("plan_status") == "ERROR"
    failed = failed or any(sample.get("final_status") == "ERROR"
                           for key in ("syntax_samples", "logic_samples")
                           for sample in run.get(key, []))
    failed = failed or any(attempt.get("reason", "").startswith("NLI unavailable:")
                           for attempt in run.get("query_attempts", []))
    if failed:
        raise ValueError(
            f"Infrastructure error in prompt {run.get('prompt_id', '?')}, "
            f"run {run.get('rep', '?')}; saved data is preserved, but pass@k "
            "cannot be computed until these samples are rerun with working dependencies.")


def chen_curve(successes: list[bool], k_values: list[int]) -> list[float | None]:
    n = len(successes)
    c = sum(1 for success in successes if success)
    return [pass_at_k(n, c, k) for k in k_values]


def average_curves(curves: list[list[float | None]], k_values: list[int]) -> list[float | None]:
    result = []
    for i, _ in enumerate(k_values):
        values = [curve[i] for curve in curves if curve[i] is not None]
        result.append(sum(values) / len(values) if values else None)
    return result


def compute_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = payload["config"]
    k_full = list(range(1, min(cfg["pass_kmax"], cfg["reps"]) + 1))
    k_stage = list(range(1, min(cfg["pass_kmax"], cfg["stage_samples"]) + 1))
    metrics = {
        "roundtrip": {"k_values": k_full, "per_prompt": {}},
        "syntax": {"k_values": k_stage, "per_prompt": {}},
        "logic": {"k_values": k_stage, "per_prompt": {}},
        "full_pipeline": {"k_values": k_full, "per_prompt": {}, "average": []},
    }

    for pid, data in payload["per_prompt"].items():
        runs = data["runs"]
        for run in runs:
            require_valid_infrastructure(run)
        prompt_info = {"id": data["id"], "category": data["category"]}

        roundtrip_curve = chen_curve([bool(run["query_released"]) for run in runs], k_full)
        full_curve = chen_curve([bool(run["full_success"]) for run in runs], k_full)
        metrics["roundtrip"]["per_prompt"][pid] = {
            **prompt_info, "eligible": len(runs), "rates": roundtrip_curve,
            "successes": sum(bool(run["query_released"]) for run in runs)}
        metrics["full_pipeline"]["per_prompt"][pid] = {
            **prompt_info, "eligible": len(runs), "rates": full_curve,
            "successes": sum(1 for run in runs if run["full_success"])}

        for stage in ("syntax", "logic"):
            sample_key = f"{stage}_samples"
            case_curves = [
                chen_curve([bool(sample["success"]) for sample in run.get(sample_key, [])], k_stage)
                for run in runs if run.get(sample_key)
            ]
            metrics[stage]["per_prompt"][pid] = {
                **prompt_info,
                "eligible": len(case_curves),
                "rates": average_curves(case_curves, k_stage) if case_curves
                else [None for _ in k_stage],
                "cases": [{"run": run["rep"], "n": len(run[sample_key]),
                           "c": sum(bool(sample["success"]) for sample in run[sample_key])}
                          for run in runs if run.get(sample_key)],
            }

    full_curves = [item["rates"] for item in metrics["full_pipeline"]["per_prompt"].values()]
    # A dataset average is undefined when any prompt has fewer than k runs.
    metrics["full_pipeline"]["average"] = [
        sum(curve[i] for curve in full_curves) / len(full_curves)
        if full_curves and all(curve[i] is not None for curve in full_curves) else None
        for i in range(len(k_full))
    ]
    metrics["stage_unit"] = cfg.get("stage_unit", "single-call repair (legacy log)")
    metrics["stage_aggregation"] = cfg.get("stage_aggregation", "mean over captured failures")
    return metrics


def plot_lines(metric: dict[str, Any], title: str, ylabel: str, path: Path,
               *, average_only: bool = False) -> None:
    cache = path.parent / ".matplotlib"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    k_values = metric["k_values"]
    if average_only:
        series = {"average": {"rates": metric["average"], "eligible": 1}}
    else:
        series = dict(sorted(metric["per_prompt"].items(), key=lambda item: int(item[0])))

    colors = plt.cm.tab20(np.linspace(0, 1, max(len(series), 1)))
    for (label, data), color in zip(series.items(), colors):
        y = [np.nan if value is None else 100 * value for value in data["rates"]]
        suffix = " (n/a)" if data.get("eligible") == 0 else ""
        ax.plot(k_values, y, marker="o", linewidth=1.5, color=color,
                label=f"#{label}{suffix}" if label != "average" else "average")

    ax.set_title(title)
    ax.set_xlabel("k")
    ax.set_ylabel(ylabel)
    ax.set_xticks(k_values)
    ax.set_ylim(-3, 103)
    ax.grid(axis="y", linestyle=":", alpha=0.45)
    ax.legend(ncol=2, fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=220)
    fig.savefig(path.with_suffix(".pdf"))
    plt.close(fig)
    print(f"saved {path}")


def plot_all(metrics: dict[str, Any], out_dir: Path) -> None:
    repair_unit = "Loop" if metrics["stage_unit"].startswith("independent capped") else "Single-Call"
    charts = [
        ("roundtrip", "Roundtrip Loop pass@k by Prompt",
         "released sample pass@k (%)", "roundtrip_passk_by_prompt.png"),
        ("syntax", f"Syntax Repair {repair_unit} pass@k by Prompt (Conditional)",
         "compilation pass@k (%)", "syntax_repair_passk_by_prompt.png"),
        ("logic", f"Logic Repair {repair_unit} pass@k by Prompt (Conditional)",
         "verified-safe pass@k (%)", "logic_repair_passk_by_prompt.png"),
        ("full_pipeline", "Full Pipeline pass@k by Prompt",
         "complete sample pass@k (%)", "full_pipeline_passk_by_prompt.png"),
    ]
    for key, title, ylabel, filename in charts:
        plot_lines(metrics[key], title, ylabel, out_dir / filename)
    plot_lines(metrics["full_pipeline"], "Full Pipeline Average pass@k",
               "mean complete-sample pass@k across prompts (%)",
               out_dir / "full_pipeline_passk_average.png", average_only=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Chen-style pass@k charts from independent runs per query.",
        epilog="Each pipeline run starts fresh, generates one initial plan, and uses "
               "the fixed repair limits below. k counts independent runs, not repair calls.")
    parser.add_argument("--prompts", type=Path, default=Path(swimming.PROMPTS_FILE))
    parser.add_argument("--prompt-ids", type=int, nargs="+",
                        help="run only these usable prompt IDs (default: all usable prompts)")
    parser.add_argument("--out-dir", type=Path,
                        help="output folder (default: a new timestamped folder under results/stage_passk)")
    parser.add_argument("--log", type=Path, help="existing stage_passk_log.json")
    parser.add_argument("--plot-only", action="store_true")
    parser.add_argument("--resume", action="store_true",
                        help="continue saved runs in --out-dir, preserving completed loops")
    parser.add_argument("--pass-at-k", type=int, default=5,
                        help="collect k independent pipeline runs per query and k independent "
                             "capped repair loops per captured failure; plot pass@1 through "
                             "pass@k (default: 5)")
    parser.add_argument("--roundtrip-attempt-cap", "--roundtrip-cap", dest="roundtrip_cap", type=int, default=5,
                        help="maximum formalization attempts within each pipeline run")
    parser.add_argument("--syntax-repair-cap", "--syntax-cap", dest="syntax_cap", type=int, default=5,
                        help="maximum syntax-repair calls within each pipeline run")
    parser.add_argument("--logic-repair-cap", "--logic-cap", dest="logic_cap", type=int, default=5,
                        help="maximum Alloy logic-repair calls within each pipeline run")
    parser.set_defaults(initial_cap=1)
    parser.add_argument("--repair-temperature", "--stage-temperature", dest="stage_temperature",
                        type=float, default=0.7,
                        help="sampling temperature for all plan repair calls")
    parser.add_argument("--scope", default=swimming.ALLOY_SCOPE_DEFAULT)
    args = parser.parse_args(argv)
    if args.pass_at_k < 1:
        parser.error("--pass-at-k must be at least 1")
    if args.roundtrip_cap < 1 or args.syntax_cap < 0 or args.logic_cap < 0:
        parser.error("roundtrip cap must be positive; repair caps must be nonnegative")
    if args.plot_only and not args.log:
        parser.error("--plot-only requires --log pointing to the saved stage_passk_log.json")
    if args.log and not args.plot_only:
        parser.error("--log is for --plot-only; use --out-dir for a new evaluation")
    if args.resume and (args.plot_only or not args.out_dir or not args.out_dir.exists()):
        parser.error("--resume requires an existing --out-dir and cannot be combined with --plot-only")
    # Keep the saved-data schema compatible with existing plot-only logs.
    args.reps = args.pass_at_k
    args.stage_samples = args.pass_at_k
    args.pass_kmax = args.pass_at_k
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.out_dir = args.out_dir or (args.log.parent if args.plot_only else
        DEFAULT_OUT_DIR / datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ"))
    log_path = args.log or args.out_dir / "stage_passk_log.json"

    if args.plot_only:
        if not log_path.exists():
            print(f"log file {log_path} not found", file=sys.stderr)
            return 1
        payload = read_json(log_path)
    else:
        if log_path.exists() and not args.resume:
            print(f"refusing to overwrite saved evaluation: {log_path}", file=sys.stderr)
            return 2
        prompts = load_prompts(args.prompts, args.prompt_ids)
        issues = swimming.preflight(dry_run=False)
        if issues:
            print("preflight failed:", file=sys.stderr)
            for issue in issues:
                print(f"- {issue}", file=sys.stderr)
            return 2
        print(f"Saving all evaluation data to {args.out_dir}", flush=True)
        payload = run_experiment(prompts, args)
        write_json(log_path, payload)

    metrics = compute_metrics(payload)
    write_json(args.out_dir / "stage_passk_metrics.json", metrics)
    plot_all(metrics, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
