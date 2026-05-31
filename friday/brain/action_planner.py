from __future__ import annotations

import re
from hashlib import sha1
from typing import Iterable

from friday.brain.risk_classifier import classify_action
from friday.known_sites import PLAYABLE_SITE_ALIASES, WEBSITE_ALIASES
from friday.schemas.screen_action import ActionType, ScreenAction

# Canonical site data lives in friday/known_sites.py.
# Strip trailing slashes so URL comparisons are consistent within this module.
MAJOR_WEBSITES = {key: url.rstrip("/") for key, url in WEBSITE_ALIASES.items()}

PLAYABLE_SITES = set(PLAYABLE_SITE_ALIASES.keys())


def plan_screen_actions(user_command: str) -> list[ScreenAction]:
    command = _normalize_command(user_command)
    if not command:
        return []
    return _classify_all(_deterministic_plan(command, user_command.strip()))


def _deterministic_plan(command: str, source_command: str) -> list[ScreenAction]:
    browser_shortcut = _browser_shortcut_action(command, source_command)
    if browser_shortcut:
        return [browser_shortcut]

    unsafe_request = _unsafe_request_action(command, source_command)
    if unsafe_request:
        return [unsafe_request]

    send_or_submit = _send_or_submit_action(command, source_command)
    if send_or_submit:
        return [send_or_submit]

    site_click_actions = _site_click_actions(command, source_command)
    if site_click_actions:
        return site_click_actions

    play_actions = _play_actions(command, source_command)
    if play_actions:
        return play_actions

    compound_actions = _compound_click_type_actions(command, source_command)
    if compound_actions:
        return compound_actions

    type_action = _type_action(command, source_command)
    if type_action:
        return [type_action]

    click_action = _click_action(command, source_command)
    if click_action:
        return [click_action]

    search_actions = _search_actions(command, source_command)
    if search_actions:
        return search_actions

    open_actions = _open_actions(command, source_command)
    if open_actions:
        return open_actions

    return []


def _browser_shortcut_action(command: str, source_command: str) -> ScreenAction | None:
    if re.fullmatch(r"(?:go\s+)?back", command):
        return _make_action(ActionType.BROWSER_NAVIGATE, "browser history", "back", source_command, 1)
    if re.fullmatch(r"(?:open\s+)?new\s+tab", command):
        return _make_action(ActionType.BROWSER_NAVIGATE, "browser tab", "new_tab", source_command, 1)
    if re.fullmatch(r"close\s+(?:the\s+)?tab", command):
        return _make_action(ActionType.BROWSER_NAVIGATE, "browser tab", "close_tab", source_command, 1)
    if command in {"stop", "cancel", "nevermind", "never mind"}:
        return _make_action(ActionType.SYSTEM_STOP, "current action", command, source_command, 1)
    return None


def _unsafe_request_action(command: str, source_command: str) -> ScreenAction | None:
    if re.search(r"\b(password|captcha|bypass|hide\s+activity|delete\s+files?|rm\s+-rf|format\s+(?:disk|drive))\b", command):
        return _make_action(ActionType.SYSTEM_STOP, "unsafe request", command, source_command, 1)
    return None


def _send_or_submit_action(command: str, source_command: str) -> ScreenAction | None:
    if re.search(r"\b(send|email|message|text|dm|reply)\b", command):
        return _make_action(ActionType.BROWSER_CLICK, "send message or email", "", source_command, 1)
    if re.search(r"\b(submit|turn\s+in|hand\s+in)\b", command):
        return _make_action(ActionType.BROWSER_CLICK, "submit form", "", source_command, 1)
    if re.search(r"\b(buy|purchase|checkout|pay|payment|order)\b", command):
        return _make_action(ActionType.BROWSER_CLICK, "payment or purchase action", "", source_command, 1)
    return None


def _type_action(command: str, source_command: str) -> ScreenAction | None:
    match = re.match(r"^(?:type|enter|write)\s+(.+)$", command)
    if not match:
        return None
    value = _strip_wrapping_quotes(match.group(1))
    return _make_action(ActionType.BROWSER_TYPE, "current field", value, source_command, 1)


def _compound_click_type_actions(command: str, source_command: str) -> list[ScreenAction]:
    match = re.match(
        r"^(?:click|tap|press|lick)\s+(?:on\s+|the\s+)?(.+?)\s+(?:and\s+)?(?:then\s+)?(?:type|enter|write)\s+(.+)$",
        command,
    )
    if not match:
        return []
    target = _clean_click_target(match.group(1))
    value = _strip_wrapping_quotes(match.group(2))
    if not target or not value:
        return []
    return [
        _make_action(ActionType.BROWSER_CLICK, target, "", source_command, 1),
        _make_action(ActionType.BROWSER_TYPE, "current field", value, source_command, 2),
    ]


def _click_action(command: str, source_command: str) -> ScreenAction | None:
    match = re.match(r"^(?:click|tap|press|lick)\s+(?:on\s+|the\s+)?(.+)$", command)
    if not match:
        return None
    target = _clean_click_target(match.group(1))
    return _make_action(ActionType.BROWSER_CLICK, target, "", source_command, 1)


