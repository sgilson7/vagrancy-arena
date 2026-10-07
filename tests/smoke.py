"""End to end on this machine: the bot, the arena page in a headless
browser, and a second browser as a viewer who joins a challenge through the
game's online mode. Chat lines are fed to the bot directly.

    .venv/bin/python -m tests.smoke [base-url]
    base-url defaults to http://127.0.0.1:8765 (serve vagrancy/dist/web there)
"""
import asyncio, base64, json, sys, tempfile
from pathlib import Path
from playwright.async_api import async_playwright
from arena import bot as B

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"


async def main():
    B.CONFIG.update(predict_seconds=4, between_fights=1, join_seconds=60, fight_timeout=90)
    d = tempfile.mkdtemp()
    arena = B.Arena(ledger_path=Path(d) / "smoke.sqlite", chat=False)
    task = asyncio.create_task(arena.main())
    fails = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await b.new_page(viewport={"width": 1920, "height": 1080})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        await page.goto(f"{BASE}/arena.html?bot=ws://127.0.0.1:{B.CONFIG['port']}&ice=none")
        await page.wait_for_function("document.body.dataset.ready === '1'", timeout=30000)
        for _ in range(40):
            if arena.page and arena.predict_open:
                break
            await asyncio.sleep(0.5)
        # Predictions during an exhibition, paid at its end.
        await arena.on_chat("ann", "Ann", "!left")
        await arena.on_chat("bo", "Bo", "!right")
        if len(arena.predictions) != 2:
            fails.append(f"predictions not taken: {arena.predictions}")
        for _ in range(240):
            if arena.result is not None:
                break
            await asyncio.sleep(0.5)
        if arena.result is None:
            fails.append("the exhibition never reported a result")
        await asyncio.sleep(2)
        xp = {v: arena.ledger.xp(v) for v in ("ann", "bo")}
        if sorted(xp.values()) not in ([50, 70],) and arena.result and arena.result.get("winner") is not None:
            fails.append(f"predictions were not paid: {xp}, result {arena.result}")
        # A submitted tree: checked by core on the page, queued.
        tree = {"name": "smoke", "reaction_ticks": 10, "rules": [{"if": [{"gap_above": 220}], "do": "approach"}, {"do": "overhead"}]}
        await arena.on_chat("cy", "Cy", "!submit " + base64.b64encode(json.dumps(tree).encode()).decode())
        if not any(q["kind"] == "tree" for q in arena.queue):
            fails.append("a good tree was not queued")
        await arena.on_chat("cy", "Cy", "!submit " + base64.b64encode(b'{"reaction_ticks": 1, "rules": []}').decode())
        if sum(q["kind"] == "tree" for q in arena.queue) != 1:
            fails.append("a bad tree was queued")
        # A challenge: Dee has enough experience after a top-up.
        arena.ledger.seen("dee", "Dee", 50)
        arena.ledger.add("dee", 100)
        await arena.on_chat("dee", "Dee", "!fight")
        if not any(q["kind"] == "fight" for q in arena.queue):
            fails.append("a challenge was not queued")
        # Move the challenge to the front and wait for its code on the page.
        arena.queue.sort(key=lambda q: q["kind"] != "fight")
        code = None
        for _ in range(400):
            code = await page.evaluate("(() => { const c = document.querySelector('#arena-result .code'); return c && c.textContent; })()")
            if code:
                break
            await asyncio.sleep(0.5)
        if not code:
            fails.append("no join code appeared")
        else:
            viewer = await b.new_page()
            await viewer.goto(f"{BASE}/?ice=none#room={code}")
            await viewer.wait_for_function("document.body.dataset.ready === '1'", timeout=30000)
            await viewer.wait_for_selector('[data-copy="online.ready.label"]', timeout=60000)
            await viewer.click('[data-copy="online.ready.label"]')
            for _ in range(120):
                if arena.challenge_state == "playing":
                    break
                await asyncio.sleep(0.5)
            if arena.challenge_state != "playing":
                fails.append(f"the challenge never started: {arena.challenge_state}")
            else:
                print("ok: the viewer joined room", code, "and the challenge is playing")
        if errs:
            fails.append(f"page errors: {errs[:3]}")
        await b.close()
    task.cancel()
    print("FAIL:" if fails else "ok: smoke passed", *fails, sep="\n  ")
    sys.exit(1 if fails else 0)

asyncio.run(main())
