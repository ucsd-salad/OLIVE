"""Formal verification regressions; no LLM calls are made."""

import tempfile
import unittest
import os
import sys
import httpx
import json
from math import comb
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pipeline_generated as pipeline
import stage_passk_evaluator as evaluator
import pipeline as roundtrip
import full_pipeline_passk_evaluator as full_pipeline
from nli import compare as nli_compare


class QueryRoundtripTests(unittest.TestCase):
    def test_benchmark_questions_disclose_adaptations_and_preserve_eligibility(self):
        path = Path(__file__).with_name("swimming_prompts.json")
        dataset = json.loads(path.read_text())
        self.assertEqual(dataset["meta"]["prompt_revision"], "staff_safety_questions_v3")
        self.assertEqual([p["id"] for p in evaluator.load_prompts(path)], list(range(3, 10)))
        questions = set()
        for prompt in dataset["prompts"]:
            self.assertTrue(prompt["prompt"].startswith(prompt["situation"] + " "))
            question = prompt["prompt"][len(prompt["situation"]) + 1:]
            self.assertTrue(question.endswith("?"))
            self.assertTrue(any(role in question.lower() for role in
                                ("staff", "lifeguard", "pool operator")))
            questions.add(question)
            self.assertEqual(prompt["prompt"].count("?"), 1)
            self.assertNotIn("?", prompt["situation"])
            self.assertNotIn("generate a plan", prompt["prompt"].lower())
            self.assertTrue(prompt["source"]["adaptation_note"])
            self.assertTrue(prompt["source"]["verification_status"])
            self.assertTrue(prompt["source"]["original_excerpt"])
        self.assertEqual(len(questions), len(dataset["prompts"]))
        third = next(p for p in dataset["prompts"] if p["id"] == 3)
        self.assertNotIn("band assignment", third["prompt"])
        self.assertIn("One brother passed", third["situation"])
        self.assertNotIn("life jacket", third["situation"])
        self.assertIn("Last year", third["source"]["original_text"])
        self.assertEqual(third["source"]["original_question"], "What would you do differently?")

    def test_retry_receives_all_errors_and_previous_proposal(self):
        original = "An adult intends to visit a shelter."
        bad = {"bindings": [{"source_quote": original, "kind": "intention",
               "field": "", "explanation": "Missing destination mapping."}],
               "declarations": ["intendedShelter: Adult -> lone ShelterLocation -- destination"]}
        good = {"bindings": [{"source_quote": original, "kind": "intention",
                "field": "intendsShelterVisit", "explanation": "An intention, not current presence."}],
                "declarations": ["intendsShelterVisit: Adult -> lone Bool -- intends to visit a shelter"]}
        client = MagicMock()
        client.complete.side_effect = [json.dumps(bad), json.dumps(good)]
        with tempfile.TemporaryDirectory() as tmp:
            result = pipeline.prepare_query_vocabulary(
                client, roundtrip.Settings(model=pipeline.CLAUDE_MODEL), original,
                Path(__file__).with_name("safety_protocol.als"), Path(tmp))
        self.assertTrue(result["accepted"])
        retry = json.loads(client.complete.call_args_list[1].args[1])
        self.assertEqual(retry["previous_proposal"], bad)
        self.assertIn("Adult", retry["allowed_signatures"])
        self.assertNotIn("ShelterLocation", retry["allowed_signatures"])
        self.assertTrue(any("ShelterLocation" in e for e in retry["previous_errors"]))
        self.assertTrue(any("missing field" in e and original in e for e in retry["previous_errors"]))
        self.assertEqual(result["extension"], good["declarations"])

    def test_preparation_accepts_wrapped_json_but_not_truncated_json(self):
        report = {"bindings": [], "declarations": [], "note": "braces { in prose }"}
        encoded = json.dumps(report)
        for raw in (encoded, "```json\n" + encoded + "\n```",
                    "I mapped the vocabulary.\n```json\n" + encoded + "\n```"):
            self.assertEqual(pipeline.parse_vocabulary_preparation(raw), report)
        for raw in ("no object", encoded[:-1]):
            with self.assertRaises(ValueError):
                pipeline.parse_vocabulary_preparation(raw)

    def test_existing_vocabulary_and_multiple_target_relationships(self):
        protocol = Path(__file__).with_name("safety_protocol.als")
        original = "A patron wears a jacket."
        report = {"bindings": [{"source_quote": original, "kind": "current",
                  "field": "wearsUSCGLifeJacket", "explanation": "Current wearing."}],
                  "declarations": []}
        client = MagicMock()
        client.complete.return_value = json.dumps(report)
        with tempfile.TemporaryDirectory() as tmp:
            prepared = pipeline.prepare_query_vocabulary(
                client, roundtrip.Settings(model=pipeline.CLAUDE_MODEL), original, protocol, Path(tmp))
            self.assertTrue(prepared["accepted"])
            self.assertEqual(prepared["extension"], [])
        accepted, errors = pipeline.pm.check_extension_lines(
            ["parentsOf: Patron -> set Adult -- parent relationship, not designated supervision"],
            pipeline.pm.split_protocol(protocol.read_text())[0])
        self.assertEqual(errors, [])
        self.assertEqual(accepted[0][0], "parentsOf")

    def test_labels_and_paper_drift_measure(self):
        high = {"entailment": 0.9, "contradiction": 0.01}
        low = {"entailment": 0.1, "contradiction": 0.01}
        self.assertEqual(nli_compare.classify(high, low), "Weakened")
        self.assertEqual(nli_compare.classify(low, high), "Strengthened")
        self.assertEqual(nli_compare.DRIFT, {"Unrelated", "Contradiction"})

    def test_preparation_validates_evidence_and_declarations_before_freezing(self):
        original = "An adult intends to visit a zone."
        report = {"bindings": [{"source_quote": original, "kind": "intention",
                  "field": "intendedZone", "explanation": "Intention, not water entry."}],
                  "declarations": ["intendedZone: Adult -> lone WaterZone -- intended destination"]}
        protocol = Path(__file__).with_name("safety_protocol.als")
        client = MagicMock()
        client.complete.side_effect = ["not JSON", json.dumps(report)]
        with tempfile.TemporaryDirectory() as tmp:
            prepared = pipeline.prepare_query_vocabulary(
                client, roundtrip.Settings(model=pipeline.CLAUDE_MODEL), original, protocol, Path(tmp))
            self.assertTrue(prepared["accepted"])
            self.assertEqual(len(prepared["attempts"]), 2)
            self.assertEqual(prepared["extension"], report["declarations"])
            self.assertTrue((Path(tmp) / "vocabulary_preparation.json").exists())
        report["bindings"][0]["source_quote"] = "Invented source quote"
        client.complete.side_effect = None
        client.complete.return_value = json.dumps(report)
        with tempfile.TemporaryDirectory() as tmp:
            prepared = pipeline.prepare_query_vocabulary(
                client, roundtrip.Settings(model=pipeline.CLAUDE_MODEL), original, protocol, Path(tmp))
            self.assertFalse(prepared["accepted"])
            self.assertEqual(prepared["extension"], [])

    def test_preparation_rejects_facts_disguised_as_declarations(self):
        report = {"bindings": [{"source_quote": "Original", "kind": "current",
                  "field": "unsafeField", "explanation": "Invalid declaration."}],
                  "declarations": ["fact AlwaysSafe { Protocol }"]}
        client = MagicMock()
        client.complete.return_value = json.dumps(report)
        with tempfile.TemporaryDirectory() as tmp:
            prepared = pipeline.prepare_query_vocabulary(
                client, roundtrip.Settings(model=pipeline.CLAUDE_MODEL), "Original",
                Path(__file__).with_name("safety_protocol.als"), Path(tmp))
            self.assertFalse(prepared["accepted"])

    def test_single_roundtrip_release_requires_formal_agreement_and_nl_gate(self):
        def fake_run(original, vocabulary, stage, settings, client, **kwargs):
            stage.mkdir(parents=True, exist_ok=True)
            (stage / "x_prime.txt").write_text("Readback")
            (stage / "y_original.als").write_text("pred rule { some Patron }")
            evaluator.write_json(stage / "nli_result.json", {"available": True, "category": category})
            evaluator.write_json(stage / "roundtrip_result.json", {
                "equivalent": verdict, "nl_fidelity": {
                    "faithful": faithful, "status": "PASS" if faithful else "FAIL",
                    "reason": "checked against source"}})
            return verdict

        prepared = {"accepted": True, "extension": ["parentOf: Adult -> set Patron -- parent relationship"],
                    "bindings": [{"source_quote": "Original", "kind": "relationship",
                                  "field": "parentOf", "explanation": "Parenthood, not chaperoning."}]}
        for verdict, category, faithful in ((True, "Contradiction", False),
                                            (False, "Equivalent", True),
                                            (True, "Equivalent", True),
                                            (True, "Related", False)):
            with self.subTest(verdict=verdict, category=category), tempfile.TemporaryDirectory() as tmp:
                with patch.object(pipeline, "prepare_query_vocabulary", return_value=prepared) as prep, \
                        patch.object(roundtrip, "load_protocol_vocabulary", return_value=object()) as vocab, \
                        patch.object(roundtrip, "run", side_effect=fake_run) as run, \
                        patch.object(roundtrip, "compare_nli", return_value={
                            "category": category, "drift": category == "Contradiction" if category else None,
                            "forward": {"entailment": 0.1}}), \
                        patch.object(pipeline, "load_formal_query", return_value={"rule": "approved"}):
                    result = pipeline.formalize_query(
                        "Original", Path(__file__).with_name("safety_protocol.als"),
                        Path(tmp), client=SimpleNamespace(model=pipeline.CLAUDE_MODEL), attempts=5,
                        alloy_timeout=600)
                self.assertEqual(bool(result), verdict and faithful)
                prep.assert_called_once()
                run.assert_called_once()
                vocab.assert_called_once()
                self.assertEqual(vocab.call_args.args[1], tuple(prepared["extension"]))
                self.assertEqual(run.call_args.args[3].max_rounds, 4)
                self.assertEqual(run.call_args.args[3].alloy_timeout, 600)
                self.assertTrue(run.call_args.args[3].run_nli)
                self.assertTrue(run.call_args.args[3].nl_gate)
                self.assertIn("parentOf", run.call_args.kwargs["formalization_feedback"])
                saved = evaluator.read_json(Path(tmp) / "query_release.json")
                self.assertEqual(saved["released"], verdict and faithful)
                self.assertEqual(saved["query_release_policy"], pipeline.QUERY_RELEASE_POLICY)
                self.assertEqual(saved["attempts"][0]["nli"]["category"], category)

    def test_nl_gate_failure_enters_scoped_repair_and_respects_cap(self):
        vocabulary = roundtrip.Vocabulary(source="sig Patron {}", struct="")
        state = roundtrip.State("pred rule { some Patron }", "Readback", "pred rule { some Patron }", vocabulary)
        failure = {"available": True, "category": "Strengthened"}
        success = {"available": True, "category": "Equivalent"}
        for cap, reports, expected, repairs in ((0, [failure], False, 0),
                                               (1, [failure, success], True, 1),
                                               (1, [failure, failure], False, 1),
                                               (1, [{"available": False}], False, 0)):
            with self.subTest(cap=cap, expected=expected), tempfile.TemporaryDirectory() as tmp:
                with patch.object(roundtrip, "prepare_stage", return_value=[]), \
                        patch.object(roundtrip, "typecheck", return_value=(True, "")), \
                        patch.object(roundtrip, "formalize", return_value=state.original_rule), \
                        patch.object(roundtrip, "deformalize", return_value=state.reconstructed), \
                        patch.object(roundtrip, "check_equivalence", return_value=roundtrip.equivalence.Verdict(True, True, "equivalent")), \
                        patch.object(roundtrip, "compare_nli", side_effect=reports), \
                        patch.object(roundtrip, "diagnose", return_value=roundtrip.Diagnosis("S1")) as diagnosis, \
                        patch.object(roundtrip, "repair", return_value=state) as repair:
                    result = roundtrip.run("Original", vocabulary, Path(tmp),
                                           roundtrip.Settings(nl_gate=True, max_rounds=cap), MagicMock())
                self.assertEqual(result, expected)
                self.assertEqual(repair.call_count, repairs)
                diagnosis.assert_not_called()
                if repairs:
                    self.assertIsNone(repair.call_args.args[4])
                    self.assertEqual(repair.call_args.kwargs["nl_feedback"], failure)
                saved = evaluator.read_json(Path(tmp) / "roundtrip_result.json")
                self.assertTrue(saved["equivalent"])
                self.assertEqual(saved["released"], expected)
                if repairs:
                    history = evaluator.read_json(Path(tmp) / "roundtrip_repairs.json")
                    self.assertEqual(history[0]["kind"], "nli_retry")
                    self.assertNotIn("hint", history[0])

    def test_nli_retry_regenerates_all_stages_without_a_diagnostic_prompt(self):
        vocabulary = roundtrip.Vocabulary(source="sig Patron {}", struct="")
        state = roundtrip.State("Old predicate", "Old readback", "Old prime", vocabulary)
        semantic = {"available": True, "category": "Weakened", "forward": {"entailment": 0.9}}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(roundtrip, "formalize", side_effect=["New predicate", "New prime"]) as formalize, \
                    patch.object(roundtrip, "deformalize", return_value="New readback") as deformalize:
                result = roundtrip.repair(MagicMock(), roundtrip.Settings(), "Original scenario",
                                          state, None, Path(tmp), nl_feedback=semantic)
            self.assertEqual(result.original_rule, "New predicate")
            self.assertEqual(result.reconstructed, "New readback")
            self.assertEqual(result.prime_rule, "New prime")
            self.assertEqual(formalize.call_count, 2)
            self.assertEqual([call.kwargs["stage"] for call in formalize.call_args_list], ["S1", "S3"])
            deformalize.assert_called_once()
            feedback = formalize.call_args_list[0].kwargs["repair_prompt"]
            self.assertIn("Original scenario", feedback)
            self.assertIn("Old predicate", feedback)
            self.assertIn("Old readback", feedback)
            self.assertIn('"entailment": 0.9', feedback)
            self.assertIn("Do not equate parents with chaperones", feedback)
            self.assertNotIn("diagnosis:", feedback)

    def test_nli_gate_accepts_only_equivalent_and_fails_closed_when_unavailable(self):
        for category in ("Equivalent", "Strengthened", "Weakened", "Related", "Unrelated", "Contradiction"):
            result = roundtrip.nl_fidelity_result({"available": True, "category": category})
            self.assertEqual(result["faithful"], category == "Equivalent")
            self.assertEqual(result["status"], "PASS" if category == "Equivalent" else "FAIL")
        for semantic in ({}, {"available": False, "category": "Equivalent"},
                         {"available": True, "category": "NONE"}):
            self.assertEqual(roundtrip.nl_fidelity_result(semantic)["status"], "ERROR")

    def test_equivalence_timeout_never_triggers_translation_repair(self):
        vocabulary = roundtrip.Vocabulary(source="sig Patron {}", struct="")
        state = roundtrip.State("pred rule { some Patron }", "Readback", "pred rule { some Patron }", vocabulary)
        timeout = roundtrip.equivalence.Verdict(False, False, "Alloy timed out after 600s",
                                                failure_status="TIMEOUT")
        mismatch = roundtrip.equivalence.Verdict(True, False, "counterexample", {})
        for verdicts, repairs in (([timeout], 0), ([mismatch, timeout], 1)):
            with self.subTest(repairs=repairs), tempfile.TemporaryDirectory() as tmp:
                with patch.object(roundtrip, "prepare_stage", return_value=[]), \
                        patch.object(roundtrip, "typecheck", return_value=(True, "")), \
                        patch.object(roundtrip, "formalize", return_value=state.original_rule), \
                        patch.object(roundtrip, "deformalize", return_value=state.reconstructed), \
                        patch.object(roundtrip, "check_equivalence", side_effect=verdicts), \
                        patch.object(roundtrip, "compare_nli") as nli, \
                        patch.object(roundtrip, "diagnose", return_value=roundtrip.Diagnosis("S1")) as diagnosis, \
                        patch.object(roundtrip, "repair", return_value=state) as repair:
                    self.assertFalse(roundtrip.run("Original", vocabulary, Path(tmp),
                                                    roundtrip.Settings(nl_gate=True, max_rounds=4), MagicMock()))
                self.assertEqual(diagnosis.call_count, repairs)
                self.assertEqual(repair.call_count, repairs)
                nli.assert_not_called()
                saved = evaluator.read_json(Path(tmp) / "roundtrip_result.json")
                self.assertFalse(saved["decided"])
                self.assertEqual(saved["equivalence_status"], "TIMEOUT")

    def test_alloy_timeout_is_preserved_as_an_undecided_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(roundtrip.alloy, "execute", return_value=roundtrip.alloy.Result(
                    False, "Alloy timed out after 600s", timed_out=True)):
                verdict = roundtrip.equivalence.decide(Path(tmp) / "equivalence.als", "run {}", 600)
            self.assertFalse(verdict.decided)
            self.assertEqual(verdict.failure_status, "TIMEOUT")

    def test_predicate_validation_timeout_also_skips_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            vocabulary = roundtrip.Vocabulary(source="sig Patron {}", struct="")
            with patch.object(roundtrip, "prepare_stage", return_value=[]), \
                    patch.object(roundtrip, "typecheck", side_effect=[(True, ""), roundtrip.AlloyTimeout("Alloy timed out after 600s")]), \
                    patch.object(roundtrip, "diagnose_rejection") as diagnosis:
                client = MagicMock()
                client.complete.return_value = "pred rule { some Patron }"
                self.assertFalse(roundtrip.run("Original", vocabulary, Path(tmp),
                                                roundtrip.Settings(nl_gate=True), client))
            diagnosis.assert_not_called()
            self.assertEqual(client.complete.call_count, 1)
            self.assertEqual(evaluator.read_json(Path(tmp) / "roundtrip_result.json")["equivalence_status"], "TIMEOUT")

    def test_fidelity_infrastructure_error_is_not_counted_as_a_failed_sample(self):
        with self.assertRaises(ValueError):
            evaluator.require_valid_infrastructure({"query_attempts": [{
                "nl_fidelity": {"status": "ERROR"}}]})

    def test_preparation_failure_skips_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pipeline, "prepare_query_vocabulary", return_value={
                    "accepted": False, "extension": [], "bindings": []}), \
                    patch.object(roundtrip, "run") as run:
                result = pipeline.formalize_query(
                    "Original", Path(__file__).with_name("safety_protocol.als"),
                    Path(tmp), client=SimpleNamespace(model=pipeline.CLAUDE_MODEL))
            self.assertIsNone(result)
            run.assert_not_called()
            self.assertFalse(evaluator.read_json(Path(tmp) / "query_release.json")["released"])

    def test_legacy_query_release_is_not_reused(self):
        import hashlib
        protocol = Path(__file__).with_name("safety_protocol.als")
        with tempfile.TemporaryDirectory() as tmp:
            evaluator.write_json(Path(tmp) / "query_release.json", {
                "query": "Original", "released": True, "released_attempt": 1,
                "protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest()})
            self.assertEqual(pipeline.previous_formalization("Original", protocol, tmp), "none")


def fake_sdk(**constructors):
    exceptions = {name: type(name, (Exception,), {}) for name in (
        "RateLimitError", "APIConnectionError", "APITimeoutError",
        "InternalServerError", "APIStatusError")}
    return SimpleNamespace(**constructors, **exceptions)


class RoundtripProviderTests(unittest.TestCase):
    def test_claude_uses_anthropic_key_and_messages_api(self):
        client = MagicMock()
        client.messages.create.return_value = SimpleNamespace(content=[
            SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text="first"),
            SimpleNamespace(type="text", text="second")])
        constructor = MagicMock(return_value=client)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=True), \
                patch.dict(sys.modules, {"anthropic": fake_sdk(Anthropic=constructor)}):
            llm = roundtrip.LLM("claude-test")
            text = llm.complete("system instructions", "user input",
                                temperature=0.7, max_tokens=100)
        self.assertEqual(text, "first\nsecond")
        constructor.assert_called_once_with(api_key="test-key", timeout=180)
        client.messages.create.assert_called_once_with(
            model="claude-test", system="system instructions",
            messages=[{"role": "user", "content": "user input"}],
            temperature=0.7, max_tokens=100)

    def test_claude_missing_key_fails_before_client_creation(self):
        constructor = MagicMock()
        with patch.dict(os.environ, {}, clear=True), \
                patch.dict(sys.modules, {"anthropic": fake_sdk(Anthropic=constructor)}):
            with self.assertRaisesRegex(roundtrip.PipelineError, "ANTHROPIC_API_KEY"):
                roundtrip.LLM("claude-test")
        constructor.assert_not_called()

    def test_non_claude_models_and_mixed_judges_are_rejected(self):
        with self.assertRaisesRegex(roundtrip.PipelineError, "Claude"):
            roundtrip.Settings(model="deepseek-chat")
        with self.assertRaisesRegex(roundtrip.PipelineError, "same Claude model"):
            roundtrip.Settings(model="claude-test", judge_model="claude-other")

    def test_completion_cannot_switch_models(self):
        constructor = MagicMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=True), \
                patch.dict(sys.modules, {"anthropic": fake_sdk(Anthropic=constructor)}):
            llm = roundtrip.LLM("claude-test")
            with self.assertRaisesRegex(roundtrip.PipelineError, "same Claude model"):
                llm.complete("system", "user", temperature=0.7, max_tokens=100,
                             model="claude-other")
        constructor.return_value.messages.create.assert_not_called()


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
    def test_alloy_timeout_is_configurable_and_recorded(self):
        args = evaluator.parse_args([])
        self.assertEqual(args.alloy_timeout, 600)
        self.assertEqual(evaluator.make_payload(args, {})["config"]["alloy_timeout_seconds"], 600)
        args = evaluator.parse_args(["--alloy-timeout", "300"])
        self.assertEqual(args.alloy_timeout, 300)
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            evaluator.parse_args(["--alloy-timeout", "0"])

    def test_infrastructure_errors_are_not_scored_as_model_failures(self):
        for record in ({"plan_status": "ERROR"},
                       {"syntax_samples": [{"final_status": "ERROR"}]},
                       {"logic_samples": [{"final_status": "ERROR"}]},
                       {"query_attempts": [{"reason": "NLI unavailable: missing dependency"}]}):
            with self.subTest(record=record), self.assertRaisesRegex(ValueError, "Infrastructure error"):
                evaluator.require_valid_infrastructure(record)
        evaluator.require_valid_infrastructure({"plan_status": "UNSAFE"})
        evaluator.require_valid_infrastructure({"plan_status": "TIMEOUT"})

    def test_metrics_refuse_an_infrastructure_error_sample(self):
        payload = {"config": {"pass_kmax": 1, "reps": 1, "stage_samples": 1},
                   "per_prompt": {"3": {"id": 3, "category": "test", "runs": [
                       {"rep": 1, "plan_status": "ERROR", "query_released": True,
                        "full_success": False}]}}}
        with self.assertRaisesRegex(ValueError, "Infrastructure error"):
            evaluator.compute_metrics(payload)

    def test_java_compiler_targets_portable_bytecode(self):
        with patch.object(pipeline.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout="", stderr="")) as compile_call:
            self.assertEqual(pipeline.compile_alloy_runner(), "")
        self.assertEqual(compile_call.call_args.args[0][:3], ["javac", "--release", "17"])

    def test_newer_java_bytecode_is_recompiled_even_with_newer_timestamp(self):
        class_file = self.root / "runner.class"
        class_file.write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x45")
        with patch.object(pipeline, "CLASS_FILE", str(class_file)), \
                patch.object(pipeline, "JAVA_FILE", str(self.compare)), \
                patch.object(pipeline, "compile_alloy_runner", return_value="") as compile_call, \
                patch.object(pipeline.subprocess, "run", return_value=SimpleNamespace(
                    returncode=0, stdout="COMPILED: GeneratedPlan", stderr="")):
            _, _, status = pipeline.run_alloy(str(self.compare), syntax_only=True)
        self.assertEqual(status, "COMPILED")
        compile_call.assert_called_once_with()

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
                patch.object(pipeline, "compile_alloy_runner", return_value=""), \
                patch.object(pipeline.subprocess, "run",
                             side_effect=pipeline.subprocess.TimeoutExpired("java", 600)) as request:
            compiled, output, status = pipeline.run_alloy(str(self.compare))
        self.assertFalse(compiled)
        self.assertEqual(status, "TIMEOUT")
        self.assertEqual(request.call_args.kwargs["timeout"], 600)
        self.assertIn("600-second", output)

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


