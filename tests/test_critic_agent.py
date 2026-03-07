import unittest

from agents.critic_agent import CriticAgent


class MockClientRewrite:
    def chat(self, messages, model, temperature=None, max_tokens=None):
        return (
            '{"action":"rewrite","rewritten_response":"Improved response ✨",'
            '"reason":"better coherence"}'
        )


class MockClientKeep:
    def chat(self, messages, model, temperature=None, max_tokens=None):
        return '{"action":"keep","rewritten_response":"","reason":"already good"}'


class MockClientEmpty:
    def chat(self, messages, model, temperature=None, max_tokens=None):
        return ""


class MockClientQuotaError:
    def chat(self, messages, model, temperature=None, max_tokens=None):
        raise Exception("429 insufficient_quota")


class CriticAgentTests(unittest.TestCase):
    def _agent(self, client):
        return CriticAgent(
            provider="openai",
            model="gpt-5-mini",
            llm_client=client,
        )

    def test_applies_rewrite_when_critic_requests_it(self):
        agent = self._agent(MockClientRewrite())
        result = agent.review_response(
            user_query="Any events today?",
            draft_response="Events listed.",
            intents=["EVENT_QUERY_DB"],
            recent_history=[],
            tourism_persona="persona",
            style_memory="style",
        )
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["response"], "Improved response ✨")

    def test_keeps_draft_when_action_keep(self):
        agent = self._agent(MockClientKeep())
        result = agent.review_response(
            user_query="Any events today?",
            draft_response="Events listed.",
            intents=["EVENT_QUERY_DB"],
            recent_history=[],
            tourism_persona="persona",
            style_memory="style",
        )
        self.assertEqual(result["status"], "kept")
        self.assertEqual(result["response"], "Events listed.")

    def test_skips_when_critic_returns_empty(self):
        agent = self._agent(MockClientEmpty())
        result = agent.review_response(
            user_query="Any events today?",
            draft_response="Events listed.",
            intents=["EVENT_QUERY_DB"],
            recent_history=[],
            tourism_persona="persona",
            style_memory="style",
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["response"], "Events listed.")

    def test_quota_error_is_fail_open(self):
        agent = self._agent(MockClientQuotaError())
        result = agent.review_response(
            user_query="Any events today?",
            draft_response="Events listed.",
            intents=["EVENT_QUERY_DB"],
            recent_history=[],
            tourism_persona="persona",
            style_memory="style",
        )
        self.assertEqual(result["status"], "skipped_quota")
        self.assertEqual(result["response"], "Events listed.")


if __name__ == "__main__":
    unittest.main()
