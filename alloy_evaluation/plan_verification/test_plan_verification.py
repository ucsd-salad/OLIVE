"""Formal verification regressions; no LLM calls are made."""

import tempfile
import unittest
import httpx
from math import comb
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pipeline_generated as pipeline
import stage_passk_evaluator as evaluator


@unittest.skipUnless(Path(pipeline.JAR).exists(), "Set ALLOY_JAR to an Alloy distribution JAR")
class PlanVerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="olive-verification-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.truth = self.root / "protocol.als"
        self.truth.write_text(
            "abstract sig Bool {}\n"
            "one sig True, False extends Bool {}\n"
            "sig Patron { safe: one Bool }\n"
            "pred safe[p: Patron] {\n  p.safe = True\n}\n"
            "pred PatronSafety {\n  all p: Patron | safe[p]\n}\n"
            "pred Protocol {\n  PatronSafety\n}\n")

    def verify(self, plan, query="pred rule { some Patron }"):
        compare = self.root / "compare.als"
        pipeline.build_compare_file(truth_path=str(self.truth), out_path=str(compare),
                                    scope="for 3", formal_query=query)
        with patch.object(pipeline, "generate_plan", return_value=plan):
            trace = pipeline.run_with_trace("test", compare_path=str(compare),
                                            formal_query=query, max_iters=1, verbose=False)
        return trace["final_status"]

    def test_empty_plan_is_unsafe(self):
        self.assertEqual(self.verify("pred GeneratedPlan {}"), "UNSAFE")

    def test_contradictory_plan_is_impossible(self):
        self.assertEqual(self.verify("pred GeneratedPlan { some Patron and no Patron }"),
                         "IMPOSSIBLE_PLAN")

    def test_erasing_required_patron_is_impossible(self):
        self.assertEqual(self.verify("pred GeneratedPlan { no Patron }"), "IMPOSSIBLE_PLAN")

    def test_safe_but_query_ignoring_plan_is_rejected(self):
        self.assertEqual(self.verify("pred GeneratedPlan { all p: Patron | p.safe = True }"),
                         "QUERY_MISMATCH")

    def test_short_concrete_safe_plan_is_accepted(self):
        self.assertEqual(self.verify(
            "pred GeneratedPlan { some Patron and all p: Patron | p.safe = True }"), "SAFE")

    def test_shared_integer_arithmetic_is_not_a_specification_call(self):
        self.truth.write_text(
            "open util/integer\n"
            "sig Patron { age: one Int }\n"
            "pred ageSafe[p: Patron] {\n  plus[p.age, 0] = 1\n}\n"
            "pred PatronSafety {\n  all p: Patron | ageSafe[p]\n}\n"
            "pred Protocol {\n  PatronSafety\n}\n")
        self.assertEqual(self.verify(
            "pred GeneratedPlan { some Patron and all p: Patron | plus[p.age, 0] = 1 }"),
            "SAFE")
        self.assertEqual(self.verify(
            "pred GeneratedPlan { some Patron and all p: Patron | ageSafe[p] }"),
            "INVALID_PLAN")

    def test_safety_specification_and_helpers_cannot_be_used_as_plans(self):
        for body in ("Protocol", "Protocol and no Patron", "PatronSafety",
                     "some p: Patron | safe[p]"):
            with self.subTest(body=body):
                self.assertEqual(self.verify("pred GeneratedPlan { " + body + " }"),
                                 "INVALID_PLAN")

    def test_syntax_metric_checks_compilation_without_accepting_plan_as_safe(self):
        compare = self.root / "compare.als"
        pipeline.build_compare_file(truth_path=str(self.truth), out_path=str(compare),
                                    scope="for 3", formal_query="pred rule { some Patron }")
        args = evaluator.parse_args(["--syntax-repair-cap", "1"])
        with patch.object(pipeline, "call_claude", return_value="pred GeneratedPlan { Protocol }"):
            trace = evaluator.run_with_stage_caps(
                "test", compare, "pred rule { some Patron }", args,
                failure={"status": "SYNTAX_ERROR"}, stage="syntax")
        self.assertIn(trace["final_status"], evaluator.COMPILED_STATUSES)
        self.assertTrue(trace["iterations"][0]["ran_alloy"])
        self.assertEqual(pipeline.run_alloy(str(compare))[2], "INVALID_PLAN")


