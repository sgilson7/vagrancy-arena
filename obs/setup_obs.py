"""Set OBS up to stream the Vagrancy arena to Twitch, and start it.

    python3 obs/setup_obs.py            # write the profile and scenes
    python3 obs/setup_obs.py --start    # ... and launch OBS streaming

Writes, inside OBS's own settings folder (never this repository):
- a profile "Vagrancy": 1920x1080 canvas, 1280x720 at 30 fps out, and the
  Twitch service with the stream key read from the macOS Keychain
  (`vagrancy-twitch-stream-key`) at the moment it is written;
- a scene collection "Vagrancy" with one scene, "Arena", whose browser
  source is the arena page connected to the local bot;
- obs-websocket on 127.0.0.1:4455 with a password kept in the Keychain
  (`vagrancy-obs-websocket`), so the bot's runbook can check the stream.

The key is never printed, logged or written anywhere but OBS's service.json.
"""
import json, secrets, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text())
OBS = Path.home() / "Library" / "Application Support" / "obs-studio"
ACCOUNT = CONFIG["keychain_account"]


def keychain(service):
    r = subprocess.run(["security", "find-generic-password", "-a", ACCOUNT, "-s", service, "-w"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def keychain_set(service, value):
    subprocess.run(["security", "add-generic-password", "-U", "-a", ACCOUNT, "-s", service, "-w", value], check=True, capture_output=True)


def ini(path, sections):
    path.parent.mkdir(parents=True, exist_ok=True)
    have = {}
    if path.exists():
        cur = None
        for line in path.read_text().splitlines():
            if line.startswith("[") and line.endswith("]"):
                cur = line[1:-1]; have.setdefault(cur, {})
            elif "=" in line and cur:
                k, v = line.split("=", 1); have[cur][k] = v
    for sec, kv in sections.items():
        have.setdefault(sec, {}).update(kv)
    path.write_text("\n".join(f"[{s}]\n" + "\n".join(f"{k}={v}" for k, v in kv.items()) + "\n" for s, kv in have.items()))


def main():
    key = keychain("vagrancy-twitch-stream-key")
    if not key:
        sys.exit("No stream key in the Keychain (vagrancy-twitch-stream-key). Add it with:\n"
                 "  security add-generic-password -U -a sgilson7 -s vagrancy-twitch-stream-key -w")
    ini(OBS / "global.ini", {
        "General": {"FirstRun": "true", "LastVersion": "520093696"},
        "Basic": {"Profile": "Vagrancy", "ProfileDir": "Vagrancy", "SceneCollection": "Vagrancy", "SceneCollectionFile": "Vagrancy"},
    })
    prof = OBS / "basic" / "profiles" / "Vagrancy"
    ini(prof / "basic.ini", {
        "General": {"Name": "Vagrancy"},
        "Video": {"BaseCX": "1920", "BaseCY": "1080", "OutputCX": "1280", "OutputCY": "720", "FPSType": "0", "FPSCommon": "30"},
        "Output": {"Mode": "Simple"},
        "SimpleOutput": {"VBitrate": "3000", "ABitrate": "128", "StreamEncoder": "x264", "Preset": "veryfast"},
    })
    service = prof / "service.json"
    service.write_text(json.dumps({"type": "rtmp_common", "settings": {"service": "Twitch", "server": "auto", "key": key, "bwtest": False}}))
    service.chmod(0o600)
    url = CONFIG["arena_url"]
    scenes = OBS / "basic" / "scenes"
    scenes.mkdir(parents=True, exist_ok=True)
    page_uuid, scene_uuid = secrets.token_hex(16), secrets.token_hex(16)
    fmt = lambda h: f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
    (scenes / "Vagrancy.json").write_text(json.dumps({
        "name": "Vagrancy", "current_scene": "Arena", "current_program_scene": "Arena",
        "scene_order": [{"name": "Arena"}],
        "sources": [
            {"id": "browser_source", "versioned_id": "browser_source", "name": "Arena page", "uuid": fmt(page_uuid),
             "settings": {"url": url, "width": 1920, "height": 1080, "fps": 30, "reroute_audio": False, "restart_when_active": False},
             "enabled": True, "volume": 1.0},
            {"id": "scene", "versioned_id": "scene", "name": "Arena", "uuid": fmt(scene_uuid),
             "settings": {"id_counter": 1, "items": [{"name": "Arena page", "source_uuid": fmt(page_uuid), "visible": True, "id": 1,
                                                       "pos": {"x": 0.0, "y": 0.0}, "scale": {"x": 1.0, "y": 1.0}, "align": 5,
                                                       "bounds_type": 0, "bounds": {"x": 0.0, "y": 0.0}}]},
             "enabled": True},
        ],
        "transitions": [], "groups": [], "quick_transitions": [], "modules": {},
    }))
    pw = keychain("vagrancy-obs-websocket") or secrets.token_urlsafe(18)
    keychain_set("vagrancy-obs-websocket", pw)
    ws = OBS / "plugin_config" / "obs-websocket" / "config.json"
    ws.parent.mkdir(parents=True, exist_ok=True)
    ws.write_text(json.dumps({"server_enabled": True, "server_port": 4455, "auth_required": True, "server_password": pw, "alerts_enabled": False, "first_load": False}))
    ws.chmod(0o600)
    print("OBS is set up: profile Vagrancy, scene Arena, browser source", url)
    if "--start" in sys.argv:
        subprocess.run(["open", "-a", "OBS", "--args", "--profile", "Vagrancy", "--collection", "Vagrancy", "--scene", "Arena",
                        "--startstreaming", "--disable-shutdown-check"], check=True)
        print("OBS is launching and will start streaming.")


if __name__ == "__main__":
    main()
