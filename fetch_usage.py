#!/usr/bin/env python3
"""Fetch Claude usage data from claude.ai API using desktop app cookies.

Reads the sessionKey from the Claude desktop app's Electron cookie store,
decrypts it, and calls the same API endpoint that claude.ai/settings/usage uses.

On first run, macOS will prompt for Keychain access -- click "Always Allow"
so subsequent runs work silently.

Writes result to /tmp/claude-usage-cache.json in the format expected by
the statusline script and menu bar app.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime, timezone

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

COOKIE_DB = os.path.expanduser("~/Library/Application Support/Claude/Cookies")
BOOTSTRAP_URL = "https://claude.ai/api/bootstrap"
# ORG_ID is discovered at runtime from the bootstrap API using your session cookie
CACHE_FILE = "/tmp/claude-usage-cache.json"

# Keychain service names to try (Electron apps vary)
KEYCHAIN_NAMES = ["Claude Safe Storage", "Electron Safe Storage", "Claude"]


def get_encryption_key():
    """Get the cookie encryption key from macOS Keychain."""
    for name in KEYCHAIN_NAMES:
        try:
            key_bytes = subprocess.check_output(
                ["security", "find-generic-password", "-s", name, "-w"],
                stderr=subprocess.DEVNULL,
            ).strip()
            return key_bytes
        except subprocess.CalledProcessError:
            continue
    raise RuntimeError("Could not find cookie encryption key in Keychain")


def decrypt_cookie(encrypted_value, key_bytes):
    """Decrypt a Chrome/Electron cookie value (macOS)."""
    derived = hashlib.pbkdf2_hmac("sha1", key_bytes, b"saltysalt", 1003, dklen=16)

    if encrypted_value[:3] == b"v10":
        iv = b" " * 16
        cipher = Cipher(algorithms.AES(derived), modes.CBC(iv), backend=default_backend())
        dec = cipher.decryptor()
        plaintext = dec.update(encrypted_value[3:]) + dec.finalize()
        # PKCS7 padding removal
        pad = plaintext[-1]
        if isinstance(pad, int) and 1 <= pad <= 16:
            plaintext = plaintext[:-pad]
        return plaintext.decode("utf-8")
    raise ValueError(f"Unknown encryption version: {encrypted_value[:3]}")


def get_session_cookie():
    """Extract and decrypt the sessionKey cookie from Claude desktop app."""
    key = get_encryption_key()

    # Copy DB (original may be locked by running app)
    tmp = tempfile.mktemp(suffix=".db")
    shutil.copy2(COOKIE_DB, tmp)

    try:
        conn = sqlite3.connect(tmp)
        cur = conn.cursor()
        cur.execute(
            "SELECT encrypted_value FROM cookies "
            "WHERE (host_key='.claude.ai' OR host_key='claude.ai') "
            "AND name='sessionKey'"
        )
        row = cur.fetchone()
        conn.close()
    finally:
        os.unlink(tmp)

    if not row:
        raise RuntimeError("sessionKey cookie not found")

    return decrypt_cookie(row[0], key)


def get_cf_clearance():
    """Extract cf_clearance cookie (needed to pass Cloudflare)."""
    key = get_encryption_key()
    tmp = tempfile.mktemp(suffix=".db")
    shutil.copy2(COOKIE_DB, tmp)

    try:
        conn = sqlite3.connect(tmp)
        cur = conn.cursor()
        cur.execute(
            "SELECT encrypted_value FROM cookies "
            "WHERE host_key='.claude.ai' AND name='cf_clearance'"
        )
        row = cur.fetchone()
        conn.close()
    finally:
        os.unlink(tmp)

    if not row:
        return None

    return decrypt_cookie(row[0], key)


def iso_to_epoch(iso_str):
    """Convert ISO 8601 timestamp to Unix epoch seconds."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.timestamp()
    except Exception:
        return None


def fetch_usage():
    """Fetch usage from claude.ai API and write cache file."""
    session_key = get_session_cookie()
    cf_clearance = get_cf_clearance()

    cookie_str = f"sessionKey={session_key}"
    if cf_clearance:
        cookie_str += f"; cf_clearance={cf_clearance}"

    common_headers = [
        "-H", "Cookie: " + cookie_str,
        "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Claude/1.1.9310 Chrome/144.0.7559.173 Electron/40.4.1 Safari/537.36",
        "-H", "Accept: application/json",
        "-H", "Referer: https://claude.ai/settings/usage",
    ]

    # Discover org ID from bootstrap API
    bootstrap_cmd = ["curl", "-s", "--max-time", "10"] + common_headers + [BOOTSTRAP_URL]
    bootstrap_result = subprocess.run(bootstrap_cmd, capture_output=True, text=True)
    bootstrap_data = json.loads(bootstrap_result.stdout)
    # Try common response shapes
    org_id = (
        (bootstrap_data.get("account") or {}).get("memberships", [{}])[0]
        .get("organization", {}).get("uuid")
        or (bootstrap_data.get("organization") or {}).get("uuid")
    )
    if not org_id:
        raise RuntimeError(f"Could not discover org ID from bootstrap API")

    usage_url = f"https://claude.ai/api/organizations/{org_id}/usage"

    cmd = ["curl", "-s", "--max-time", "10"] + common_headers + [usage_url]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr}")

    data = json.loads(result.stdout)

    # Validate we got usage data
    if "five_hour" not in data:
        raise RuntimeError(f"Unexpected response: {result.stdout[:200]}")

    # Write cache in the format expected by statusline + menu bar
    cache = {
        "five_hour": data["five_hour"]["utilization"],
        "five_hour_resets": iso_to_epoch(data["five_hour"].get("resets_at")),
        "seven_day": data["seven_day"]["utilization"],
        "seven_day_resets": iso_to_epoch(data["seven_day"].get("resets_at")),
        "ts": time.time(),
    }

    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

    return cache


if __name__ == "__main__":
    try:
        cache = fetch_usage()
        print(f"OK: 5h={cache['five_hour']}%, 7d={cache['seven_day']}%")
    except Exception as e:
        print(f"ERROR: {e}")
        raise SystemExit(1)
