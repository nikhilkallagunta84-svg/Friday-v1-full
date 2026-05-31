from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote_plus, urlparse

from friday.google_accounts import preferred_google_url


SITE_SEARCH_HOSTS = {
    "ap classroom": "myap.collegeboard.org",
    "apple": "apple.com",
    "canva": "canva.com",
    "college board": "collegeboard.org",
    "docs": "docs.google.com",
    "drive": "drive.google.com",
    "dropbox": "dropbox.com",
    "ebay": "ebay.com",
    "espn": "espn.com",
    "facebook": "facebook.com",
    "fb": "facebook.com",
    "figma": "figma.com",
    "gmail": "mail.google.com",
    "google classroom": "classroom.google.com",
    "google docs": "docs.google.com",
    "google drive": "drive.google.com",
    "google maps": "google.com/maps",
    "google sheets": "sheets.google.com",
    "google slides": "slides.google.com",
    "khan academy": "khanacademy.org",
    "linkedin": "linkedin.com",
    "medium": "medium.com",
    "notion": "notion.so",
    "openai": "openai.com",
    "pinterest": "pinterest.com",
    "snapchat": "snapchat.com",
    "soundcloud": "soundcloud.com",
    "stack overflow": "stackoverflow.com",
    "stackoverflow": "stackoverflow.com",
    "threads": "threads.net",
    "twitch": "twitch.tv",
    "yahoo": "yahoo.com",
    "zoom": "zoom.us",
}


