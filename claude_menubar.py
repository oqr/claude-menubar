#!/usr/bin/env python3
"""Claude Usage Menu Bar App for macOS.

Two data sources, merged every poll cycle:
1. Session data from Claude Code's status line (/tmp/claude-menubar-data.json)
2. Rate limit data from the Anthropic OAuth API (polled independently)

The app can run standalone (API polling only) even when no Claude Code
session is active.
"""

import json
import os
import subprocess
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

import rumps

DATA_FILE = "/tmp/claude-menubar-data.json"
USAGE_CACHE = "/tmp/claude-usage-cache.json"
HISTORY_FILE = os.path.expanduser("~/.claude/usage-history.json")
KEYCHAIN_SERVICE = "Claude Code-credentials"
REFRESH_SCRIPT = os.path.expanduser("~/.claude/refresh-token.sh")
API_URL = "https://api.anthropic.com/api/oauth/usage"

# Poll intervals
SESSION_POLL_SECS = 3       # check session data file
API_POLL_SECS = 300          # poll API every 5 min
API_RETRY_SECS = 30          # retry on failure
API_MAX_RETRIES = 5          # retries before falling back to normal interval

# Template icon lives next to this script (or in PyInstaller temp dir)
if getattr(sys, "frozen", False):
    _HERE = Path(sys._MEIPASS)
else:
    _HERE = Path(__file__).parent
ICON_FILE = str(_HERE / "icon_template@2x.png")


# ---- Helpers ----

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def format_tokens(n):
    if not n:
        return "0"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def parse_reset_time(val):
    """Convert a reset timestamp to epoch seconds.

    Handles:
    - None / falsy -> None
    - Already a number (epoch seconds or ms) -> epoch seconds
    - ISO 8601 string -> epoch seconds
    """
    if not val:
        return None
    # Already numeric
    if isinstance(val, (int, float)):
        # If looks like milliseconds (13+ digits), convert
        if val > 1e12:
            return val / 1000
        return val
    # ISO string
    if isinstance(val, str):
        try:
            from datetime import datetime, timezone
            # Handle Z suffix
            s = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            return dt.timestamp()
        except (ValueError, TypeError):
            return None
    return None


def format_reset(epoch):
    """Format reset time as relative duration."""
    if not epoch:
        return "?"
    try:
        now = time.time()
        delta_secs = int(epoch - now)
        if delta_secs < 0:
            return "now"
        hours = delta_secs // 3600
        mins = (delta_secs % 3600) // 60
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"
    except Exception:
        return "?"


def bar_text(pct, width=10):
    if pct is None:
        return "░" * width
    pct = max(0, min(100, int(pct)))
    filled = round(pct * width / 100)
    return "█" * filled + "░" * (width - filled)


def color_dot(pct):
    if pct is None:
        return "⚪"
    if pct >= 80:
        return "🔴"
    if pct >= 50:
        return "🟡"
    return "🟢"


# ---- API Polling ----

