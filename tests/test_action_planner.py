from __future__ import annotations

import unittest

from friday.brain.action_planner import plan_screen_actions
from friday.schemas.risk import RiskLevel
from friday.schemas.screen_action import ActionType, ScreenAction


class ActionPlannerTests(unittest.TestCase):
    def test_open_youtube_creates_browser_open_url(self) -> None:
        actions = plan_screen_actions("open youtube")

        self.assertEqual(len(actions), 1)
        self.assertIsInstance(actions[0], ScreenAction)
        self.assertEqual(actions[0].action_type, ActionType.BROWSER_OPEN_URL)
        self.assertEqual(actions[0].target, "youtube")
        self.assertEqual(actions[0].value, "https://www.youtube.com")

    def test_search_youtube_creates_open_and_search_actions(self) -> None:
        actions = plan_screen_actions("search youtube for AP Calculus")

        self.assertEqual([action.action_type for action in actions], [ActionType.BROWSER_OPEN_URL, ActionType.BROWSER_SEARCH])
        self.assertEqual(actions[0].target, "youtube")
        self.assertEqual(actions[1].target, "youtube search")
        self.assertEqual(actions[1].value, "ap calculus")

    def test_open_spotify_and_search_creates_valid_browser_actions(self) -> None:
        actions = plan_screen_actions("open spotify and search Lil Baby")

        self.assertEqual([action.action_type for action in actions], [ActionType.BROWSER_OPEN_URL, ActionType.BROWSER_SEARCH])
        self.assertEqual(actions[0].value, "https://open.spotify.com")
        self.assertEqual(actions[1].target, "spotify search")
        self.assertEqual(actions[1].value, "lil baby")
        self.assertTrue(all(isinstance(action, ScreenAction) for action in actions))

    def test_search_major_website_creates_open_and_site_search_actions(self) -> None:
        actions = plan_screen_actions("search instagram for AI engineering")

        self.assertEqual([action.action_type for action in actions], [ActionType.BROWSER_OPEN_URL, ActionType.BROWSER_SEARCH])
        self.assertEqual(actions[0].target, "instagram")
        self.assertEqual(actions[0].value, "https://www.instagram.com")
        self.assertEqual(actions[1].target, "instagram search")
        self.assertEqual(actions[1].value, "ai engineering")

    def test_open_major_website_alias_works(self) -> None:
        actions = plan_screen_actions("open insta")

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action_type, ActionType.BROWSER_OPEN_URL)
        self.assertEqual(actions[0].target, "insta")
        self.assertEqual(actions[0].value, "https://www.instagram.com")

    def test_open_youtube_and_search_for_strips_optional_for(self) -> None:
        actions = plan_screen_actions("open youtube and search for AI agents")

        self.assertEqual([action.action_type for action in actions], [ActionType.BROWSER_OPEN_URL, ActionType.BROWSER_SEARCH])
        self.assertEqual(actions[1].target, "youtube search")
        self.assertEqual(actions[1].value, "ai agents")

    def test_open_youtube_and_play_creates_search_and_click_plan(self) -> None:
        actions = plan_screen_actions("open youtube and play Sum 2 Prove by Lil Baby")

        self.assertEqual(
            [action.action_type for action in actions],
            [ActionType.BROWSER_OPEN_URL, ActionType.BROWSER_SEARCH, ActionType.BROWSER_CLICK],
        )
        self.assertEqual(actions[0].target, "youtube")
        self.assertEqual(actions[1].target, "youtube search")
        self.assertEqual(actions[1].value, "sum 2 prove by lil baby")
        self.assertEqual(actions[2].target, "first playable result")

    def test_click_search_bar_and_type_creates_two_step_plan(self) -> None:
        actions = plan_screen_actions("click the search bar and type Lil Baby")

        self.assertEqual([action.action_type for action in actions], [ActionType.BROWSER_CLICK, ActionType.BROWSER_TYPE])
        self.assertEqual(actions[0].target, "search bar")
        self.assertEqual(actions[1].target, "current field")
        self.assertEqual(actions[1].value, "lil baby")

    def test_click_ordinal_link_keeps_semantic_target(self) -> None:
        actions = plan_screen_actions("click the first link")

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action_type, ActionType.BROWSER_CLICK)
        self.assertEqual(actions[0].target, "first link")

    def test_open_site_and_click_button_creates_open_then_click(self) -> None:
        actions = plan_screen_actions("open youtube and click the sign in button")

        self.assertEqual([action.action_type for action in actions], [ActionType.BROWSER_OPEN_URL, ActionType.BROWSER_CLICK])
        self.assertEqual(actions[0].target, "youtube")
        self.assertEqual(actions[0].value, "https://www.youtube.com")
        self.assertEqual(actions[1].target, "sign in")

    def test_click_button_on_specific_site_creates_open_then_click(self) -> None:
        actions = plan_screen_actions("click the login button on github")

        self.assertEqual([action.action_type for action in actions], [ActionType.BROWSER_OPEN_URL, ActionType.BROWSER_CLICK])
        self.assertEqual(actions[0].target, "github")
        self.assertEqual(actions[0].value, "https://github.com")
        self.assertEqual(actions[1].target, "login")

    def test_find_element_on_site_and_click_it_creates_open_then_click(self) -> None:
        actions = plan_screen_actions("find templates on canva and click it")

        self.assertEqual([action.action_type for action in actions], [ActionType.BROWSER_OPEN_URL, ActionType.BROWSER_CLICK])
        self.assertEqual(actions[0].target, "canva")
        self.assertEqual(actions[1].target, "templates")

    def test_click_typo_alias_is_treated_as_click(self) -> None:
        actions = plan_screen_actions("lick the pricing button on openai")

        self.assertEqual([action.action_type for action in actions], [ActionType.BROWSER_OPEN_URL, ActionType.BROWSER_CLICK])
        self.assertEqual(actions[0].target, "openai")
        self.assertEqual(actions[1].target, "pricing")

    def test_send_email_becomes_high_risk(self) -> None:
        actions = plan_screen_actions("send this email")

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].risk_level, RiskLevel.HIGH)
        self.assertTrue(actions[0].requires_confirmation)

    def test_type_my_password_becomes_blocked(self) -> None:
        actions = plan_screen_actions("type my password")

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].risk_level, RiskLevel.BLOCKED)
        self.assertTrue(actions[0].requires_confirmation)

    def test_planner_never_returns_raw_dicts(self) -> None:
        commands = [
            "open chatgpt",
            "open google docs",
            "click search box",
            "type hello world",
            "go back",
            "new tab",
            "close tab",
        ]

        for command in commands:
            with self.subTest(command=command):
                actions = plan_screen_actions(command)
                self.assertTrue(actions)
                self.assertTrue(all(isinstance(action, ScreenAction) for action in actions))
                self.assertFalse(any(isinstance(action, dict) for action in actions))


if __name__ == "__main__":
    unittest.main()
