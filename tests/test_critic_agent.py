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


class MockClientCostMismatch:
    def chat(self, messages, model, temperature=None, max_tokens=None):
        return (
            '{"inconsistency_detected":true,'
            '"clarification_question":"Just to confirm: for Cooking Class, is it 3 people total (you, wife, daughter)?"}'
        )


class MockClientCostOk:
    def chat(self, messages, model, temperature=None, max_tokens=None):
        return '{"inconsistency_detected":false,"clarification_question":""}'


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

    def test_detect_attendee_inconsistency_requests_clarification(self):
        agent = self._agent(MockClientCostMismatch())
        result = agent.detect_attendee_inconsistency(
            user_query="I go with my wife and daughter then 5 colleagues and 3 partners",
            draft_response="Cooking Class: $75 x 2 ...",
        )
        self.assertEqual(result["status"], "clarification_needed")
        self.assertIn("Cooking Class", result.get("clarification_question", ""))

    def test_detect_attendee_inconsistency_ok(self):
        agent = self._agent(MockClientCostOk())
        result = agent.detect_attendee_inconsistency(
            user_query="2 people for class, 6 for meetup",
            draft_response="Cooking Class: $75 x 2 ... Tech Meetup: $5 x 6 ...",
        )
        self.assertEqual(result["status"], "ok")

    def test_detect_attendee_inconsistency_quota_fail_open(self):
        agent = self._agent(MockClientQuotaError())
        result = agent.detect_attendee_inconsistency(
            user_query="...",
            draft_response="...",
        )
        self.assertEqual(result["status"], "skipped_quota")


if __name__ == "__main__":
    unittest.main()
