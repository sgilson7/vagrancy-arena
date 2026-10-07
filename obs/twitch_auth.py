"""Let the bot speak in chat and set the stream's title and category
and the channel's description.

    .venv/bin/python obs/twitch_auth.py

Uses Twitch's device sign-in: it prints a short code and a link; open the
link (twitch.tv/activate), sign in as the channel, enter the code, and
approve. The tokens go straight into the macOS Keychain
(`vagrancy-twitch-chat-token`, `vagrancy-twitch-refresh-token`); nothing is
printed or written to a file. Needs `twitch_client_id` in config.json: the
Client ID of an application registered at dev.twitch.tv/console/apps with
Client Type "Public" (a Client ID is not a secret).
"""
import json, subprocess, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text())
SCOPES = "chat:read chat:edit channel:manage:broadcast user:edit"


def post(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}")


def keychain_set(service, value):
    subprocess.run(["security", "add-generic-password", "-U", "-a", CONFIG["keychain_account"], "-s", service, "-w", value], check=True, capture_output=True)


def main():
    cid = CONFIG.get("twitch_client_id")
    if not cid:
        sys.exit("Put your application's Client ID in config.json as twitch_client_id (dev.twitch.tv/console/apps, Client Type: Public).")
    d = post("https://id.twitch.tv/oauth2/device", {"client_id": cid, "scopes": SCOPES})
    if "device_code" not in d:
        sys.exit(f"Twitch refused the sign-in request: {d.get('message', d)}")
    print(f"Open {d['verification_uri']} and enter the code {d['user_code']} (it expires in {d['expires_in'] // 60} minutes).")
    deadline = time.time() + d["expires_in"]
    while time.time() < deadline:
        time.sleep(d.get("interval", 5))
        t = post("https://id.twitch.tv/oauth2/token", {"client_id": cid, "scopes": SCOPES, "device_code": d["device_code"],
                                                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if "access_token" in t:
            keychain_set("vagrancy-twitch-chat-token", t["access_token"])
            keychain_set("vagrancy-twitch-refresh-token", t["refresh_token"])
            print("Signed in. Restart the bot (pkill -f arena.bot, then start it) and it will speak in chat.")
            return
        if t.get("message") not in ("authorization_pending", "slow_down"):
            sys.exit(f"Sign-in failed: {t.get('message', t)}")
    sys.exit("The code expired; run this again.")


if __name__ == "__main__":
    main()
