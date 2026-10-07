"""What OBS is doing, through obs-websocket (v5): streaming or not, and the
arena scene's source. The password is read from the Keychain.

    .venv/bin/python obs/status.py [request ...]   e.g. StartStream
"""
import asyncio, base64, hashlib, json, subprocess, sys
from pathlib import Path
import websockets

CONFIG = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text())


def password():
    r = subprocess.run(["security", "find-generic-password", "-a", CONFIG["keychain_account"], "-s", "vagrancy-obs-websocket", "-w"], capture_output=True, text=True)
    return r.stdout.strip()


async def call(ws, rtype, data=None, n=[0]):
    n[0] += 1
    await ws.send(json.dumps({"op": 6, "d": {"requestType": rtype, "requestId": str(n[0]), "requestData": data or {}}}))
    while True:
        m = json.loads(await ws.recv())
        if m["op"] == 7 and m["d"]["requestId"] == str(n[0]):
            return m["d"]


async def main():
    async with websockets.connect("ws://127.0.0.1:4455") as ws:
        hello = json.loads(await ws.recv())["d"]
        ident = {"rpcVersion": 1}
        if "authentication" in hello:
            a = hello["authentication"]
            secret = base64.b64encode(hashlib.sha256((password() + a["salt"]).encode()).digest()).decode()
            ident["authentication"] = base64.b64encode(hashlib.sha256((secret + a["challenge"]).encode()).digest()).decode()
        await ws.send(json.dumps({"op": 1, "d": ident}))
        json.loads(await ws.recv())
        for r in sys.argv[1:]:
            print(r, json.dumps(await call(ws, r))[:300])
        st = await call(ws, "GetStreamStatus")
        print("streaming:", st.get("responseData", {}).get("outputActive"), "| reconnecting:", st.get("responseData", {}).get("outputReconnecting"),
              "| duration ms:", st.get("responseData", {}).get("outputDuration"))
        sc = await call(ws, "GetCurrentProgramScene")
        print("scene:", sc.get("responseData", {}).get("currentProgramSceneName"))
        items = await call(ws, "GetSceneItemList", {"sceneName": "Arena"})
        print("items:", [i.get("sourceName") for i in items.get("responseData", {}).get("sceneItems", [])])
        inp = await call(ws, "GetInputSettings", {"inputName": "Arena page"})
        print("browser source url:", inp.get("responseData", {}).get("inputSettings", {}).get("url"))

asyncio.run(main())