class FullPipelineEvaluationTests(unittest.TestCase):
    def test_full_pipeline_default_timeout_is_ten_minutes(self):
        args = full_pipeline.parse_args([])
        self.assertEqual(args.alloy_timeout, 600)
        self.assertEqual(full_pipeline.make_payload(args, {})["config"]["alloy_timeout_seconds"], 600)

    def test_full_pipeline_keeps_repairs_but_never_branches_stage_samples(self):
        with tempfile.TemporaryDirectory(prefix="olive-full-pipeline-") as directory:
            root = Path(directory)
            args = full_pipeline.parse_args(["--pass-at-k", "2", "--out-dir", str(root)])
            prompt = {"id": 3, "category": "test", "prompt": "test", "situation": "test"}
            unsafe = "COMMAND CounterExample: Instance found"
            safe = ("COMMAND CounterExample: No instance found\n"
                    "COMMAND PlanPossible: Instance found\nCOMMAND QueryViolation: No instance found")
            plan = "pred GeneratedPlan { some Patron }"
            with patch.object(pipeline, "formalize_query", return_value={
                    "rule": "pred rule { some Patron }", "extension": []}) as formalize, \
                    patch.object(pipeline, "generate_plan", return_value=plan) as generate, \
                    patch.object(pipeline, "call_claude", return_value=plan) as repair, \
                    patch.object(pipeline, "run_alloy", side_effect=[
                        (True, unsafe, "UNSAFE"), (True, safe, "SAFE")] * 2), \
                    patch.object(evaluator, "branch_stage_samples", side_effect=AssertionError) as branch:
                payload = full_pipeline.run_experiment([prompt], args)
                self.assertEqual(formalize.call_count, 2)
                self.assertEqual(formalize.call_args.kwargs["alloy_timeout"], args.alloy_timeout)
                self.assertEqual(generate.call_count, 2)
                self.assertEqual(repair.call_count, 2)
                branch.assert_not_called()
                args.resume = True
                self.assertEqual(full_pipeline.run_sample(prompt, 1, args)["plan_status"], "SAFE")
                self.assertEqual(generate.call_count, 2)
            for run in payload["per_prompt"]["3"]["runs"]:
                self.assertTrue(run["full_success"])
                self.assertEqual(run["plan_stage_counts"]["logic_repair"], 1)
            self.assertFalse(list(root.glob("runs/*/rep_*/*_samples")))
            log = root / "full_pipeline_passk_log.json"
            with patch.object(pipeline, "formalize_query", side_effect=AssertionError), \
                    patch.object(pipeline, "generate_plan", side_effect=AssertionError):
                self.assertEqual(full_pipeline.main(["--plot-only", "--log", str(log)]), 0)
            self.assertEqual(len(list(root.glob("*.png"))), 2)
            self.assertEqual(len(list(root.glob("*.pdf"))), 2)

    def test_full_pipeline_metrics_follow_chen_and_leave_missing_k_undefined(self):
        args = full_pipeline.parse_args(["--pass-at-k", "5"])
        runs = [{"rep": i, "complete": True, "plan_status": "SAFE" if i == 1 else "UNSAFE",
                 "full_success": i == 1} for i in range(1, 5)]
        per_prompt = {"3": {"id": 3, "category": "test", "runs": runs}}
        metrics = full_pipeline.compute_metrics(full_pipeline.make_payload(args, per_prompt))
        self.assertEqual(metrics["full_pipeline"]["per_prompt"]["3"]["rates"],
                         [0.25, 0.5, 0.75, 1.0, None])
        per_prompt["4"] = {"id": 4, "category": "test", "runs": []}
        metrics = full_pipeline.compute_metrics(full_pipeline.make_payload(args, per_prompt))
        self.assertEqual(metrics["full_pipeline"]["average"], [None] * 5)
        runs[0]["plan_status"] = "ERROR"
        with self.assertRaisesRegex(ValueError, "Infrastructure error"):
            full_pipeline.compute_metrics(full_pipeline.make_payload(args, per_prompt))


if __name__ == "__main__":
    unittest.main()