class EvaluationTests(unittest.TestCase):
    def test_prompt_selection(self):
        args = evaluator.parse_args(["--prompt-ids", "3"])
        prompts = evaluator.load_prompts(args.prompts, args.prompt_ids)
        self.assertEqual([prompt["id"] for prompt in prompts], [3])
        self.assertGreater(len(evaluator.load_prompts(args.prompts)), 1)
        with self.assertRaisesRegex(SystemExit, "unknown prompt IDs"):
            evaluator.load_prompts(args.prompts, [999])

    def test_unusable_prompts_are_excluded_and_cannot_be_selected(self):
        path = evaluator.parse_args([]).prompts
        self.assertEqual([prompt["id"] for prompt in evaluator.load_prompts(path)],
                         [3, 4, 5, 6, 7, 8, 9])
        for pid in (1, 2, 10):
            with self.subTest(pid=pid), self.assertRaisesRegex(SystemExit, "unusable prompt IDs"):
                evaluator.load_prompts(path, [pid])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="olive-evaluation-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.compare = self.root / "compare.als"
        self.compare.write_text("open model\npred GeneratedPlan { final_plan }\n")
        (self.root / "model.als").write_text("sig Patron {}\n")
        self.args = evaluator.parse_args([
            "--pass-at-k", "2", "--syntax-repair-cap", "2", "--logic-repair-cap", "1"])

    def test_large_plan_request_uses_streaming_and_collects_final_text(self):
        client = MagicMock()
        stream = client.messages.stream.return_value.__enter__.return_value
        stream.get_final_message.return_value = SimpleNamespace(content=[
            SimpleNamespace(type="thinking"),
            SimpleNamespace(type="text", text="pred GeneratedPlan {}")])
        with patch.object(pipeline, "_get_anthropic_client", return_value=client):
            text = pipeline._call_claude_api("test prompt", 30000, 0.7)
        self.assertEqual(text, "pred GeneratedPlan {}")
        client.messages.create.assert_not_called()
        client.messages.stream.assert_called_once_with(
            model=pipeline.CLAUDE_MODEL, max_tokens=30000, temperature=0.7,
            messages=[{"role": "user", "content": "test prompt"}])
        stream.get_final_message.assert_called_once_with()

    def test_streaming_response_has_a_total_duration_limit(self):
        client = MagicMock()
        stream = client.messages.stream.return_value.__enter__.return_value
        stream.__iter__.return_value = iter([SimpleNamespace(type="message_start")])
        with patch.object(pipeline, "_get_anthropic_client", return_value=client), \
                patch.object(pipeline.time, "monotonic", side_effect=[0, 601]):
            with self.assertRaisesRegex(TimeoutError, "600-second"):
                pipeline._call_claude_api("test", 30000, 0.7)
        stream.get_final_message.assert_not_called()

    def test_stream_read_timeout_retries_the_same_request(self):
        with patch.object(pipeline, "_stream_claude_response",
                          side_effect=[httpx.ReadTimeout("stall"), "complete plan"]) as request, \
                patch.object(pipeline.time, "sleep"):
            self.assertEqual(pipeline._call_claude_api("prompt", 30000, 0.7), "complete plan")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0], request.call_args_list[1])

    def test_stream_retries_are_bounded(self):
        with patch.object(pipeline, "_stream_claude_response",
                          side_effect=httpx.ReadTimeout("stall")) as request, \
                patch.object(pipeline.time, "sleep"):
            with self.assertRaises(httpx.ReadTimeout):
                pipeline._call_claude_api("prompt", 30000, 0.7)
        self.assertEqual(request.call_count, 3)

    def test_alloy_timeout_returns_a_failed_verification(self):
        with patch.object(pipeline, "CLASS_FILE", str(self.compare)), \
                patch.object(pipeline, "JAVA_FILE", str(self.compare)), \
                patch.object(pipeline.subprocess, "run",
                             side_effect=pipeline.subprocess.TimeoutExpired("java", 120)):
            compiled, _, status = pipeline.run_alloy(str(self.compare))
        self.assertFalse(compiled)
        self.assertEqual(status, "TIMEOUT")

    def test_estimator_matches_combinatorial_definition(self):
        for n in range(1, 10):
            for c in range(n + 1):
                for k in range(1, n + 1):
                    self.assertAlmostEqual(evaluator.pass_at_k(n, c, k),
                                           1 - comb(n - c, k) / comb(n, k))
        self.assertIsNone(evaluator.pass_at_k(2, 1, 5))
        for c in (0, 1, 10, 100, 200):
            for k in (1, 5, 100):
                self.assertAlmostEqual(evaluator.pass_at_k(200, c, k),
                                       1 - comb(200 - c, k) / comb(200, k))

    def test_syntax_branches_restart_and_run_capped_loops(self):
        failure = {"status": "SYNTAX_ERROR", "plan": "pred GeneratedPlan { broken }",
                   "raw_response": "original failure", "alloy_output": "Syntax error"}
        unsafe = "COMMAND CounterExample: Instance found\nCOMMAND PlanPossible: Instance found"
        with patch.object(pipeline, "call_claude", side_effect=[
                "no predicate", "pred GeneratedPlan {}"] * 2) as llm, \
                patch.object(pipeline, "run_alloy", return_value=(True, unsafe, "UNSAFE")):
            samples, logic = evaluator.branch_stage_samples(
                self.root, self.compare, {"iterations": [failure]},
                {"prompt": "test"}, {}, self.args)
        self.assertEqual(logic, [])
        self.assertEqual(len(samples), 2)
        self.assertTrue(all(sample["success"] for sample in samples))
        self.assertTrue(all(len(sample["iterations"]) == 2 for sample in samples))
        for i in (0, 2):
            self.assertIn("original failure", llm.call_args_list[i].args[0])
            self.assertNotIn("final_plan", llm.call_args_list[i].args[0])
        self.assertTrue((self.root / "syntax_samples" / "model.als").exists())
        saved = evaluator.read_json(self.root / "syntax_samples" / "sample_1.json")
        self.assertEqual(saved["iterations"][0]["raw_response"], "no predicate")

    def test_logic_branches_can_repair_syntax_without_exceeding_logic_cap(self):
        failure = {"status": "UNSAFE", "plan": "pred GeneratedPlan {}",
                   "raw_response": "initial", "alloy_output": "failure"}
        safe = "COMMAND CounterExample: No instance found\nCOMMAND PlanPossible: Instance found"
        outcomes = [(False, "Syntax error", "SYNTAX_ERROR"), (True, safe, "SAFE")] * 2
        with patch.object(pipeline, "call_claude", return_value="pred GeneratedPlan {}"), \
                patch.object(pipeline, "run_alloy", side_effect=outcomes):
            _, samples = evaluator.branch_stage_samples(
                self.root, self.compare, {"iterations": [failure]},
                {"prompt": "test"}, {}, self.args)
        self.assertEqual(len(samples), 2)
        for sample in samples:
            self.assertTrue(sample["success"])
            self.assertEqual(sample["stage_counts"],
                             {"initial": 0, "syntax_repair": 1, "logic_repair": 1})

    def test_incomplete_verification_is_not_a_pass_or_repaired_as_logic(self):
        safe = "COMMAND CounterExample: No instance found\nCOMMAND PlanPossible: Instance found"
        with patch.object(pipeline, "generate_plan", return_value="pred GeneratedPlan {}"), \
                patch.object(pipeline, "run_alloy", return_value=(False, safe, "UNKNOWN")), \
                patch.object(pipeline, "call_claude") as repair:
            trace = evaluator.run_with_stage_caps("test", self.compare, "", self.args)
        self.assertEqual(trace["final_status"], "UNKNOWN")
        repair.assert_not_called()

    def test_zero_repair_budget_makes_no_llm_call(self):
        self.args.syntax_cap = 0
        failure = {"status": "SYNTAX_ERROR"}
        with patch.object(pipeline, "call_claude") as llm:
            trace = evaluator.run_with_stage_caps(
                "test", self.compare, "", self.args, failure=failure, stage="syntax")
        llm.assert_not_called()
        self.assertEqual(trace["iterations"], [])

    def test_resume_continues_remaining_budget_and_reuses_completed_loop(self):
        self.args.resume = True
        checkpoint = self.root / "checkpoint.json"
        prior = {"iter": 1, "kind": "syntax_repair", "status": "SYNTAX_ERROR",
                 "plan": "pred GeneratedPlan { broken }", "raw_response": "previous reply",
                 "alloy_output": "Syntax error", "ran_alloy": True}
        evaluator.write_json(checkpoint, {"iterations": [prior],
            "stage_counts": {"initial": 0, "syntax_repair": 1, "logic_repair": 0}})
        output = "COMMAND CounterExample: Instance found\nCOMMAND PlanPossible: Instance found"
        with patch.object(pipeline, "call_claude", return_value="pred GeneratedPlan {}") as llm, \
                patch.object(pipeline, "generate_plan") as initial, \
                patch.object(pipeline, "run_alloy", return_value=(True, output, "UNSAFE")):
            trace = evaluator.run_with_stage_caps(
                "test", self.compare, "", self.args, failure={"status": "SYNTAX_ERROR"},
                stage="syntax", checkpoint=checkpoint)
        initial.assert_not_called()
        llm.assert_called_once()
        self.assertIn("previous reply", llm.call_args.args[0])
        self.assertEqual(trace["stage_counts"]["syntax_repair"], 2)
        self.assertEqual(len(trace["iterations"]), 2)
        with patch.object(pipeline, "call_claude") as llm:
            cached = evaluator.run_with_stage_caps(
                "test", self.compare, "", self.args, failure={"status": "SYNTAX_ERROR"},
                stage="syntax", checkpoint=checkpoint)
        llm.assert_not_called()
        self.assertEqual(trace, cached)

    def test_resume_saved_query_and_full_trace_without_llm_calls(self):
        self.args.resume = True
        self.args.out_dir = self.root
        run_dir = self.root / "runs" / "prompt_1" / "rep_1"
        run_dir.mkdir(parents=True)
        trace = {"iterations": [], "final_status": "UNSAFE",
                 "stage_counts": {"initial": 1, "syntax_repair": 0, "logic_repair": 1}}
        evaluator.write_json(run_dir / "plan_trace.json", trace)
        query = {"rule": "pred rule { some Patron }", "extension": []}
        with patch.object(pipeline, "previous_formalization", return_value=query), \
                patch.object(pipeline, "formalize_query") as formalize, \
                patch.object(pipeline, "generate_plan") as generate, \
                patch.object(evaluator, "branch_stage_samples", return_value=([], [])):
            record = evaluator.run_sample({"id": 1, "prompt": "test", "situation": "test"},
                                           1, self.args)
        formalize.assert_not_called()
        generate.assert_not_called()
        self.assertEqual(record["plan_status"], "UNSAFE")
        self.assertTrue(record["stages_complete"])

    def test_stage_metrics_average_fixed_failure_cases_without_pooling(self):
        runs = [{"rep": i, "query_released": True, "full_success": i == 1,
                 "syntax_samples": [{"success": i == 1}] * 2, "logic_samples": []}
                for i in (1, 2)]
        payload = {"config": {"pass_kmax": 2, "reps": 2, "stage_samples": 2},
                   "per_prompt": {"1": {"id": 1, "category": "test", "runs": runs}}}
        metrics = evaluator.compute_metrics(payload)
        self.assertEqual(metrics["syntax"]["per_prompt"]["1"]["rates"], [0.5, 0.5])
        self.assertEqual(metrics["full_pipeline"]["average"], [0.5, 1.0])
        self.assertEqual(metrics["logic"]["per_prompt"]["1"]["rates"], [None, None])
        payload["per_prompt"]["2"] = {"id": 2, "category": "test", "runs": []}
        self.assertEqual(evaluator.compute_metrics(payload)["full_pipeline"]["average"],
                         [None, None])


if __name__ == "__main__":
    unittest.main()