def _site_click_actions(command: str, source_command: str) -> list[ScreenAction]:
    patterns = [
        (
            r"^(?:open|go\s+to|launch|pull\s+up)\s+(.+?)\s+and\s+(?:find\s+and\s+)?(?:click|tap|press|lick)\s+(?:on\s+|the\s+)?(.+)$",
            "site_first",
        ),
        (
            r"^(?:on|in|inside|within)\s+(.+?)\s+(?:find\s+and\s+)?(?:click|tap|press|lick)\s+(?:on\s+|the\s+)?(.+)$",
            "site_first",
        ),
        (
            r"^(?:find\s+and\s+)?(?:click|tap|press|lick)\s+(?:on\s+|the\s+)?(.+)\s+(?:on|in|inside|within)\s+(.+)$",
            "target_first",
        ),
        (
            r"^(?:look\s+for|find|locate)\s+(?:the\s+)?(.+?)\s+(?:on|in|inside|within)\s+(.+?)\s+and\s+(?:click|tap|press|lick)(?:\s+it)?$",
            "target_first",
        ),
    ]
    for pattern, order in patterns:
        match = re.match(pattern, command)
        if not match:
            continue
        if order == "site_first":
            site_text, target_text = match.group(1), match.group(2)
        else:
            target_text, site_text = match.group(1), match.group(2)
        open_action = _site_open_action(site_text, source_command, 1)
        target = _clean_click_target(target_text)
        if open_action and target:
            return [
                open_action,
                _make_action(ActionType.BROWSER_CLICK, target, "", source_command, 2),
            ]
    return []


def _search_actions(command: str, source_command: str) -> list[ScreenAction]:
    match = re.match(r"^search\s+(.+?)\s+for\s+(.+)$", command)
    if match:
        site = _canonical_site(match.group(1))
        query = _strip_wrapping_quotes(match.group(2))
        if site:
            return [
                _make_action(ActionType.BROWSER_OPEN_URL, site, MAJOR_WEBSITES[site], source_command, 1),
                _make_action(ActionType.BROWSER_SEARCH, f"{site} search", query, source_command, 2),
            ]
        return [_make_action(ActionType.BROWSER_SEARCH, "web search", f"{match.group(1)} for {query}", source_command, 1)]

    match = re.match(r"^(?:search|find|look up)\s+(?:in|on|inside|within)\s+(.+?)\s+(?:for|about)\s+(.+)$", command)
    if match:
        site = _canonical_site(match.group(1))
        query = _strip_wrapping_quotes(match.group(2))
        if site:
            return [
                _make_action(ActionType.BROWSER_OPEN_URL, site, MAJOR_WEBSITES[site], source_command, 1),
                _make_action(ActionType.BROWSER_SEARCH, f"{site} search", query, source_command, 2),
            ]

    match = re.match(r"^(?:search|find|look up|google)\s+(?:for\s+)?(.+?)\s+(?:in|on|inside|within)\s+(.+)$", command)
    if match:
        query = _strip_wrapping_quotes(match.group(1))
        site = _canonical_site(match.group(2))
        if site:
            return [
                _make_action(ActionType.BROWSER_OPEN_URL, site, MAJOR_WEBSITES[site], source_command, 1),
                _make_action(ActionType.BROWSER_SEARCH, f"{site} search", query, source_command, 2),
            ]

    match = re.match(r"^(?:open|go\s+to|launch|pull\s+up)\s+(.+?)\s+and\s+(?:search|look\s+up|find)(?:\s+for)?\s+(.+)$", command)
    if match:
        site = _canonical_site(match.group(1))
        query = _strip_wrapping_quotes(match.group(2))
        if site:
            return [
                _make_action(ActionType.BROWSER_OPEN_URL, site, MAJOR_WEBSITES[site], source_command, 1),
                _make_action(ActionType.BROWSER_SEARCH, f"{site} search", query, source_command, 2),
            ]
    return []


def _play_actions(command: str, source_command: str) -> list[ScreenAction]:
    patterns = [
        (r"^(?:open|go\s+to|launch|pull\s+up)\s+(.+?)\s+and\s+(?:play|put\s+on|start\s+playing)(?:\s+for\s+me)?\s+(.+)$", "site_first"),
        (r"^(?:play|put\s+on|start\s+playing)\s+(.+?)\s+(?:on|in|through|using)\s+(.+)$", "query_first"),
    ]
    for pattern, order in patterns:
        match = re.match(pattern, command)
        if not match:
            continue
        if order == "site_first":
            site = _canonical_playable_site(match.group(1))
            query = _strip_wrapping_quotes(match.group(2))
        else:
            query = _strip_wrapping_quotes(match.group(1))
            site = _canonical_playable_site(match.group(2))
        if site and query:
            return [
                _make_action(ActionType.BROWSER_OPEN_URL, site, MAJOR_WEBSITES[site], source_command, 1),
                _make_action(ActionType.BROWSER_SEARCH, f"{site} search", query, source_command, 2),
                _make_action(ActionType.BROWSER_CLICK, "first playable result", "", source_command, 3),
            ]
    return []


