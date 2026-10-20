"""Full-pipeline Chen pass@k, without independent repair-stage sampling.

Each sample starts from NL, formalizes the query, and generates/verifies a plan
with capped internal repair loops. Shared loop code keeps verification identical
to stage_passk_evaluator; no stage-specific branches are collected.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import stage_passk_evaluator as shared


pipeline = shared.pipeline
swimming = shared.swimming
DEFAULT_OUT_DIR = shared.DEFAULT_OUT_DIR.parent / "full_pipeline_passk"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--prompts", type=Path, default=Path(swimming.PROMPTS_FILE))
    parser.add_argument("--prompt-ids", type=int, nargs="+", help="default: all usable prompts")
    parser.add_argument("--pass-at-k", type=int, default=5,
                        help="collect k independent full-pipeline samples per prompt (default: 5)")
    parser.add_argument("--roundtrip-attempt-cap", type=int, default=5)
    parser.add_argument("--syntax-repair-cap", type=int, default=5)
    parser.add_argument("--logic-repair-cap", type=int, default=5)
    parser.add_argument("--alloy-timeout", type=int, default=pipeline.DEFAULT_ALLOY_TIMEOUT,
                        help="seconds per plan-verification invocation (default: 600)")
    parser.add_argument("--repair-temperature", type=float, default=0.7)
    parser.add_argument("--scope", default=swimming.ALLOY_SCOPE_DEFAULT)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--plot-only", action="store_true")
    parser.add_argument("--log", type=Path, help="saved full_pipeline_passk_log.json for --plot-only")
    args = parser.parse_args(argv)
    if args.pass_at_k < 1 or args.alloy_timeout < 1 or args.roundtrip_attempt_cap < 1:
        parser.error("pass-at-k, Alloy timeout, and roundtrip cap must be positive")
    if args.syntax_repair_cap < 0 or args.logic_repair_cap < 0:
        parser.error("repair caps must be nonnegative")
    if args.plot_only != bool(args.log):
        parser.error("--plot-only and --log must be provided together")
    if args.resume and (args.plot_only or not args.out_dir or not args.out_dir.is_dir()):
        parser.error("--resume requires an existing --out-dir and cannot be used with --plot-only")
    args.reps = args.pass_kmax = args.pass_at_k
    args.initial_cap = 1
    args.roundtrip_cap = args.roundtrip_attempt_cap
    args.syntax_cap = args.syntax_repair_cap
    args.logic_cap = args.logic_repair_cap
    args.stage_temperature = args.repair_temperature
    return args


def make_payload(args: argparse.Namespace, per_prompt: dict[str, Any]) -> dict[str, Any]:
    return {
        "config": {
            "evaluation_mode": "full_pipeline_only",
            "query_release_policy": pipeline.QUERY_RELEASE_POLICY,
            "definition": "Chen et al. pass@k over independent complete pipeline samples",
            "verification": "feasible, safe, query-preserving; specification calls prohibited",
            "provider": pipeline.LLM_PROVIDER,
            "plan_model": pipeline.CLAUDE_MODEL,
            "roundtrip_model": pipeline.CLAUDE_MODEL,
            "reps": args.reps,
            "pass_kmax": args.pass_kmax,
            "roundtrip_cap": args.roundtrip_cap,
            "initial_cap": 1,
            "syntax_cap": args.syntax_cap,
            "logic_cap": args.logic_cap,
            "stage_temperature": args.stage_temperature,
            "alloy_timeout_seconds": args.alloy_timeout,
            "plan_max_tokens": pipeline.DEFAULT_MAX_TOKENS,
            "scope": args.scope,
            "n_prompts": len(per_prompt),
        },
        "per_prompt": per_prompt,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


def run_sample(prompt: dict[str, Any], rep: int, args: argparse.Namespace) -> dict[str, Any]:
    pid = prompt["id"]
    run_dir = args.out_dir / "runs" / f"prompt_{pid}" / f"rep_{rep}"
    run_dir.mkdir(parents=True, exist_ok=True)
    record_path = run_dir / "record.json"
    if args.resume and record_path.exists():
        cached = shared.read_json(record_path)
        if cached.get("complete"):
            print(f"  [resume] reusing prompt {pid}, run {rep}", flush=True)
            return cached

    print(f"  [prompt {pid:>2}, rep {rep}] query roundtrip", flush=True)
    print("[FULL USER PROMPT]\n" + prompt["prompt"], flush=True)
    query_dir = run_dir / "query"
    situation = prompt.get("situation") or swimming.situation_of(prompt["prompt"])
    formal_query = (pipeline.previous_formalization(situation, swimming.TRUTH_FILE, str(query_dir))
                    if args.resume else "none")
    if formal_query == "none":
        formal_query = pipeline.formalize_query(
            situation, swimming.TRUTH_FILE, str(query_dir), attempts=args.roundtrip_cap,
            alloy_timeout=args.alloy_timeout)
    else:
        print("    [resume] reusing saved query result", flush=True)
    release = shared.read_json(query_dir / "query_release.json")
    record = {
        "rep": rep, "prompt_id": pid, "prompt": prompt,
        "category": prompt.get("category", "uncategorised"),
        "formal_query": formal_query,
        "query_released": bool(formal_query),
        "query_release_attempt": release.get("released_attempt"),
        "query_attempts": release.get("attempts", []),
        "plan_status": "UNVERIFIED_QUERY", "full_success": False,
        "plan_iterations": [], "complete": True,
    }
    if formal_query:
        compare_path = run_dir / "swimming_compare.als"
        pipeline.build_compare_file(
            truth_path=swimming.TRUTH_FILE, out_path=str(compare_path), scope=args.scope,
            extension_lines=formal_query.get("extension") or None,
            formal_query=formal_query.get("rule"))
        print(f"  [prompt {pid:>2}, rep {rep}] full plan loop", flush=True)
        trace = shared.run_with_stage_caps(
            prompt["prompt"], compare_path, formal_query.get("rule", ""), args,
            checkpoint=run_dir / "plan_trace.json")
        record.update({
            "plan_status": trace["final_status"],
            "full_success": trace["final_status"] == "SAFE",
            "plan_stage_counts": trace.get("stage_counts", {}),
            "plan_stopped_reason": trace.get("stopped_reason", ""),
            "plan_iterations": trace.get("iterations", []),
        })
    shared.write_json(record_path, record)
    return record


def run_experiment(prompts: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    manifest = {"config": make_payload(args, {})["config"], "prompts": prompts,
                "protocol_sha256": hashlib.sha256(Path(swimming.TRUTH_FILE).read_bytes()).hexdigest()}
    manifest_path = args.out_dir / "experiment_config.json"
    if args.resume and (not manifest_path.exists() or shared.read_json(manifest_path) != manifest):
        raise ValueError("Resume requires the same full-pipeline settings, prompts, and protocol")
    shared.write_json(manifest_path, manifest)
    per_prompt = {str(prompt["id"]): {
        "id": prompt["id"], "prompt": prompt,
        "category": prompt.get("category", "uncategorised"), "runs": []}
        for prompt in prompts}
    for rep in range(1, args.reps + 1):
        print(f"\n========== independent pipeline run {rep}/{args.reps} ==========", flush=True)
        for prompt in prompts:
            record = run_sample(prompt, rep, args)
            per_prompt[str(prompt["id"])]["runs"].append(record)
            shared.write_json(args.out_dir / "full_pipeline_passk_log.json",
                              make_payload(args, per_prompt))
            shared.require_valid_infrastructure(record)
    return make_payload(args, per_prompt)


def compute_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    if payload["config"].get("evaluation_mode") != "full_pipeline_only":
        raise ValueError("Expected a full-pipeline-only evaluation log")
    cfg = payload["config"]
    k_values = list(range(1, min(cfg["pass_kmax"], cfg["reps"]) + 1))
    metric = {"k_values": k_values, "per_prompt": {}, "average": []}
    for pid, data in payload["per_prompt"].items():
        runs = data["runs"]
        for run in runs:
            shared.require_valid_infrastructure(run)
            if not run.get("complete"):
                raise ValueError(f"Incomplete record for prompt {pid}")
        successes = [bool(run["full_success"]) for run in runs]
        metric["per_prompt"][pid] = {
            "id": data["id"], "category": data["category"],
            "eligible": len(runs), "successes": sum(successes),
            "rates": shared.chen_curve(successes, k_values),
        }
    curves = [item["rates"] for item in metric["per_prompt"].values()]
    metric["average"] = [sum(curve[i] for curve in curves) / len(curves)
                         if curves and all(curve[i] is not None for curve in curves) else None
                         for i in range(len(k_values))]
    return {"full_pipeline": metric}


def plot_all(metrics: dict[str, Any], out_dir: Path) -> None:
    metric = metrics["full_pipeline"]
    shared.plot_lines(metric, "Full Pipeline pass@k by Prompt", "complete sample pass@k (%)",
                      out_dir / "full_pipeline_passk_by_prompt.png")
    shared.plot_lines(metric, "Full Pipeline Average pass@k", "mean complete-sample pass@k (%)",
                      out_dir / "full_pipeline_passk_average.png", average_only=True)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.out_dir = args.out_dir or (args.log.parent if args.plot_only else
        DEFAULT_OUT_DIR / datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ"))
    log_path = args.log or args.out_dir / "full_pipeline_passk_log.json"
    if args.plot_only:
        if not log_path.exists():
            print(f"log file {log_path} not found", file=sys.stderr)
            return 1
        payload = shared.read_json(log_path)
    else:
        if not args.resume and args.out_dir.exists() and any(args.out_dir.iterdir()):
            print(f"refusing to overwrite nonempty evaluation folder: {args.out_dir}", file=sys.stderr)
            return 2
        prompts = shared.load_prompts(args.prompts, args.prompt_ids)
        issues = swimming.preflight(dry_run=False)
        if issues:
            print("preflight failed:\n" + "\n".join(issues), file=sys.stderr)
            return 2
        print(f"Saving all evaluation data to {args.out_dir}", flush=True)
        payload = run_experiment(prompts, args)
        shared.write_json(log_path, payload)
    metrics = compute_metrics(payload)
    shared.write_json(args.out_dir / "full_pipeline_passk_metrics.json", metrics)
    plot_all(metrics, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