def get_oauth_token():
    """Read OAuth access token from macOS keychain."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None, None
        creds = json.loads(result.stdout.strip())
        oauth = creds.get("claudeAiOauth", {})
        return oauth.get("accessToken"), oauth
    except Exception:
        return None, None


def refresh_token():
    """Run the refresh script if token is expired."""
    try:
        subprocess.run(
            ["sh", REFRESH_SCRIPT],
            capture_output=True, timeout=15,
        )
    except Exception:
        pass


def fetch_usage_api():
    """Hit the Anthropic usage API and return parsed data, or None on failure."""
    import urllib.request
    import urllib.error

    token, oauth_meta = get_oauth_token()
    if not token:
        return None

    # Check if token is expired, try refresh
    expires_at = (oauth_meta or {}).get("expiresAt", 0)
    now_ms = int(time.time() * 1000)
    if expires_at and expires_at < now_ms + 60000:
        refresh_token()
        token, oauth_meta = get_oauth_token()
        if not token:
            return None

    req = urllib.request.Request(API_URL, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None

    if "five_hour" not in data:
        return None

    # Parse into our cache format
    result = {
        "five_hour": data.get("five_hour", {}).get("utilization"),
        "five_hour_resets": data.get("five_hour", {}).get("resets_at"),
        "seven_day": data.get("seven_day", {}).get("utilization"),
        "seven_day_resets": data.get("seven_day", {}).get("resets_at"),
        "seven_day_sonnet": None,
        "extra_usage_enabled": False,
        "extra_usage_credits": None,
        "extra_usage_limit": None,
        "plan": (oauth_meta or {}).get("subscriptionType", ""),
        "rate_limit_tier": (oauth_meta or {}).get("rateLimitTier", ""),
        "ts": time.time(),
    }

    # Sonnet breakdown
    ss = data.get("seven_day_sonnet")
    if ss:
        result["seven_day_sonnet"] = ss.get("utilization")

    # Extra usage / overuse credits
    eu = data.get("extra_usage")
    if eu:
        result["extra_usage_enabled"] = eu.get("is_enabled", False)
        result["extra_usage_credits"] = eu.get("used_credits")
        result["extra_usage_limit"] = eu.get("monthly_limit")

    # Write cache for statusline script to also use
    save_json(USAGE_CACHE, result)
    return result


# ---- Menu Bar App ----

class ClaudeMenuBar(rumps.App):
    def __init__(self):
        icon = ICON_FILE if os.path.exists(ICON_FILE) else None
        super().__init__("✦", icon=icon, template=True, quit_button=None)
        self.title = "✦ ..." if not icon else None
        self._last_session_id = None
        self._history = load_json(HISTORY_FILE) or {
            "total_cost_usd": 0, "total_input_tokens": 0,
            "total_output_tokens": 0, "sessions": 0, "first_seen": None,
        }
        self._data = None
        self._usage = None  # latest API usage data
        self._api_retries = 0

        # Session section
        self.model_item = rumps.MenuItem("  Model: ...")
        self.folder_item = rumps.MenuItem("  Project: ...")
        self.tokens_item = rumps.MenuItem("  Tokens: ...")
        self.context_item = rumps.MenuItem("  Context: ...")

        # Rate limits section
        self.plan_item = rumps.MenuItem("  Plan: ...")
        self.five_hour_item = rumps.MenuItem("  5h: ...")
        self.five_hour_reset = rumps.MenuItem("    Resets: ...")
        self.seven_day_item = rumps.MenuItem("  7d: ...")
        self.seven_day_reset = rumps.MenuItem("    Resets: ...")
        self.sonnet_item = rumps.MenuItem("  Sonnet 7d: ...")
        self.extra_usage_item = rumps.MenuItem("  Extra usage: ...")

        # Footer
        self.updated_item = rumps.MenuItem("Updated: never")
        self.status_item = rumps.MenuItem("Status: waiting for data")
        self.auth_item = rumps.MenuItem("")  # hidden until needed
        self.refresh_item = rumps.MenuItem("Refresh Now", callback=self.manual_refresh)
        self.quit_item = rumps.MenuItem("Quit", callback=self.quit_app)
        self._auth_warning_shown = False

        self.menu = [
            rumps.MenuItem("SESSION"),
            self.model_item,
            self.folder_item,
            self.tokens_item,
            self.context_item,
            None,
            rumps.MenuItem("RATE LIMITS"),
            self.plan_item,
            self.five_hour_item,
            self.five_hour_reset,
            self.seven_day_item,
            self.seven_day_reset,
            self.sonnet_item,
            self.extra_usage_item,
            None,
            self.updated_item,
            self.status_item,
            self.auth_item,
            self.refresh_item,
            None,
            self.quit_item,
        ]

        # Start API polling in background thread
        self._start_api_poller()

    def _start_api_poller(self):
        """Background thread that polls the usage API independently."""
        def poller():
            while True:
                try:
                    result = fetch_usage_api()
                    if result:
                        self._usage = result
                        self._api_retries = 0
                        self._auth_warning_shown = False
                        self.auth_item.title = ""
                        time.sleep(API_POLL_SECS)
                    else:
                        self._api_retries += 1
                        # After 3 consecutive failures, check if token is expired
                        if self._api_retries >= 3 and not self._auth_warning_shown:
                            self._check_auth_state()
                        if self._api_retries <= API_MAX_RETRIES:
                            time.sleep(API_RETRY_SECS)
                        else:
                            time.sleep(API_POLL_SECS)
                except Exception:
                    time.sleep(API_POLL_SECS)

        t = threading.Thread(target=poller, daemon=True)
        t.start()

    def _check_auth_state(self):
        """Check if token is expired and warn user."""
        _, oauth = get_oauth_token()
        if not oauth:
            self.auth_item.title = "⚠️  No credentials. Run: claude /login"
            self._auth_warning_shown = True
            return
        expires_at = oauth.get("expiresAt", 0)
        now_ms = int(time.time() * 1000)
        if expires_at < now_ms:
            hours_ago = (now_ms - expires_at) / 3600000
            self.auth_item.title = f"⚠️  Token expired {hours_ago:.0f}h ago. Run: claude /login"
            self._auth_warning_shown = True

    def manual_refresh(self, _):
        """Trigger an immediate API refresh."""
        self.status_item.title = "Status: refreshing..."
        threading.Thread(target=self._do_manual_refresh, daemon=True).start()

    def _do_manual_refresh(self):
        refresh_token()
        result = fetch_usage_api()
        if result:
            self._usage = result
            self._api_retries = 0

    @rumps.timer(SESSION_POLL_SECS)
    def poll_data(self, _):
        """Check for updated data every few seconds."""
        data = load_json(DATA_FILE)

        # Merge API usage data (authoritative for rate limits)
        usage = self._usage or load_json(USAGE_CACHE)
        if usage:
            # Check cache freshness (10 min for file-based cache)
            cache_age = time.time() - (usage.get("ts") or 0)
            if cache_age > 600 and usage is not self._usage:
                usage = None

        if data and usage:
            data["rate_5h_pct"] = usage.get("five_hour", data.get("rate_5h_pct"))
            data["rate_5h_resets"] = usage.get("five_hour_resets", data.get("rate_5h_resets"))
            data["rate_7d_pct"] = usage.get("seven_day", data.get("rate_7d_pct"))
            data["rate_7d_resets"] = usage.get("seven_day_resets", data.get("rate_7d_resets"))
        elif not data and usage:
            data = {
                "rate_5h_pct": usage.get("five_hour"),
                "rate_5h_resets": usage.get("five_hour_resets"),
                "rate_7d_pct": usage.get("seven_day"),
                "rate_7d_resets": usage.get("seven_day_resets"),
                "ts": usage.get("ts", 0),
            }

        if not data:
            if self._data:
                self._update_title_from_rates(self._data, active=False)
            self.status_item.title = "Status: no data"
            return

        ts = data.get("ts", 0)
        age = time.time() - ts
        active = age < 300

        self._data = data

        # Track sessions
        sid = data.get("session_id")
        if sid and sid != self._last_session_id:
            self._last_session_id = sid
            self._history["sessions"] = self._history.get("sessions", 0) + 1
            if not self._history.get("first_seen"):
                self._history["first_seen"] = datetime.now().isoformat()

        if active:
            self.status_item.title = "Status: active"
            self._update_display(data, usage)
        else:
            if usage and (time.time() - (usage.get("ts") or 0)) < 600:
                self.status_item.title = "Status: no session (API data live)"
            else:
                self.status_item.title = f"Status: idle ({int(age // 60)}m ago)"
            self._update_title_from_rates(data, active=False)
            self._update_rate_limits(data, usage)

    def _update_title_from_rates(self, d, active=True):
        pct_5h = d.get("rate_5h_pct")
        pct_7d = d.get("rate_7d_pct")

        parts = []
        if pct_5h is not None:
            parts.append(f"5h {int(pct_5h)}%{color_dot(pct_5h)}")
        if pct_7d is not None:
            parts.append(f"7d {int(pct_7d)}%{color_dot(pct_7d)}")

        prefix = "" if os.path.exists(ICON_FILE) else "✦ "
        self.title = (prefix + "  ".join(parts)) if parts else (prefix + "...")

    def _update_rate_limits(self, d, usage):
        """Update rate limit menu items from merged data."""
        pct_5h = d.get("rate_5h_pct")
        pct_7d = d.get("rate_7d_pct")

        # Plan label
        if usage:
            plan = usage.get("plan", "")
            tier = usage.get("rate_limit_tier", "")
            label = self._format_plan(plan, tier)
            self.plan_item.title = f"  Plan: {label}" if label else "  Plan: ..."
        else:
            self.plan_item.title = "  Plan: ..."

        # 5-hour
        if pct_5h is not None:
            self.five_hour_item.title = f"  5h: {bar_text(pct_5h)} {int(pct_5h)}%  {color_dot(pct_5h)}"
            resets = parse_reset_time(d.get("rate_5h_resets"))
            self.five_hour_reset.title = f"    Resets in {format_reset(resets)}"
        else:
            self.five_hour_item.title = "  5h: waiting for data..."
            self.five_hour_reset.title = ""

        # 7-day
        if pct_7d is not None:
            self.seven_day_item.title = f"  7d: {bar_text(pct_7d)} {int(pct_7d)}%  {color_dot(pct_7d)}"
            resets = parse_reset_time(d.get("rate_7d_resets"))
            self.seven_day_reset.title = f"    Resets in {format_reset(resets)}"
        else:
            self.seven_day_item.title = "  7d: waiting for data..."
            self.seven_day_reset.title = ""

        # Sonnet 7d
        if usage and usage.get("seven_day_sonnet") is not None:
            spct = usage["seven_day_sonnet"]
            self.sonnet_item.title = f"  Sonnet 7d: {bar_text(spct)} {int(spct)}%  {color_dot(spct)}"
        else:
            self.sonnet_item.title = "  Sonnet 7d: --"

        # Extra usage
        if usage and usage.get("extra_usage_enabled"):
            used = usage.get("extra_usage_credits") or 0
            limit = usage.get("extra_usage_limit") or 0
            used_dollars = used / 100
            limit_dollars = limit / 100 if limit else 0
            if limit_dollars:
                self.extra_usage_item.title = f"  Extra: ${used_dollars:.2f} / ${limit_dollars:.2f}"
            else:
                self.extra_usage_item.title = f"  Extra: ${used_dollars:.2f} used"
        else:
            self.extra_usage_item.title = "  Extra usage: off"

    def _format_plan(self, plan, tier):
        """Format plan label from subscription type and rate limit tier."""
        if not plan:
            return ""
        label = plan.capitalize()
        if "20x" in (tier or ""):
            label += " 20x"
        elif "5x" in (tier or ""):
            label += " 5x"
        return label

    def _update_display(self, d, usage):
        pct_5h = d.get("rate_5h_pct")
        pct_7d = d.get("rate_7d_pct")
        ctx_pct = int(d.get("context_pct", 0))

        self._update_title_from_rates(d, active=True)

        # Session details
        self.model_item.title = f"  Model: {d.get('model', '?')}"
        self.folder_item.title = f"  Project: {d.get('folder', '?')}"

        inp = d.get("input_tokens", 0)
        out = d.get("output_tokens", 0)
        self.tokens_item.title = f"  Tokens: {format_tokens(inp)} in / {format_tokens(out)} out"

        ctx_bar = bar_text(ctx_pct, 15)
        self.context_item.title = f"  Context: {ctx_bar} {ctx_pct}%"

        # Rate limits (shared logic)
        self._update_rate_limits(d, usage)

        # Footer
        now = datetime.now().strftime("%I:%M:%S %p")
        self.updated_item.title = f"Updated {now}"

    def quit_app(self, _):
        save_json(HISTORY_FILE, self._history)
        rumps.quit_application()


if __name__ == "__main__":
    ClaudeMenuBar().run()
