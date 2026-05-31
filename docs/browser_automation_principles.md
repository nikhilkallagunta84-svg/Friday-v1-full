# FRIDAY Browser Automation Principles

These rules define how FRIDAY should reason about browser control. They are intentionally written as an agent-facing operating model so Codex, Claude Code, or any future planner can follow the same pattern.

## Core Model

Every browser task must become structured screen actions before execution.

FRIDAY already represents these with `ScreenAction` objects:

```json
{
  "action_type": "browser.click",
  "target": "Search box",
  "value": "Lil Baby songs",
  "risk_level": "low",
  "requires_confirmation": false
}
```

Execution must flow through:

```text
user intent
  -> action planner
  -> risk classifier
  -> controller router
  -> browser controller
  -> action result
  -> sanitized action log
```

Do not pass loose dictionaries around new screen-control code when a `ScreenAction` or `ActionResult` can be used.

## Semantic First

FRIDAY should prefer semantic browser control over pixels.

Preferred order:

1. Playwright locators: role, label, placeholder, text, semantic input selectors.
2. Accessibility-style element intent: button/link/search field/result names.
3. DOM/result patterns: search result links, video titles, known form inputs.
4. Screenshot/vision fallback for canvas-heavy or inaccessible pages.
5. Coordinates only when a semantic or vision-backed target is unavailable.

The key abstraction is a stable element handle. In Playwright this is a locator. In future browser-tool adapters this may be a `ref_*` DOM handle.

## Finding Elements

When the user gives intent such as:

```text
click the first link
click the search bar
type into the email field
click the first video result
```

FRIDAY should bind that intent to a semantic target before clicking.

Current implementation map:

- `friday/brain/action_planner.py` turns natural language into `ScreenAction`.
- `friday/control/browser_controller.py` resolves browser targets with Playwright locators.
- `friday/control/vision_controller.py` exists only as a fallback for screenshot-level control.

## Clicking

Clicking should prefer stable handles.

Preferred:

```text
intent -> semantic locator/ref -> click
```

Fallback:

```text
intent -> screenshot -> vision locate -> coordinate click -> confirm if uncertain
```

Coordinate clicks should not be the default for normal websites.

## Typing

Typing should use field-specific actions when possible.

Preferred:

```text
target field -> fill/form input
```

Fallback:

```text
focus current field -> keyboard type
```

Never type passwords, tokens, API keys, or private credentials from voice/text commands.

## Batch Plans

Multi-step requests should stay as one ordered plan:

```text
open site
find/search/type/click
verify
summarize
log
```

`ControllerRouter.execute_plan()` is FRIDAY's current batch runner. It executes sequentially, returns one `ActionResult` per action, and stops on critical failure or emergency stop.

## Verification

After every state-changing action, FRIDAY should verify cheaply.

Examples:

- After opening/searching: confirm navigation completed enough to continue.
- After clicking: allow the page to settle before the next action.
- After typing: confirm the action did not throw and keep the next action deterministic.
- After failure: avoid guessing, return a clean `ActionResult`, and let the planner/router decide fallback.

Do not store screenshots or full page content in logs. Diagnostics should be short and sanitized.

## Strategy Choice

Use this decision order:

```text
normal website with usable DOM -> Playwright semantic locators
long article/read-only page -> page text/extraction
canvas-heavy app -> screenshot + vision fallback
desktop app with accessibility data -> accessibility controller
graphical inaccessible app -> vision + PyAutoGUI fallback
high-risk action -> confirmation
blocked sensitive action -> refuse
```

## Error Handling

If an action fails:

1. Return an `ActionResult(success=False)`.
2. Do not expose stack traces to the user.
3. Do not log screenshots, full page content, credentials, or form values.
4. Prefer one retry only when the page likely changed.
5. Stop the current plan if continuing could cause accidental clicks or typing.

## TL;DR

```text
intent
  -> plan structured actions
  -> prefer semantic refs/locators
  -> batch sequential actions
  -> verify after state changes
  -> use vision/coordinates only as fallback
  -> log sanitized replay history
```

The rule: refs over pixels, batches over one-off clicks, verification after state changes.
