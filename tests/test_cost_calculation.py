import unittest

from agents.controller_agent import ControllerAgent


class MockLLMValid:
    def chat(self, messages, model, temperature=None, max_tokens=None):
        return (
            '{"legs":['
            '{"event":"Cooking Class","attendees_total":2},'
            '{"event":"Tech Meetup","attendees_total":6}'
            "]}"
        )


class MockLLMInvalid:
    def chat(self, messages, model, temperature=None, max_tokens=None):
        return "not-json"


class MockLLMComplexPlan:
    def chat(self, messages, model, temperature=None, max_tokens=None):
        return (
            '{"legs":['
            '{"activity_text":"cooking class","attendees_total":3,"confidence":0.98},'
            '{"activity_text":"tech meetup","attendees_total":9,"confidence":0.97}'
            '],'
            '"needs_clarification":false,'
            '"clarification_question":""}'
        )


class MockLLMMixedFamilyNumeric:
    def chat(self, messages, model, temperature=None, max_tokens=None):
        return (
            '{"legs":['
            '{"activity_text":"tech meetup","attendees_total":4,"confidence":0.94}'
            '],'
            '"needs_clarification":false,'
            '"clarification_question":""}'
        )


class MockLLMNeedsClarification:
    def chat(self, messages, model, temperature=None, max_tokens=None):
        return (
            '{"legs":[],"needs_clarification":true,'
            '"clarification_question":"How many people will attend the tech meetup in total?"}'
        )


class CostCalculationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.events = [
            {"name": "Art Exhibition", "location": "National Gallery", "price": 15.0},
            {"name": "Tech Meetup", "location": "StartupX Hub", "price": 5.0},
            {"name": "Cooking Class", "location": "Culinary Institute", "price": 75.0},
        ]
        self.date = "2026-03-06"

    def _controller(self):
        ctl = ControllerAgent.__new__(ControllerAgent)
        ctl.last_event_results = []
        ctl.last_event_date = None
        return ctl

    def test_fallback_parses_with_friends_and_wife(self):
        ctl = self._controller()
        query = (
            "I want to go the cooking class with my wife and then attend "
            "the tech meetup with 5 SCM friends. How much does it cost in total?"
        )

        result = ctl._calculate_cost_from_query(query, self.events, self.date)

        self.assertIsNotNone(result)
        self.assertIn("Cooking Class: \\$75.00 x 2 = \\$150.00", result)
        self.assertIn("Tech Meetup: \\$5.00 x 6 = \\$30.00", result)
        self.assertIn("Total: \\$180.00", result)

    def test_explicit_people_count_is_used_as_total(self):
        ctl = self._controller()
        query = "How much for 2 persons attending tech meetup?"

        result = ctl._calculate_cost_from_query(query, self.events, self.date)

        self.assertIsNotNone(result)
        self.assertIn("Tech Meetup: \\$5.00 x 2 = \\$10.00", result)
        self.assertIn("Total: \\$10.00", result)

    def test_hybrid_uses_llm_structured_legs(self):
        ctl = self._controller()
        ctl.llm = MockLLMValid()
        ctl.llm_model = "mock"
        query = (
            "Go for cooking class with my wife and then tech meetup with colleagues. "
            "How much total?"
        )

        result = ctl._calculate_cost_from_query(query, self.events, self.date)

        self.assertIsNotNone(result)
        self.assertIn("Cooking Class: \\$75.00 x 2 = \\$150.00", result)
        self.assertIn("Tech Meetup: \\$5.00 x 6 = \\$30.00", result)
        self.assertIn("Total: \\$180.00", result)

    def test_invalid_llm_output_falls_back_to_regex(self):
        ctl = self._controller()
        ctl.llm = MockLLMInvalid()
        ctl.llm_model = "mock"
        query = "How much to attend tech meetup with 3 friends?"

        result = ctl._calculate_cost_from_query(query, self.events, self.date)

        self.assertIsNotNone(result)
        self.assertIn("Tech Meetup: \\$5.00 x 4 = \\$20.00", result)
        self.assertIn("Total: \\$20.00", result)

    def test_hybrid_supports_multiple_groups_and_family_mentions(self):
        ctl = self._controller()
        ctl.llm = MockLLMComplexPlan()
        ctl.llm_model = "mock"
        query = (
            "I want to go cooking class with my wife and daughter and then "
            "attend tech meetup with 5 colleagues and 3 partners. "
            "How much does it cost in total?"
        )

        result = ctl._calculate_cost_from_query(query, self.events, self.date)

        self.assertIsNotNone(result)
        self.assertIn("Cooking Class: \\$75.00 x 3 = \\$225.00", result)
        self.assertIn("Tech Meetup: \\$5.00 x 9 = \\$45.00", result)
        self.assertIn("Total: \\$270.00", result)

    def test_hybrid_supports_mixed_family_numeric(self):
        ctl = self._controller()
        ctl.llm = MockLLMMixedFamilyNumeric()
        ctl.llm_model = "mock"
        query = "How much to attend tech meetup with my wife and 2 daughters?"

        result = ctl._calculate_cost_from_query(query, self.events, self.date)

        self.assertIsNotNone(result)
        self.assertIn("Tech Meetup: \\$5.00 x 4 = \\$20.00", result)
        self.assertIn("Total: \\$20.00", result)

    def test_hybrid_returns_clarification_when_counts_are_ambiguous(self):
        ctl = self._controller()
        ctl.llm = MockLLMNeedsClarification()
        ctl.llm_model = "mock"
        query = "How much to attend the tech meetup with some friends?"

        result = ctl._calculate_cost_from_query(query, self.events, self.date)

        self.assertEqual(
            result,
            "How many people will attend the tech meetup in total?",
        )


if __name__ == "__main__":
    unittest.main()