def _open_actions(command: str, source_command: str) -> list[ScreenAction]:
    match = re.match(r"^(?:open|go\s+to|launch|pull\s+up)\s+(.+)$", command)
    if not match:
        return []
    target = _clean_open_target(match.group(1))
    site = _canonical_site(target)
    if site:
        return [_make_action(ActionType.BROWSER_OPEN_URL, site, MAJOR_WEBSITES[site], source_command, 1)]
    if _looks_like_url(target):
        return [_make_action(ActionType.BROWSER_OPEN_URL, target, _normalize_url(target), source_command, 1)]
    return []


def _site_open_action(value: str, source_command: str, index: int) -> ScreenAction | None:
    target = _clean_open_target(value)
    site = _canonical_site(target)
    if site:
        return _make_action(ActionType.BROWSER_OPEN_URL, site, MAJOR_WEBSITES[site], source_command, index)
    if _looks_like_url(target):
        return _make_action(ActionType.BROWSER_OPEN_URL, target, _normalize_url(target), source_command, index)
    return None


def _make_action(action_type: ActionType, target: str, value: str, source_command: str, index: int) -> ScreenAction:
    return ScreenAction(
        action_id=_action_id(source_command, action_type.value, target, value, index),
        action_type=action_type,
        target=target.strip(),
        value=value.strip(),
        risk_level="safe",
        requires_confirmation=False,
        source_command=source_command,
    )


def _classify_all(actions: Iterable[ScreenAction]) -> list[ScreenAction]:
    return [classify_action(action) for action in actions]


def _normalize_command(command: str) -> str:
    clean = " ".join(command.strip().split()).lower()
    clean = re.sub(r"^(?:hey\s+)?friday[,\s]+", "", clean)
    clean = re.sub(r"^(?:can\s+you|could\s+you|please)\s+", "", clean)
    return clean.strip()


def _canonical_site(value: str) -> str | None:
    cleaned = _clean_open_target(value)
    if cleaned in MAJOR_WEBSITES:
        return cleaned
    compact = cleaned.replace(".", " ")
    if compact in MAJOR_WEBSITES:
        return compact
    for site in sorted(MAJOR_WEBSITES, key=len, reverse=True):
        if cleaned == site or cleaned.endswith(f" {site}"):
            return site
    return None


def _canonical_playable_site(value: str) -> str | None:
    site = _canonical_site(value)
    if not site:
        return None
    if site in PLAYABLE_SITES:
        if site in {"you tube", "yt"}:
            return "youtube"
        if site in {"spotfy", "spotifiy", "spotufy"}:
            return "spotify"
        if site == "sound cloud":
            return "soundcloud"
        if site == "tik tok":
            return "tiktok"
        return site
    return None


def _clean_open_target(value: str) -> str:
    clean = _strip_wrapping_quotes(value)
    clean = re.sub(r"\s+(?:for\s+me|please)$", "", clean).strip()
    return clean


def _clean_click_target(value: str) -> str:
    clean = _strip_wrapping_quotes(value)
    clean = re.sub(r"\s+(?:for\s+me|please)$", "", clean).strip()
    clean = re.sub(r"^(?:on\s+)?(?:a|an|the)\s+", "", clean).strip()
    clean = re.sub(r"\s+(?:page|website|site)$", "", clean).strip()
    has_tab_context = bool(re.search(r"\s+(?:on|in|from)\s+.+\s+(?:tab|page|window|results?)$", clean))
    if not _is_ordinal_link_target(clean) and not has_tab_context:
        clean = re.sub(r"\s+(?:button|link|tab|menu|icon|field)$", "", clean).strip()
    return clean


def _is_ordinal_link_target(value: str) -> bool:
    clean = " ".join(value.lower().strip().split())
    clean = re.sub(r"^(?:a|an|the)\s+", "", clean)
    return bool(
        re.match(r"^(?:top|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)?)\s+(?:link|result)$", clean)
        or re.match(r"^(?:link|result)\s+(?:number\s+)?(?:top|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)?)$", clean)
    )


def _strip_wrapping_quotes(value: str) -> str:
    clean = value.strip()
    if len(clean) >= 2 and clean[0] == clean[-1] and clean[0] in {"'", '"'}:
        return clean[1:-1].strip()
    return clean


def _looks_like_url(value: str) -> bool:
    return bool(re.match(r"^(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+", value))


def _normalize_url(value: str) -> str:
    clean = value.strip()
    if re.match(r"^https?://", clean):
        return clean
    return f"https://{clean}"


def _action_id(source_command: str, action_type: str, target: str, value: str, index: int) -> str:
    digest = sha1(f"{source_command}|{action_type}|{target}|{value}|{index}".encode("utf-8")).hexdigest()[:12]
    return f"screen-action-{index}-{digest}"