class BrowserTool:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self._opener = shutil.which("open")
        self._node = shutil.which("node")
        self._python = str(root_dir / ".venv" / "bin" / "python") if (root_dir / ".venv" / "bin" / "python").exists() else (shutil.which("python3") or "python3")
        self._node_playwright_available: bool | None = None
        self._python_playwright_available_cache: bool | None = None

    def open_page(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        url = str(parameters.get("url", "")).strip()
        url = self._normalize_url(url)
        url = preferred_google_url(url)
        browser = str(parameters.get("browser") or "").strip()
        dry_run = bool(parameters.get("dry_run", False))
        if not self._valid_url(url):
            return self._failure("Browser URL must start with http:// or https://.")
        visible = bool(parameters.get("visible", True))
        headless = bool(parameters.get("headless", False))
        browser_name = self._browser_app_name(browser)
        if dry_run:
            return self._success(
                f"Open-page request parsed for {browser_name or 'default browser'}.",
                {"url": url, "browser": browser_name or browser, "dry_run": True},
            )
        if visible and not headless:
            if self._opener:
                try:
                    command = [self._opener]
                    if browser_name:
                        command.extend(["-a", browser_name])
                    command.append(url)
                    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    label = browser_name or "your default browser"
                    return self._success(f"Opened URL in {label}.", {"url": url, "browser": browser_name or browser})
                except OSError as exc:
                    return self._failure(f"Could not open URL: {exc}")
        if self._playwright_available():
            script = (
                "const { chromium } = require('playwright');"
                "(async()=>{"
                f"const browser=await chromium.launch({{headless:{str(headless).lower()}}});"
                "const page=await browser.newPage();"
                f"await page.goto({json.dumps(url)}, {{waitUntil:'domcontentloaded', timeout:30000}});"
                "console.log(await page.title());"
                "await browser.close();"
                "})();"
            )
            completed = subprocess.run(
                ["node", "-e", script],
                cwd=str(self.root_dir),
                capture_output=True,
                text=True,
                timeout=45,
            )
            return {
                "success": completed.returncode == 0,
                "requires_confirmation": False,
                "message": "Browser navigation completed." if completed.returncode == 0 else "Browser navigation failed.",
                "data": {"url": url, "stdout": completed.stdout[-2000:], "stderr": completed.stderr[-2000:]},
            }
        if self._python_playwright_available():
            script = (
                "from playwright.sync_api import sync_playwright\n"
                f"url = {json.dumps(url)}\n"
                f"headless = {json.dumps(headless)}\n"
                "with sync_playwright() as p:\n"
                "    browser = p.chromium.launch(headless=headless)\n"
                "    page = browser.new_page()\n"
                "    page.goto(url, wait_until='domcontentloaded', timeout=30000)\n"
                "    print(page.title())\n"
                "    browser.close()\n"
            )
            completed = self._run_python_script(script, timeout=45)
            return {
                "success": completed.returncode == 0,
                "requires_confirmation": False,
                "message": "Browser navigation completed." if completed.returncode == 0 else "Browser navigation failed.",
                "data": {"url": url, "stdout": completed.stdout[-2000:], "stderr": completed.stderr[-2000:]},
            }
        if not self._opener:
            return self._failure("Playwright is not installed and macOS open is unavailable.")
        subprocess.Popen([self._opener, url])
        return self._success("Opened URL with the macOS browser launcher.", {"url": url})

    def search(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        query = str(parameters.get("query", "")).strip()
        engine = str(parameters.get("engine", "google")).strip().lower()
        browser = str(parameters.get("browser") or "").strip()
        dry_run = bool(parameters.get("dry_run", False))
        if not query:
            return self._failure("Search query cannot be empty.")
        url = self._search_url(engine, query)
        open_parameters: Dict[str, Any] = {"url": url, "visible": True}
        if browser:
            open_parameters["browser"] = browser
        if dry_run:
            open_parameters["dry_run"] = True
        result = self.open_page(open_parameters)
        if result["success"]:
            browser_name = self._browser_app_name(browser)
            suffix = f" in {browser_name}" if browser_name else ""
            result["message"] = f"Opened {engine} search results{suffix}."
            result["data"]["query"] = query
            result["data"]["engine"] = engine
            if browser_name:
                result["data"]["browser"] = browser_name
        return result

    def close_tab(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        target = str(parameters.get("target") or parameters.get("query") or parameters.get("title") or "").strip()
        url = str(parameters.get("url") or "").strip()
        browser = str(parameters.get("browser") or "").strip()
        current = bool(parameters.get("current", False))
        close_all = bool(parameters.get("all", False))
        dry_run = bool(parameters.get("dry_run", False))
        if not target and not url and not current:
            return self._failure("Tell me which browser tab to close.")
        if dry_run:
            return self._success(
                "Close-tab request parsed.",
                {"target": target, "url": url, "browser": browser, "current": current, "all": close_all, "dry_run": True},
            )
        if not shutil.which("osascript"):
            return self._failure("Closing browser tabs requires macOS osascript.")

        browsers = self._browser_candidates(browser)
        errors: list[str] = []
        no_match_browsers: list[str] = []
        for browser_name in browsers:
            completed = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", self._close_tab_jxa(browser_name, target, url, current, close_all)],
                capture_output=True,
                text=True,
                timeout=8,
            )
            stdout = completed.stdout.strip()
            if completed.returncode != 0:
                errors.append(f"{browser_name} could not be inspected")
                continue
            try:
                payload = json.loads(stdout) if stdout else {}
            except json.JSONDecodeError:
                payload = {}
            if payload.get("closed"):
                count = int(payload.get("count") or 1)
                title = str(payload.get("title") or target or "current tab")
                message = f"Closed {count} browser tabs matching {target}." if close_all and count != 1 else f"Closed browser tab: {title}."
                return self._success(
                    message,
                    {
                        "target": target,
                        "url": payload.get("url", url),
                        "title": title,
                        "browser": browser_name,
                        "current": current,
                        "all": close_all,
                        "count": count,
                    },
                )
            if payload.get("not_running"):
                continue
            if payload.get("not_found"):
                continue
            if payload.get("unsupported"):
                errors.append(f"{browser_name} could not expose tabs to automation")
            else:
                no_match_browsers.append(browser_name)

        if no_match_browsers:
            label = target or url or "that request"
            return self._failure(f"I couldn't find a matching browser tab for {label}.")
        detail = "; ".join(item for item in errors if item) or "No matching browser tab was found."
        return self._failure(f"I could not close that browser tab. {detail}")

    def switch_tab(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        target = str(parameters.get("target") or parameters.get("query") or parameters.get("title") or "").strip()
        url = str(parameters.get("url") or "").strip()
        browser = str(parameters.get("browser") or "").strip()
        dry_run = bool(parameters.get("dry_run", False))
        if not target and not url:
            return self._failure("Tell me which browser tab to switch to.")
        if dry_run:
            return self._success(
                "Switch-tab request parsed.",
                {"target": target, "url": url, "browser": browser, "dry_run": True},
            )
        if not shutil.which("osascript"):
            return self._failure("Switching browser tabs requires macOS osascript.")

        browsers = self._browser_candidates(browser)
        errors: list[str] = []
        for browser_name in browsers:
            completed = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", self._switch_tab_jxa(browser_name, target, url)],
                capture_output=True,
                text=True,
                timeout=8,
            )
            stdout = completed.stdout.strip()
            if completed.returncode != 0:
                errors.append(f"{browser_name}: {completed.stderr.strip()}")
                continue
            try:
                payload = json.loads(stdout) if stdout else {}
            except json.JSONDecodeError:
                payload = {}
            if payload.get("switched"):
                title = str(payload.get("title") or target or "matching tab")
                return self._success(
                    f"Switched to browser tab: {title}.",
                    {
                        "target": target,
                        "url": payload.get("url", url),
                        "title": title,
                        "browser": browser_name,
                    },
                )
            if payload.get("not_running"):
                errors.append(f"{browser_name} is not running")
            elif payload.get("unsupported"):
                errors.append(f"{browser_name} does not expose tabs to automation")
            else:
                errors.append(f"{browser_name}: no matching tab")

        detail = "; ".join(item for item in errors if item) or "No matching tab was found."
        return self._failure(f"I could not switch to that browser tab. {detail}")

    def extract_text(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        url = str(parameters.get("url", "")).strip()
        if not self._valid_url(url):
            return self._failure("Browser URL must start with http:// or https://.")
        if not self._playwright_available():
            if not self._python_playwright_available():
                return self._failure("Playwright is not installed. Install the Python playwright package to enable extraction.")
            script = (
                "from playwright.sync_api import sync_playwright\n"
                f"url = {json.dumps(url)}\n"
                "with sync_playwright() as p:\n"
                "    browser = p.chromium.launch(headless=True)\n"
                "    page = browser.new_page()\n"
                "    page.goto(url, wait_until='domcontentloaded', timeout=30000)\n"
                "    print(page.locator('body').inner_text(timeout=10000)[:8000])\n"
                "    browser.close()\n"
            )
            completed = self._run_python_script(script, timeout=45)
            return {
                "success": completed.returncode == 0,
                "requires_confirmation": False,
                "message": "Page text extracted." if completed.returncode == 0 else "Page extraction failed.",
                "data": {"url": url, "text": completed.stdout[-8000:], "stderr": completed.stderr[-2000:]},
            }
        script = (
            "const { chromium } = require('playwright');"
            "(async()=>{"
            "const browser=await chromium.launch({headless:true});"
            "const page=await browser.newPage();"
            f"await page.goto({json.dumps(url)}, {{waitUntil:'domcontentloaded', timeout:30000}});"
            "const text=await page.locator('body').innerText({timeout:10000});"
            "console.log(text.slice(0,8000));"
            "await browser.close();"
            "})();"
        )
        completed = subprocess.run(["node", "-e", script], cwd=str(self.root_dir), capture_output=True, text=True, timeout=45)
        return {
            "success": completed.returncode == 0,
            "requires_confirmation": False,
            "message": "Page text extracted." if completed.returncode == 0 else "Page extraction failed.",
            "data": {"url": url, "text": completed.stdout[-8000:], "stderr": completed.stderr[-2000:]},
        }

    def _browser_candidates(self, requested: str) -> list[str]:
        requested_name = self._browser_app_name(requested)
        if requested_name:
            return [requested_name]
        if "edge" in " ".join(requested.lower().split()):
            return ["Microsoft Edge"]
        preferred = ["Google Chrome", "Safari", "Microsoft Edge"]
        running = [name for name in preferred if self._browser_is_running(name)]
        return running or preferred

    def _browser_app_name(self, requested: str) -> str:
        clean = " ".join(requested.lower().split())
        aliases = {
            "chrome": "Google Chrome",
            "google chrome": "Google Chrome",
            "safari": "Safari",
            "edge": "Microsoft Edge",
            "microsoft edge": "Microsoft Edge",
        }
        return aliases.get(clean, "")

    def _browser_is_running(self, browser_name: str) -> bool:
        if not shutil.which("osascript"):
            return False
        script = f"""
try {{
  Application({json.dumps(browser_name)}).running();
}} catch (error) {{
  false;
}}
"""
        try:
            completed = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", script],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except BaseException:
            return False
        return completed.returncode == 0 and completed.stdout.strip().lower() == "true"

    def _search_url(self, engine: str, query: str) -> str:
        engine = " ".join(engine.lower().strip().split())
        engine = {
            "git hub": "github",
            "spotfy": "spotify",
            "spotifiy": "spotify",
            "spotufy": "spotify",
            "you tube": "youtube",
            "tik tok": "tiktok",
            "duck duck go": "duckduckgo",
            "chat gpt": "chatgpt",
        }.get(engine, engine)
        encoded = quote_plus(query)
        routes = {
            "youtube": f"https://www.youtube.com/results?search_query={encoded}",
            "yt": f"https://www.youtube.com/results?search_query={encoded}",
            "reddit": f"https://www.reddit.com/search/?q={encoded}",
            "instagram": f"https://www.instagram.com/explore/search/keyword/?q={encoded}",
            "insta": f"https://www.instagram.com/explore/search/keyword/?q={encoded}",
            "ig": f"https://www.instagram.com/explore/search/keyword/?q={encoded}",
            "spotify": f"https://open.spotify.com/search/{encoded}",
            "github": f"https://github.com/search?q={encoded}",
            "amazon": f"https://www.amazon.com/s?k={encoded}",
            "walmart": f"https://www.walmart.com/search?q={encoded}",
            "target": f"https://www.target.com/s?searchTerm={encoded}",
            "wikipedia": f"https://www.wikipedia.org/search-redirect.php?search={encoded}",
            "tiktok": f"https://www.tiktok.com/search?q={encoded}",
            "x": f"https://x.com/search?q={encoded}&src=typed_query",
            "twitter": f"https://x.com/search?q={encoded}&src=typed_query",
            "facebook": f"https://www.facebook.com/search/top?q={encoded}",
            "fb": f"https://www.facebook.com/search/top?q={encoded}",
            "linkedin": f"https://www.linkedin.com/search/results/all/?keywords={encoded}",
            "stackoverflow": f"https://stackoverflow.com/search?q={encoded}",
            "stack overflow": f"https://stackoverflow.com/search?q={encoded}",
            "pinterest": f"https://www.pinterest.com/search/pins/?q={encoded}",
            "soundcloud": f"https://soundcloud.com/search?q={encoded}",
            "twitch": f"https://www.twitch.tv/search?term={encoded}",
            "medium": f"https://medium.com/search?q={encoded}",
            "canva": f"https://www.canva.com/search/templates?q={encoded}",
            "figma": f"https://www.figma.com/community/search?query={encoded}",
            "khan academy": f"https://www.khanacademy.org/search?page_search_query={encoded}",
            "ebay": f"https://www.ebay.com/sch/i.html?_nkw={encoded}",
            "bing": f"https://www.bing.com/search?q={encoded}",
            "duckduckgo": f"https://duckduckgo.com/?q={encoded}",
            "duck duck go": f"https://duckduckgo.com/?q={encoded}",
            "yahoo": f"https://search.yahoo.com/search?p={encoded}",
            "google": f"https://www.google.com/search?q={encoded}",
        }
        if engine in routes:
            return routes[engine]
        if engine in SITE_SEARCH_HOSTS:
            return f"https://www.google.com/search?q={quote_plus(f'site:{SITE_SEARCH_HOSTS[engine]} {query}')}"
        domain = self._engine_domain(engine)
        if domain:
            return f"https://www.google.com/search?q={quote_plus(f'site:{domain} {query}')}"
        return f"https://www.google.com/search?q={quote_plus(f'{engine} {query}'.strip())}"

    def _engine_domain(self, engine: str) -> str:
        clean = engine.strip().strip(" .")
        if not clean or " " in clean:
            return ""
        if clean.startswith(("http://", "https://")):
            parsed = urlparse(clean)
            return parsed.netloc.lower().removeprefix("www.")
        if "." not in clean:
            return ""
        parsed = urlparse(f"https://{clean}")
        return parsed.netloc.lower().removeprefix("www.")

    def _close_tab_jxa(self, browser_name: str, target: str, url: str, current: bool, close_all: bool = False) -> str:
        return f"""
(function() {{
try {{
const app = Application({json.dumps(browser_name)});
app.includeStandardAdditions = true;
const target = {json.dumps(target.lower())};
const targetUrl = {json.dumps(url.lower())};
const closeCurrent = {json.dumps(current)};
const closeAll = {json.dumps(close_all)};

function result(payload) {{
  return JSON.stringify(payload);
}}

function norm(value) {{
  try {{
    return String(value || "").toLowerCase();
  }} catch (error) {{
    return "";
  }}
}}

function compact(value) {{
  return norm(value).replace(/[^a-z0-9]+/g, "");
}}

function urlKey(value) {{
  return norm(value)
    .replace(/^https?:\\/\\//, "")
    .replace(/^www\\./, "")
    .replace(/\\/+$/, "");
}}

function urlHostKey(value) {{
  return urlKey(value).split(/[/?#]/)[0];
}}

function aliasesFor(value) {{
  const key = compact(value);
  const aliases = {{
    youtube: ["youtube", "youtubecom", "youtu"],
    yt: ["youtube", "youtubecom", "youtu"],
    instagram: ["instagram", "instagramcom"],
    insta: ["instagram", "instagramcom"],
    ig: ["instagram", "instagramcom"],
    google: ["google", "googlecom"],
    gmail: ["gmail", "mailgoogle"],
    spotify: ["spotify", "spotifycom", "openspotify"],
    chatgpt: ["chatgpt", "chatgptcom"],
    reddit: ["reddit", "redditcom"],
    github: ["github", "githubcom"],
    classroom: ["classroomgoogle", "googleclassroom"],
  }};
  return aliases[key] || [key];
}}

function matches(title, url) {{
  const cleanTitle = norm(title);
  const cleanUrl = norm(url);
  const cleanTarget = norm(target).replace(/\\b(the|a|an|tab|browser|website|site|page)\\b/g, " ").replace(/\\s+/g, " ").trim();
  const cleanUrlKey = urlKey(cleanUrl);
  const cleanTargetUrlKey = urlKey(targetUrl);
  const cleanTargetHostKey = urlHostKey(targetUrl);
  if (cleanTargetUrlKey && cleanUrlKey.includes(cleanTargetUrlKey)) return true;
  if (cleanTargetHostKey && cleanUrlKey.includes(cleanTargetHostKey)) return true;
  if (!cleanTarget) return false;
  if (cleanTitle.includes(cleanTarget) || cleanUrl.includes(cleanTarget)) return true;
  const compactTarget = compact(cleanTarget);
  const compactPage = compact(cleanTitle + " " + cleanUrl);
  if (compactTarget && compactPage.includes(compactTarget)) return true;
  return aliasesFor(cleanTarget).some(alias => Boolean(alias && compactPage.includes(alias)));
}}

function safeGet(getter) {{
  try {{
    return getter();
  }} catch (error) {{
    return "";
  }}
}}

function safeTabs(win) {{
  try {{
    return win.tabs();
  }} catch (error) {{
    return [];
  }}
}}

function safeTitle(tab) {{
  return safeGet(() => tab.title());
}}

function safeUrl(tab) {{
  return safeGet(() => tab.url());
}}

function activeTabFor(win) {{
  let tab = null;
  try {{
    tab = win.activeTab();
  }} catch (error) {{}}
  if (tab) return tab;
  try {{
    tab = win.currentTab();
  }} catch (error) {{}}
  if (tab) return tab;
  const tabs = safeTabs(win);
  try {{
    const index = Number(win.activeTabIndex()) - 1;
    if (index >= 0 && tabs[index]) return tabs[index];
  }} catch (error) {{}}
  return tabs[0] || null;
}}

function closeTab(tab) {{
  try {{
    tab.close();
    return true;
  }} catch (firstError) {{
    try {{
      tab.delete();
      return true;
    }} catch (secondError) {{
      return false;
    }}
  }}
}}

if (!app.running()) {{
  return result({{closed: false, not_running: true, browser: {json.dumps(browser_name)}}});
}} else {{
  const windows = app.windows();
  if (!windows.length) {{
    return result({{closed: false, browser: {json.dumps(browser_name)}}});
  }} else if (closeCurrent) {{
    const win = windows[0];
    let tab = activeTabFor(win);
    const title = tab ? String(safeTitle(tab) || "current tab") : "current tab";
    const tabUrl = tab ? String(safeUrl(tab) || "") : "";
    if (tab) closeTab(tab);
    return result({{closed: Boolean(tab), title, url: tabUrl, browser: {json.dumps(browser_name)}}});
  }} else {{
    let closed = false;
    let count = 0;
    let closedTitle = "";
    let closedUrl = "";
    for (let w = 0; w < windows.length && (!closed || closeAll); w += 1) {{
      const tabs = safeTabs(windows[w]);
      for (let i = tabs.length - 1; i >= 0; i -= 1) {{
        const tab = tabs[i];
        const title = String(safeTitle(tab) || "");
        const tabUrl = String(safeUrl(tab) || "");
        if (matches(title, tabUrl)) {{
          if (closeTab(tab)) {{
            closed = true;
            count += 1;
            closedTitle = title;
            closedUrl = tabUrl;
          }}
          if (!closeAll) break;
        }}
      }}
    }}
    return result({{closed, count, title: closedTitle, url: closedUrl, browser: {json.dumps(browser_name)}}});
  }}
}}
}} catch (error) {{
  return JSON.stringify({{closed: false, unsupported: true, error: String(error), browser: {json.dumps(browser_name)}}});
}}
}})();
"""

    def _switch_tab_jxa(self, browser_name: str, target: str, url: str) -> str:
        return f"""
const app = Application({json.dumps(browser_name)});
app.includeStandardAdditions = true;
const target = {json.dumps(target.lower())};
const targetUrl = {json.dumps(url.lower())};

function result(payload) {{
  return JSON.stringify(payload);
}}

function norm(value) {{
  return String(value || "").toLowerCase();
}}

function compact(value) {{
  return norm(value).replace(/[^a-z0-9]+/g, "");
}}

function matches(title, url) {{
  const cleanTitle = norm(title);
  const cleanUrl = norm(url);
  const cleanTarget = norm(target).replace(/\\b(the|a|an|tab|browser|website|site|page)\\b/g, " ").replace(/\\s+/g, " ").trim();
  if (targetUrl && cleanUrl.includes(targetUrl)) return true;
  if (!cleanTarget) return false;
  if (cleanTitle.includes(cleanTarget) || cleanUrl.includes(cleanTarget)) return true;
  const compactTarget = compact(cleanTarget);
  return Boolean(compactTarget && (compact(cleanTitle).includes(compactTarget) || compact(cleanUrl).includes(compactTarget)));
}}

function activateTab(win, tab, index) {{
  let activated = false;
  try {{
    win.activeTabIndex = index + 1;
    activated = true;
  }} catch (error) {{}}
  try {{
    win.activeTab = tab;
    activated = true;
  }} catch (error) {{}}
  try {{
    win.currentTab = tab;
    activated = true;
  }} catch (error) {{}}
  try {{
    win.index = 1;
  }} catch (error) {{}}
  app.activate();
  return activated;
}}

if (!app.running()) {{
  result({{switched: false, not_running: true, browser: {json.dumps(browser_name)}}});
}} else {{
  const windows = app.windows();
  if (!windows.length) {{
    result({{switched: false, browser: {json.dumps(browser_name)}}});
  }} else {{
    let switched = false;
    let switchedTitle = "";
    let switchedUrl = "";
    for (let w = 0; w < windows.length && !switched; w += 1) {{
      const win = windows[w];
      const tabs = win.tabs();
      for (let i = 0; i < tabs.length; i += 1) {{
        const tab = tabs[i];
        const title = String(tab.title());
        const tabUrl = String(tab.url());
        if (matches(title, tabUrl)) {{
          switched = activateTab(win, tab, i);
          switchedTitle = title;
          switchedUrl = tabUrl;
          break;
        }}
      }}
    }}
    result({{switched, title: switchedTitle, url: switchedUrl, browser: {json.dumps(browser_name)}}});
  }}
}}
"""

    def _playwright_available(self) -> bool:
        if self._node_playwright_available is not None:
            return self._node_playwright_available
        if not self._node:
            self._node_playwright_available = False
            return False
        completed = subprocess.run(
            [self._node, "-e", "require('playwright'); console.log('ok')"],
            cwd=str(self.root_dir),
            capture_output=True,
            text=True,
            timeout=5,
        )
        self._node_playwright_available = completed.returncode == 0
        return self._node_playwright_available

    def _python_playwright_available(self) -> bool:
        if self._python_playwright_available_cache is not None:
            return self._python_playwright_available_cache
        completed = subprocess.run(
            [self._python_path(), "-c", "import playwright; print('ok')"],
            cwd=str(self.root_dir),
            capture_output=True,
            text=True,
            timeout=5,
        )
        self._python_playwright_available_cache = completed.returncode == 0
        return self._python_playwright_available_cache

    def _python_path(self) -> str:
        return self._python

    def _run_python_script(self, script: str, timeout: int) -> subprocess.CompletedProcess[str]:
        python = self._python_path()
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as script_file:
            script_file.write(script)
            script_path = script_file.name
        try:
            return subprocess.run(
                [python, script_path],
                cwd=str(self.root_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

    def _valid_url(self, url: str) -> bool:
        return url.startswith("http://") or url.startswith("https://")

    def _normalize_url(self, url: str) -> str:
        clean = url.strip()
        if not clean:
            return clean
        if clean.startswith(("http://", "https://")):
            return clean
        if "." not in clean:
            clean = clean + ".com"
        return "https://" + clean

    def _success(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "requires_confirmation": False, "message": message, "data": data}

    def _failure(self, message: str) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": False, "message": message, "data": {}}
