"""Provider selection and request formatting, without network calls."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pipeline


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
            llm = pipeline.LLM("claude-test")
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
            with self.assertRaisesRegex(pipeline.PipelineError, "ANTHROPIC_API_KEY"):
                pipeline.LLM("claude-test")
        constructor.assert_not_called()

    def test_non_claude_models_and_mixed_judges_are_rejected(self):
        with self.assertRaisesRegex(pipeline.PipelineError, "Claude"):
            pipeline.Settings(model="deepseek-chat")
        with self.assertRaisesRegex(pipeline.PipelineError, "same Claude model"):
            pipeline.Settings(model="claude-test", judge_model="claude-other")

    def test_completion_cannot_switch_models(self):
        constructor = MagicMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=True), \
                patch.dict(sys.modules, {"anthropic": fake_sdk(Anthropic=constructor)}):
            llm = pipeline.LLM("claude-test")
            with self.assertRaisesRegex(pipeline.PipelineError, "same Claude model"):
                llm.complete("system", "user", temperature=0.7, max_tokens=100,
                             model="claude-other")
        constructor.return_value.messages.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
