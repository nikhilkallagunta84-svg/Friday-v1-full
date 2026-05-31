from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import time
from typing import Any, Callable, Dict
from urllib.parse import quote, quote_plus
from urllib.request import Request, urlopen


MEDIA_SERVICE_ALIASES = {
    "spotify": "spotify",
    "spotufy": "spotify",
    "spotfy": "spotify",
    "spotifiy": "spotify",
    "youtube": "youtube",
    "you tube": "youtube",
    "yt": "youtube",
    "soundcloud": "soundcloud",
    "sound cloud": "soundcloud",
    "tiktok": "tiktok",
    "tik tok": "tiktok",
    "twitch": "twitch",
}

MEDIA_SERVICE_LABELS = {
    "spotify": "Spotify",
    "youtube": "YouTube",
    "soundcloud": "SoundCloud",
    "tiktok": "TikTok",
    "twitch": "Twitch",
}


class SpotifyMusicTool:
    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        opener: Callable[..., subprocess.Popen[str]] | None = None,
        sleeper: Callable[[float], None] | None = None,
        system_name: str | None = None,
        youtube_resolver: Callable[[str], str] | None = None,
    ) -> None:
        self._runner = runner or subprocess.run
        self._opener = opener or subprocess.Popen
        self._sleep = sleeper or time.sleep
        self._system_name = system_name or platform.system()
        self._youtube_resolver = youtube_resolver or _resolve_youtube_first_video_url

    def play(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        service = _normalize_media_service(str(parameters.get("service") or parameters.get("app") or "spotify"))
        query = str(parameters.get("query") or parameters.get("track") or parameters.get("song") or "").strip()
        dry_run = bool(parameters.get("dry_run", False))
        label = _media_service_label(service)
        if not service:
            return self._failure("Tell me which site to play that on, sir.", {"service": str(parameters.get("service") or "")})
        if not query:
            return self._failure(f"Tell me what to play on {label}, sir.", {"service": service})
        if self._system_name != "Darwin":
            return self._failure(
                f"Playback control is only implemented for macOS right now, not {self._system_name}.",
                {"service": service, "query": query},
            )

        search_uri = f"spotify:search:{quote(query)}"
        web_url = _media_search_url(service, query)
        data = {
            "service": service,
            "query": query,
            "search_uri": search_uri,
            "web_url": web_url,
            "dry_run": dry_run,
            "autoplay_attempted": False,
            "autoplay_succeeded": False,
            "fallback": "",
        }
        if dry_run:
            return self._success(f"{label} play request parsed for {query}.", data)

        if service == "youtube":
            return self._play_youtube(query, str(parameters.get("browser") or ""), data)
        if service != "spotify":
            return self._play_web_media(service, query, str(parameters.get("browser") or ""), data)

        return self._play_spotify(query, search_uri, web_url, str(parameters.get("browser") or ""), data)

    def _play_spotify(
        self,
        query: str,
        search_uri: str,
        web_url: str,
        browser_hint: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        open_result = self._open_spotify_app()
        if not open_result["success"]:
            web_play = self._play_spotify_web(query, web_url, browser_hint)
            data.update(web_play.get("data", {}))
            if web_play["success"]:
                data["autoplay_attempted"] = True
                data["autoplay_succeeded"] = True
                data["fallback"] = "spotify_web_real_browser_click"
                return self._success(f"Playing {query} on Spotify web.", data)
            fallback = self._open_real_browser_url(web_url, browser_hint)
            data["fallback"] = "spotify_real_browser_search"
            data.update(fallback.get("data", {}))
            if fallback["success"]:
                return self._success(
                    f"I opened Spotify web search for {query}, but I need browser automation permission before I can click play automatically.",
                    {**data, "autoplay_error": web_play["message"]},
                )
            return self._failure(f"I couldn't open Spotify or Spotify web for {query}.", {**data, "error": fallback["message"]})

        playback = self._search_and_play_with_keyboard(query)
        data["autoplay_attempted"] = True
        if playback["success"]:
            data["autoplay_succeeded"] = True
            data["fallback"] = "spotify_app_keyboard"
            return self._success(f"Playing {query} on Spotify.", data)

        uri_result = self._open_spotify_uri(search_uri)
        data["spotify_uri_opened"] = bool(uri_result["success"])
        web_play = self._play_spotify_web(query, web_url, browser_hint)
        data.update(web_play.get("data", {}))
        if web_play["success"]:
            data["autoplay_succeeded"] = True
            data["fallback"] = "spotify_web_real_browser_click"
            return self._success(f"Playing {query} on Spotify web.", {**data, "app_autoplay_error": playback["message"]})
        web_result = self._open_real_browser_url(web_url, browser_hint)
        data["fallback"] = "spotify_real_browser_search"
        data.update(web_result.get("data", {}))
        if web_result["success"]:
            return self._failure(
                f"I opened Spotify search for {query}, but I couldn't click play automatically yet. Enable macOS Accessibility for Terminal/Codex and browser JavaScript automation for Chrome or Safari so I can press the first result.",
                {**data, "autoplay_error": playback["message"], "uri_error": uri_result["message"], "web_autoplay_error": web_play["message"]},
            )
        return self._failure(
            f"I opened Spotify, but I couldn't search or start {query}: {playback['message']}",
            {**data, "autoplay_error": playback["message"], "uri_error": uri_result["message"], "web_autoplay_error": web_play["message"]},
        )

    def _play_youtube(self, query: str, browser_hint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            watch_url = self._youtube_resolver(query)
        except BaseException as exc:
            watch_url = ""
            data["resolver_error"] = str(exc)
        target_url = watch_url or data["web_url"]
        open_result = self._open_real_browser_url(target_url, browser_hint)
        data.update(open_result.get("data", {}))
        data["resolved_url"] = watch_url
        data["autoplay_attempted"] = True
        data["autoplay_succeeded"] = bool(watch_url and open_result["success"])
        if watch_url and open_result["success"]:
            return self._success(f"Playing {query} on YouTube.", data)
        if open_result["success"]:
            return self._failure(
                f"I opened YouTube search for {query}, but couldn't identify the first video URL automatically.",
                data,
            )
        return self._failure(f"I couldn't open YouTube for {query}: {open_result['message']}", data)

    def _play_web_media(self, service: str, query: str, browser_hint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        label = _media_service_label(service)
        open_result = self._open_real_browser_url(data["web_url"], browser_hint)
        data.update(open_result.get("data", {}))
        data["autoplay_attempted"] = False
        data["autoplay_succeeded"] = False
        data["fallback"] = "real_browser_search"
        if open_result["success"]:
            return self._success(f"Opened {label} search for {query} in your real browser.", data)
        return self._failure(f"I couldn't open {label} for {query}: {open_result['message']}", data)

    def _open_real_browser_url(self, url: str, browser_hint: str = "") -> Dict[str, Any]:
        if not shutil.which("open"):
            return self._failure("macOS open command is unavailable.", {"url": url})
        browser_name = _browser_app_name(browser_hint) or "Google Chrome"
        command = ["open", "-a", browser_name, url] if browser_name else ["open", url]
        try:
            self._opener(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            if browser_name:
                try:
                    self._opener(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return self._success("Opened URL in your default browser.", {"url": url, "browser": ""})
                except OSError:
                    pass
            return self._failure(str(exc), {"url": url, "browser": browser_name})
        return self._success(f"Opened URL in {browser_name or 'your default browser'}.", {"url": url, "browser": browser_name})

    def _open_spotify_app(self) -> Dict[str, Any]:
        if not shutil.which("open"):
            return self._failure("macOS open command is unavailable.", {})
        completed = self._runner(["open", "-a", "Spotify"], capture_output=True, text=True, timeout=10)
        if completed.returncode == 0:
            self._sleep(1.0)
            return self._success("Opened Spotify.", {})
        return self._failure(completed.stderr.strip() or "Spotify app could not be opened.", {})

    def _search_and_play_with_keyboard(self, query: str) -> Dict[str, Any]:
        if not shutil.which("osascript"):
            return self._failure("macOS osascript is unavailable.", {})
        script = f"""
on spotifyTrackId()
  try
    tell application "Spotify"
      if player state is playing or player state is paused then
        return id of current track as text
      end if
    end tell
  end try
  return ""
end spotifyTrackId

on spotifyIsPlaying(beforeTrackId)
  try
    tell application "Spotify"
      if player state is playing then
        set afterTrackId to id of current track as text
        if beforeTrackId is "" or afterTrackId is not equal to beforeTrackId then return true
      end if
    end tell
  end try
  return false
end spotifyIsPlaying

set beforeTrackId to spotifyTrackId()
tell application "Spotify" to activate
delay 0.8
tell application "System Events"
  if UI elements enabled is false then error "Accessibility permission is required for keyboard playback control."
  keystroke "l" using command down
  delay 0.2
  keystroke {json.dumps(query)}
  delay 0.2
  key code 36
  delay 1.8
end tell

if spotifyIsPlaying(beforeTrackId) then return "playing"

tell application "System Events"
  key code 36
  delay 0.8
end tell
if spotifyIsPlaying(beforeTrackId) then return "playing"

tell application "System Events"
  key code 125
  delay 0.15
  key code 36
  delay 0.8
end tell
if spotifyIsPlaying(beforeTrackId) then return "playing"

tell application "System Events"
  key code 48
  delay 0.15
  key code 48
  delay 0.15
  key code 36
  delay 0.8
end tell
if spotifyIsPlaying(beforeTrackId) then return "playing"

tell application "System Events"
  key code 49
  delay 0.8
end tell
if spotifyIsPlaying(beforeTrackId) then return "playing"

return "not_playing"
"""
        completed = self._runner(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
        stdout = completed.stdout.strip().lower()
        if completed.returncode == 0 and "playing" in stdout and "not_playing" not in stdout:
            return self._success("Spotify keyboard playback command completed.", {})
        if completed.returncode == 0:
            return self._failure("Spotify search opened, but the first result did not start playing.", {"stdout": stdout})
        return self._failure(completed.stderr.strip() or "Spotify keyboard playback command failed.", {})

    def _play_spotify_web(self, query: str, url: str, browser_hint: str) -> Dict[str, Any]:
        if not shutil.which("osascript"):
            return self._failure("macOS osascript is unavailable.", {"url": url})
        browser_name = _browser_app_name(browser_hint) or "Google Chrome"
        if browser_name == "Safari":
            script = _safari_spotify_web_play_script(url, query)
        elif browser_name in {"Google Chrome", "Microsoft Edge"}:
            script = _chromium_spotify_web_play_script(browser_name, url, query)
        else:
            return self._failure(f"{browser_name} does not support this Spotify web control path.", {"url": url, "browser": browser_name})
        completed = self._runner(["osascript", "-e", script], capture_output=True, text=True, timeout=18)
        stdout = completed.stdout.strip()
        data = {"url": url, "browser": browser_name, "stdout": stdout[-500:]}
        if completed.returncode == 0 and stdout.lower().startswith(("clicked", "opened_link_then_clicked")):
            return self._success("Clicked the first playable Spotify web result.", data)
        message = completed.stderr.strip() or stdout or "Spotify web click did not find a playable result."
        return self._failure(message, data)

    def _open_spotify_uri(self, uri: str) -> Dict[str, Any]:
        if not shutil.which("open"):
            return self._failure("macOS open command is unavailable.", {})
        completed = self._runner(["open", uri], capture_output=True, text=True, timeout=8)
        if completed.returncode == 0:
            return self._success("Opened Spotify search URI.", {"uri": uri})
        return self._failure(completed.stderr.strip() or "Spotify search URI could not be opened.", {"uri": uri})

    def _success(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "requires_confirmation": False, "message": message, "data": data}

    def _failure(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": False, "message": message, "data": data}


def _normalize_media_service(value: str) -> str:
    clean = " ".join(value.lower().strip().split())
    return MEDIA_SERVICE_ALIASES.get(clean, "")


def _media_service_label(service: str) -> str:
    return MEDIA_SERVICE_LABELS.get(service, service.title() if service else "that site")


def _media_search_url(service: str, query: str) -> str:
    if service == "spotify":
        return f"https://open.spotify.com/search/{quote(query)}"
    encoded = quote_plus(query)
    if service == "youtube":
        return f"https://www.youtube.com/results?search_query={encoded}"
    if service == "soundcloud":
        return f"https://soundcloud.com/search?q={encoded}"
    if service == "tiktok":
        return f"https://www.tiktok.com/search?q={encoded}"
    if service == "twitch":
        return f"https://www.twitch.tv/search?term={encoded}"
    return f"https://www.google.com/search?q={encoded}"


def _resolve_youtube_first_video_url(query: str) -> str:
    search_url = _media_search_url("youtube", query)
    request = Request(
        search_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(request, timeout=8) as response:
        html = response.read().decode("utf-8", errors="ignore")
    seen: set[str] = set()
    for pattern in (r"/watch\?v=([A-Za-z0-9_-]{11})", r'"videoId":"([A-Za-z0-9_-]{11})"'):
        for video_id in re.findall(pattern, html):
            if video_id not in seen:
                seen.add(video_id)
                return f"https://www.youtube.com/watch?v={video_id}"
    return ""


def _browser_app_name(requested: str) -> str:
    clean = " ".join(requested.lower().strip().split())
    return {
        "chrome": "Google Chrome",
        "google chrome": "Google Chrome",
        "safari": "Safari",
        "edge": "Microsoft Edge",
        "microsoft edge": "Microsoft Edge",
    }.get(clean, "")


def _spotify_web_click_javascript(query: str, allow_link_click: bool = True) -> str:
    return f"""
(() => {{
  const query = {json.dumps(query)};
  const terms = query.toLowerCase().split(/\\s+/).filter((term) => term.length > 1);
  const clean = (text) => (text || '').replace(/\\s+/g, ' ').trim();
  const visible = (element) => {{
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }};
  const score = (text) => {{
    const lowered = clean(text).toLowerCase();
    return terms.reduce((total, term) => total + (lowered.includes(term) ? 1 : 0), 0);
  }};
  const badLabel = (text) => /pause|shuffle|next|previous|cookie|sign up|install|download|upgrade|spotify free/i.test(text || '');
  const containers = [
    '[role="row"]',
    '[data-testid*="track"]',
    '[data-testid*="top-result"]',
    '[data-testid*="search"]',
    'section',
    'article',
    'div'
  ];
  const playCandidates = Array.from(document.querySelectorAll('button,[role="button"]'))
    .filter((element) => {{
      const label = clean([element.getAttribute('aria-label'), element.textContent].join(' '));
      return visible(element) && /\\bplay\\b/i.test(label) && !badLabel(label);
    }})
    .map((element) => {{
      const container = element.closest(containers.join(','));
      const text = clean([element.getAttribute('aria-label'), container && container.innerText, element.textContent].join(' '));
      return {{ element, text, score: score(text) }};
    }})
    .sort((a, b) => b.score - a.score);
  const playButton = playCandidates.find((candidate) => candidate.score > 0) || playCandidates[0];
  if (playButton) {{
    playButton.element.scrollIntoView({{ block: 'center', inline: 'center' }});
    playButton.element.click();
    return 'clicked_button:' + playButton.text.slice(0, 160);
  }}
  if ({str(allow_link_click).lower()}) {{
    const linkCandidates = Array.from(document.querySelectorAll('a[href*="/track/"]'))
      .filter(visible)
      .map((element) => {{
        const container = element.closest(containers.join(','));
        const text = clean([container && container.innerText, element.textContent, element.href].join(' '));
        return {{ element, text, score: score(text) }};
      }})
      .sort((a, b) => b.score - a.score);
    const link = linkCandidates.find((candidate) => candidate.score > 0) || linkCandidates[0];
    if (link) {{
      link.element.scrollIntoView({{ block: 'center', inline: 'center' }});
      link.element.click();
      return 'opened_link:' + link.text.slice(0, 160);
    }}
  }}
  return 'no_playable_element';
}})();
""".strip()


def _chromium_spotify_web_play_script(browser_name: str, url: str, query: str) -> str:
    first_js = _spotify_web_click_javascript(query, allow_link_click=True)
    second_js = _spotify_web_click_javascript(query, allow_link_click=False)
    return f"""
set targetUrl to {json.dumps(url)}
set firstScript to {json.dumps(first_js)}
set secondScript to {json.dumps(second_js)}
tell application {json.dumps(browser_name)}
  activate
  if not (exists window 1) then make new window
  tell front window
    set targetTab to make new tab at end of tabs with properties {{URL:targetUrl}}
    set active tab index to (count of tabs)
  end tell
  repeat 40 times
    delay 0.25
    if loading of targetTab is false then exit repeat
  end repeat
  delay 2.5
  tell targetTab
    set firstResult to execute javascript firstScript
  end tell
  if firstResult starts with "opened_link" then
    delay 2
    tell targetTab
      set secondResult to execute javascript secondScript
    end tell
    if secondResult starts with "clicked" then return "opened_link_then_" & secondResult
  end if
  return firstResult
end tell
"""


def _safari_spotify_web_play_script(url: str, query: str) -> str:
    first_js = _spotify_web_click_javascript(query, allow_link_click=True)
    second_js = _spotify_web_click_javascript(query, allow_link_click=False)
    return f"""
set targetUrl to {json.dumps(url)}
set firstScript to {json.dumps(first_js)}
set secondScript to {json.dumps(second_js)}
tell application "Safari"
  activate
  if not (exists window 1) then make new document
  tell front window
    set targetTab to make new tab with properties {{URL:targetUrl}}
    set current tab to targetTab
  end tell
  delay 3
  set firstResult to do JavaScript firstScript in targetTab
  if firstResult starts with "opened_link" then
    delay 2
    set secondResult to do JavaScript secondScript in targetTab
    if secondResult starts with "clicked" then return "opened_link_then_" & secondResult
  end if
  return firstResult
end tell
"""
