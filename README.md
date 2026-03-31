# Claude Usage

A macOS menu bar app that shows your Claude Code rate limit utilization in real time.

![Menu bar showing 5h 8% and 7d 14%](https://github.com/oqr/claude-menubar/raw/main/icon_template@2x.png)

## What it shows

- **5h** — current session window utilization
- **7d** — weekly utilization
- **Sonnet 7d** — Sonnet-specific weekly utilization (when available)
- **Plan** — your subscription tier (Pro, Max, Max 5x, etc.)
- **Reset times** — when each window resets
- **Extra usage** — credit spend if you have overages enabled

Color coding: green below 50%, yellow 50-80%, red above 80%.

## How it works

The app polls the Anthropic OAuth API (`/api/oauth/usage`) on a 5-minute timer using the OAuth token that Claude Code stores in your macOS Keychain. It runs independently — no Claude Code terminal session required.

If your token expires, the menu shows a warning with instructions to re-authenticate.

## Requirements

- macOS
- Python 3.9+
- Claude Code installed and logged in (to seed the OAuth token)

## Install

```bash
git clone https://github.com/oqr/claude-menubar.git
cd claude-menubar
python3 -m venv venv
source venv/bin/activate
pip install rumps
```

To run from source:
```bash
./run.sh
```

To build a standalone `.app`:
```bash
pip install pyinstaller
pyinstaller "Claude Usage.spec" --noconfirm
cp -R dist/Claude\ Usage.app /Applications/
```

Then open `/Applications/Claude Usage.app` and allow it in System Settings > Privacy & Security if prompted.

## Auto-start on login

Add the app to Login Items in System Settings > General > Login Items.

## Token refresh

The app uses your Claude Code OAuth token from the macOS Keychain. Tokens expire after several hours. A companion script (`~/.claude/refresh-token.sh`) can refresh them automatically using the same refresh flow Claude Code uses internally.

If you see a "Token expired" warning in the menu, run `claude /login` in a terminal to get a fresh token.

## Claude Code status line integration

For live context window usage directly in your terminal, add this to your Claude Code settings:

```json
{
  "statusCommand": "sh ~/.claude/statusline-command.sh"
}
```

The `statusline-command.sh` script (not included here — lives at `~/.claude/`) writes session data to `/tmp/claude-menubar-data.json` which the menu bar app reads.

## Alternative: browser userscript

`claude-usage-reporter.user.js` is a Tampermonkey userscript that pulls usage data directly from claude.ai and forwards it to the menu bar app via a local HTTP endpoint. Useful if the OAuth approach stops working.

Requires:
- [Tampermonkey](https://www.tampermonkey.net/) browser extension
- `usage_server.py` running locally: `python usage_server.py &`

## Files

| File | Purpose |
|------|---------|
| `claude_menubar.py` | Main menu bar app |
| `Claude Usage.spec` | PyInstaller build config |
| `run.sh` | Run from source |
| `fetch_usage.py` | Standalone cookie-based fetcher (alternative to OAuth) |
| `claude-usage-reporter.user.js` | Browser userscript |
| `usage_server.py` | Local HTTP server for userscript |
| `make_icon.py` | Icon generation |

## Credits

OAuth API approach inspired by [Claude-Usage-Systray](https://github.com/albazzaztariq/Claude-Usage-Systray) (Windows) by albazzaztariq.
