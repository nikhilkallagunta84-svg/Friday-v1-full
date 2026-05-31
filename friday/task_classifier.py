from __future__ import annotations

import re

_VISION_PATTERNS = re.compile(
    r"\b(?:screen(?:shot)?|what(?:'?s| is) on my (?:screen|display)|describe my screen"
    r"|look(?:ing)? at|read (?:my |the |what's on (?:my )?)?screen"
    r"|click the .{1,40} button|find the .{1,30} on (?:my )?screen"
    r"|what am i looking at|help me with this screen"
    r"|visible (?:ui|element|button|field|text)|analyze this"
    r"|image|photo|picture|video|upload)",
    re.IGNORECASE,
)

# Programming-language keywords that strongly imply code work.
_CODE_LANGUAGES = (
    r"python|java(?:script)?|typescript|ts|js|rust|go(?:lang)?|c\+\+|cpp|c#|csharp"
    r"|kotlin|swift|ruby|php|bash|shell|sql|html|css|react|vue|svelte|node"
    r"|tsx|jsx|ts file|py file|sh script"
)

# "Write code", "generate a function", "build a script" — strong code triggers.
_CODE_VERBS = (
    r"(?:write|generate|create|make|build|draft|produce|give\s+me)\s+"
    r"(?:a\s+|an\s+|the\s+|me\s+|some\s+)?"
    r"(?:python|javascript|typescript|rust|go(?:lang)?|c\+\+|java|swift|ruby|php|sql|bash|shell|html|css|react|vue|node\.?js|jsx|tsx)?\s*"
    r"(?:code|script|function|method|class|module|program|snippet|component|hook|cli|util(?:ity)?|library|api|endpoint|regex|query|algorithm|implementation)"
)

_CODE_PATTERNS = re.compile(
    rf"\b(?:{_CODE_VERBS}"
    r"|(?:debug|fix|refactor|optimi[sz]e|rewrite|port|convert|translate)\s+(?:this|the|my)?\s*(?:code|function|script|class|module|component|file|snippet|regex|query)"
    rf"|code\s+(?:up|review|for|that|to|in)\b"
    rf"|(?:in|using|with)\s+(?:{_CODE_LANGUAGES})\b"
    r"|write\s+(?:a\s+|the\s+)?unit\s+test"
    r"|implement\s+(?:a\s+|an\s+|the\s+)?(?:function|class|method|algorithm|feature)"
    r")",
    re.IGNORECASE,
)

_SIMPLE_PATTERNS = re.compile(
    r"^(?:what time|what day|what date|what's the time|what's the date"
    r"|who is \w+$|what is \w+$"
    r"|^(?:hi|hello|hey|yo|sup|thanks|thank you|good (?:morning|afternoon|evening|night))"
    r"|^(?:yes|no|yeah|nah|sure|okay|ok|nope|yep|go ahead|cancel|stop|never ?mind)"
    r"|tell me a joke|how are you|what can you do"
    r"|^open\b|^close\b|^search\b|^play\b|^launch\b|^start\b)",
    re.IGNORECASE,
)

_COMPLEX_PATTERNS = re.compile(
    r"\b(?:explain\s+(?:how|why|the|in detail)|compare\b.*\band\b"
    r"|write\s+(?:a|an|the|me)\b|create\s+(?:a|an)\b"
    r"|debug\b|refactor\b|analyze\s+(?:this|the|my)\b"
    r"|plan\b.*\bfor\b|build\s+(?:a|an|me)\b"
    r"|summarize\s+(?:this|the|my)\b|draft\s+(?:a|an)\b"
    r"|design\b|implement\b|optimize\b|review\b"
    r"|(?:essay|report|outline|proposal|presentation)\b)",
    re.IGNORECASE,
)

_WORD_SPLIT = re.compile(r"\s+")


def classify_task(input_text: str) -> str:
    text = input_text.strip()
    if not text:
        return "simple"

    if _VISION_PATTERNS.search(text):
        return "vision"

    # Code wins over complex/normal — coder-specialist models give the best output.
    if _CODE_PATTERNS.search(text):
        return "code"

    word_count = len(_WORD_SPLIT.split(text))

    if word_count > 50:
        return "complex"

    if _COMPLEX_PATTERNS.search(text):
        return "complex"

    if word_count <= 12 and _SIMPLE_PATTERNS.search(text):
        return "simple"

    return "normal"
