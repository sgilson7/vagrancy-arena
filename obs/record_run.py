"""Record the agent's run through arcade mode for Sam's video.

    .venv/bin/python obs/record_run.py --music /path/to/track.mp3 [--seed 7]

Serves the game's local build (~/Documents/vagrancy/dist/web) on
127.0.0.1:8777 and adds an OBS scene "Recording": the game, with the
director playing (?player=<seed>&fresh&tuning=2), and the music file as a
media source on a loop, the only audio. Stops the stream, records to
~/Movies/Vagrancy as mp4, follows the run in the server's log
(run-fought-N, run-done), stops the recording a few seconds after the run
ends, and starts the stream again. The OBS password comes from the Keychain.
"""
import argparse, asyncio, base64, hashlib, json, re, subprocess, sys, time
from pathlib import Path
import websockets

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text())
GAME = Path.home() / "Documents" / "vagrancy" / "dist" / "web"
PORT = 8777
LOG = ROOT / "logs" / "record-server.log"
OUT = Path.home() / "Movies" / "Vagrancy"


def password():
    r = subprocess.run(["security", "find-generic-password", "-a", CONFIG["keychain_account"], "-s", "vagrancy-obs-websocket", "-w"], capture_output=True, text=True)
    return r.stdout.strip()


class Obs:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def call(self, rtype, data=None):
        self.n += 1
        await self.ws.send(json.dumps({"op": 6, "d": {"requestType": rtype, "requestId": str(self.n), "requestData": data or {}}}))
        while True:
            m = json.loads(await self.ws.recv())
            if m["op"] == 7 and m["d"]["requestId"] == str(self.n):
                return m["d"]


async def connect():
    ws = await websockets.connect("ws://127.0.0.1:4455", max_size=2**25)
    hello = json.loads(await ws.recv())["d"]
    ident = {"rpcVersion": 1}
    if "authentication" in hello:
        a = hello["authentication"]
        secret = base64.b64encode(hashlib.sha256((password() + a["salt"]).encode()).digest()).decode()
        ident["authentication"] = base64.b64encode(hashlib.sha256((secret + a["challenge"]).encode()).digest()).decode()
    await ws.send(json.dumps({"op": 1, "d": ident}))
    await ws.recv()
    return Obs(ws)


def serve():
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text("")
    return subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1", "--directory", str(GAME)],
                            stdout=subprocess.DEVNULL, stderr=open(LOG, "a"))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--music", required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-stream", action="store_true", help="leave the stream off afterwards")
    ap.add_argument("--music-db", type=float, default=-14.0, help="the music's level in dB (0 is full volume)")
    args = ap.parse_args()
    music = Path(args.music).expanduser()
    if not music.is_file():
        sys.exit(f"no music file at {music}")
    OUT.mkdir(parents=True, exist_ok=True)
    server = serve()
    try:
        obs = await connect()
        url = f"http://127.0.0.1:{PORT}/?player={args.seed}&fresh&tuning=2"
        await obs.call("SetProfileParameter", {"parameterCategory": "SimpleOutput", "parameterName": "FilePath", "parameterValue": str(OUT)})
        await obs.call("SetProfileParameter", {"parameterCategory": "SimpleOutput", "parameterName": "RecFormat2", "parameterValue": "mp4"})
        await obs.call("SetProfileParameter", {"parameterCategory": "SimpleOutput", "parameterName": "RecQuality", "parameterValue": "HQ"})
        scenes = [s["sceneName"] for s in (await obs.call("GetSceneList"))["responseData"]["scenes"]]
        if "Recording" in scenes:
            await obs.call("RemoveScene", {"sceneName": "Recording"})
            await asyncio.sleep(1)
        await obs.call("CreateScene", {"sceneName": "Recording"})
        await obs.call("CreateInput", {"sceneName": "Recording", "inputName": "Run music", "inputKind": "ffmpeg_source",
                                       "inputSettings": {"local_file": str(music), "looping": True, "restart_on_activate": True}})
        # Under the fighting, not over it (Sam: "dont make the music full volume").
        await obs.call("SetInputVolume", {"inputName": "Run music", "inputVolumeDb": args.music_db})
        stopped = (await obs.call("GetStreamStatus"))["responseData"]["outputActive"]
        if stopped:
            await obs.call("StopStream")
            await asyncio.sleep(3)
        await obs.call("SetCurrentProgramScene", {"sceneName": "Recording"})
        # The game last, so the run starts when the recording does.
        await obs.call("StartRecord")
        await obs.call("CreateInput", {"sceneName": "Recording", "inputName": "Run game", "inputKind": "browser_source",
                                       "inputSettings": {"url": url, "width": 1920, "height": 1080, "fps": 30, "reroute_audio": True, "restart_when_active": False}})
        await obs.call("SetInputMute", {"inputName": "Run game", "inputMuted": True})
        print(f"recording {url}", flush=True)
        start, fought = time.time(), 0
        while True:
            await asyncio.sleep(5)
            text = LOG.read_text()
            n = [int(x) for x in re.findall(r"run-fought-(\d+)", text)]
            if n and max(n) != fought:
                fought = max(n)
                print(f"{(time.time() - start) / 60:5.1f} min: {fought} fights played", flush=True)
            if "run-done" in text:
                break
            if time.time() - start > 75 * 60:
                print("the run took over 75 minutes; stopping", flush=True)
                break
        await asyncio.sleep(6)
        out = (await obs.call("StopRecord"))["responseData"].get("outputPath")
        print("recorded to", out, flush=True)
        await obs.call("SetCurrentProgramScene", {"sceneName": "Arena"})
        await obs.call("RemoveInput", {"inputName": "Run game"})
        if stopped and not args.no_stream:
            await asyncio.sleep(2)
            await obs.call("StartStream")
            print("stream started again", flush=True)
    finally:
        server.terminate()


if __name__ == "__main__":
    asyncio.run(main())
