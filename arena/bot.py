"""The Vagrancy arena's bot: Twitch chat, the experience ledger, and the
arena page, on the streaming machine.

    .venv/bin/python -m arena.bot            # see config.json

It runs three things at once:

- a WebSocket server on 127.0.0.1 that the arena page (arena.html?bot=...)
  connects to: the bot tells it what to show and hears the results;
- a Twitch chat connection: with a token in the macOS Keychain
  (`vagrancy-twitch-chat-token`) it can answer in chat; with none it reads
  chat anonymously and the page shows what it would have said;
- the loop: a fight, predictions in its first seconds, experience for the
  right ones, and turns for viewers who spent experience or sent a tree.

Nothing here is a server on the web: the socket listens on 127.0.0.1 only.
"""
import asyncio, json, logging, random, re, secrets, string, subprocess, time
from pathlib import Path

import websockets

from .ledger import Ledger

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text())
log = logging.getLogger("arena")

COMMANDS = {"left": "!left", "right": "!right", "xp": "!xp", "fight": "!fight", "submit": "!submit", "speed": "!speed", "trees": "!trees"}
# !speed <word>: how fast exhibitions play. A live !fight always plays at
# full speed, since its other player is in the game in real time.
SPEEDS = {"quarter": 0.25, "half": 0.5, "normal": 1, "full": 1, "double": 2}
ROOM_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def keychain(service):
    """A secret from the macOS Keychain, or None. Never logged."""
    try:
        r = subprocess.run(["security", "find-generic-password", "-a", CONFIG["keychain_account"], "-s", service, "-w"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or None if r.returncode == 0 else None
    except Exception:
        return None


def keychain_set(service, value):
    subprocess.run(["security", "add-generic-password", "-U", "-a", CONFIG["keychain_account"], "-s", service, "-w", value],
                   check=True, capture_output=True, timeout=5)


def twitch(method, url, token=None, data=None, form=None):
    """A Twitch API call; the token is sent, never logged."""
    import urllib.parse, urllib.request
    headers = {"Client-Id": CONFIG.get("twitch_client_id", "")}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except Exception as e:
        log.warning("twitch %s %s failed (%s)", method, url.split("?")[0], type(e).__name__)
        return None


def refresh_token():
    """A fresh chat token from the refresh token in the Keychain (device
    sign-in tokens last a few hours). Returns it, or None."""
    rt = keychain("vagrancy-twitch-refresh-token")
    if not rt or not CONFIG.get("twitch_client_id"):
        return None
    t = twitch("POST", "https://id.twitch.tv/oauth2/token", form={"client_id": CONFIG["twitch_client_id"], "grant_type": "refresh_token", "refresh_token": rt})
    if not t or "access_token" not in t:
        return None
    keychain_set("vagrancy-twitch-chat-token", t["access_token"])
    keychain_set("vagrancy-twitch-refresh-token", t["refresh_token"])
    return t["access_token"]


def set_stream_info(token):
    """The stream's title and category, from config.json."""
    me = twitch("GET", "https://api.twitch.tv/helix/users", token)
    if not me or not me.get("data"):
        return
    uid = me["data"][0]["id"]
    cat = twitch("GET", "https://api.twitch.tv/helix/games?name=" + __import__("urllib.parse").parse.quote(CONFIG["stream_category"]), token)
    body = {"title": CONFIG["stream_title"]}
    if cat and cat.get("data"):
        body["game_id"] = cat["data"][0]["id"]
    twitch("PATCH", f"https://api.twitch.tv/helix/channels?broadcaster_id={uid}", token, data=body)
    log.info("stream title and category set (%s)", CONFIG["stream_category"])
    # The channel's description needs user:edit, granted by a sign-in made
    # after it was added to obs/twitch_auth.py.
    v = twitch("GET", "https://id.twitch.tv/oauth2/validate", token)
    if v and "user:edit" in v.get("scopes", []) and CONFIG.get("stream_description"):
        twitch("PUT", "https://api.twitch.tv/helix/users?description=" + __import__("urllib.parse").parse.quote(CONFIG["stream_description"]), token)
        log.info("channel description set")
    else:
        log.info("channel description not set: sign in again with obs/twitch_auth.py to allow it")


class Chat:
    """Twitch chat over its IRC WebSocket. Read-only without a token."""

    URL = "wss://irc-ws.chat.twitch.tv:443"

    def __init__(self, channel, on_message):
        self.channel = channel.lower()
        self.on_message = on_message
        self.ws = None
        self.token = refresh_token() or keychain("vagrancy-twitch-chat-token")
        if self.token:
            set_stream_info(self.token)
        self.nick = CONFIG.get("bot_nick") if self.token else f"justinfan{random.randint(10000, 99999)}"

    @property
    def can_speak(self):
        return bool(self.token)

    async def run(self):
        while True:
            try:
                async with websockets.connect(self.URL) as ws:
                    self.ws = ws
                    await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
                    await ws.send(f"PASS oauth:{self.token}" if self.token else "PASS SCHMOOPIIE")
                    await ws.send(f"NICK {self.nick}")
                    await ws.send(f"JOIN #{self.channel}")
                    log.info("chat joined #%s (%s)", self.channel, "speaking" if self.token else "reading only")
                    async for raw in ws:
                        for line in raw.split("\r\n"):
                            if not line:
                                continue
                            if line.startswith("PING"):
                                await ws.send("PONG :tmi.twitch.tv")
                                continue
                            m = re.match(r"^(?:@(\S+) )?:(\w+)!\S+ PRIVMSG #\w+ :(.*)$", line)
                            if m:
                                tags = dict(kv.split("=", 1) for kv in (m.group(1) or "").split(";") if "=" in kv)
                                name = tags.get("display-name") or m.group(2)
                                badges = tags.get("badges", "")
                                boss = "broadcaster/" in badges or "moderator/" in badges
                                await self.on_message(m.group(2).lower(), name, m.group(3).strip(), boss)
            except Exception as e:
                log.warning("chat dropped (%s); reconnecting", type(e).__name__)
                self.ws = None
                await asyncio.sleep(5)
                # A dropped connection may be an expired token.
                self.token = refresh_token() or self.token

    async def say(self, text):
        if self.ws and self.token:
            await self.ws.send(f"PRIVMSG #{self.channel} :{text}")


class Arena:
    def __init__(self, ledger_path=None, chat=True):
        self.ledger = Ledger(ledger_path or ROOT / CONFIG["ledger"], study=CONFIG.get("irb_approval") or None)
        self.use_chat = chat
        self.page = None
        self.roster = []
        self.queue = []            # [{ viewer, login, kind: fight|tree, tree? }]
        self.predictions = {}      # login -> 0|1
        self.predict_open = False
        self.predict_until = 0
        self.result = None
        self.challenge_state = None
        self.checks = {}           # id -> future
        self.chat = Chat(CONFIG["channel"], self.on_chat)
        # The trees over the fighters: "on", "off", or "sometimes" (each
        # fight drawn with them about half the time). The standing setting
        # comes from config.json or a moderator's !trees sometimes; anyone's
        # !trees on|off holds for trees_hold_seconds, and while it holds
        # nobody, moderators included, can change it.
        self.trees_standing = CONFIG.get("trees", "on")
        self.trees_held = None
        self.held_until = 0
        self.now = time.monotonic
        # Anyone's !speed sticks, and locks out the next one for
        # speed_lock_seconds.
        self.speed = 1
        self.speed_locked_until = 0

    # --- the page ------------------------------------------------------------------------
    async def page_handler(self, ws):
        log.info("arena page connected")
        self.page = ws
        try:
            async for raw in ws:
                m = json.loads(raw)
                if m.get("type") == "hello":
                    self.roster = m.get("roster", [])
                    await self.send_panels()
                    await self.send({"type": "speed", "value": self.speed})
                elif m.get("type") == "result":
                    self.result = m
                elif m.get("type") == "challenge":
                    self.challenge_state = m.get("state")
                elif m.get("type") == "checked":
                    fut = self.checks.pop(m.get("id"), None)
                    if fut and not fut.done():
                        fut.set_result(m)
        finally:
            if self.page is ws:
                self.page = None
            log.info("arena page left")

    async def send(self, msg):
        if self.page:
            try:
                await self.page.send(json.dumps(msg))
            except Exception:
                self.page = None

    @property
    def trees(self):
        return self.trees_held if self.trees_held and self.now() < self.held_until else self.trees_standing

    async def release_trees(self, until):
        await asyncio.sleep(max(0, until - self.now()))
        if self.held_until == until:
            self.trees_held = None
            await self.send_trees()
            await self.chat.say(f"The hold is over. Trees: {self.trees}.")

    async def on_trees(self, name, arg, boss):
        left = self.held_until - self.now()
        if self.trees_held and left > 0:
            await self.chat.say(f"@{name} trees are held {self.trees_held} for another {int(left) // 60}:{int(left) % 60:02d}.")
            return
        if arg == "sometimes":
            if boss:
                self.trees_held = None
                self.trees_standing = arg
                await self.send_trees()
                await self.chat.say("Trees: sometimes.")
            return
        hold = CONFIG.get("trees_hold_seconds", 300)
        self.trees_held, self.held_until = arg, self.now() + hold
        await self.send_trees()
        await self.chat.say(f"{name} turned the trees {arg} for {hold // 60} minutes. Nobody can change it until then.")
        asyncio.create_task(self.release_trees(self.held_until))

    async def on_speed(self, name, arg):
        left = self.speed_locked_until - self.now()
        if left > 0:
            await self.chat.say(f"@{name} the speed can change again in {int(left) + 1} seconds.")
            return
        self.speed = SPEEDS[arg]
        self.speed_locked_until = self.now() + CONFIG.get("speed_lock_seconds", 60)
        await self.send({"type": "speed", "value": self.speed})
        await self.chat.say(f"{name} set the speed to {arg}. It can change again in {CONFIG.get('speed_lock_seconds', 60)} seconds.")

    async def send_trees(self):
        show = self.trees == "on" or (self.trees == "sometimes" and random.random() < 0.5)
        await self.send({"type": "trees", "show": show})

    async def send_panels(self):
        await self.send({"type": "how", **COMMANDS, "cost": CONFIG["fight_cost"], "submit_cost": CONFIG["submit_cost"],
                         "speeds": ", ".join(k for k in SPEEDS if k != "full"), "speed_lock": CONFIG.get("speed_lock_seconds", 60),
                         "trees_on": f"{COMMANDS['trees']} on", "trees_off": f"{COMMANDS['trees']} off",
                         "trees_minutes": CONFIG.get("trees_hold_seconds", 300) // 60})
        await self.send({"type": "queue", "items": [{"viewer": q["viewer"], "kind": q["kind"]} for q in self.queue[:6]]})
        await self.send({"type": "leaders", "items": self.ledger.leaders(5)})
        await self.send({"type": "predict", "open": self.predict_open, "seconds": max(0, int(self.predict_until - time.time())),
                         "left": sum(1 for v in self.predictions.values() if v == 0),
                         "right": sum(1 for v in self.predictions.values() if v == 1)})

    async def check_tree(self, tree):
        """Ask the page, which asks core (content::custom), whether a tree runs."""
        fut = asyncio.get_running_loop().create_future()
        key = secrets.token_hex(4)
        self.checks[key] = fut
        await self.send({"type": "check", "id": key, "tree": tree})
        try:
            return await asyncio.wait_for(fut, 10)
        except asyncio.TimeoutError:
            return {"ok": False, "key": "timeout"}

    # --- chat ----------------------------------------------------------------------------
    async def on_chat(self, login, name, text, boss=False):
        self.ledger.seen(login, name, CONFIG["start_xp"])
        word, _, rest = text.partition(" ")
        word = word.lower()
        if word == COMMANDS["trees"] and rest.strip().lower() in ("on", "off", "sometimes"):
            await self.on_trees(name, rest.strip().lower(), boss)
            return
        if word == COMMANDS["speed"] and rest.strip().lower() in SPEEDS:
            await self.on_speed(name, rest.strip().lower())
            return
        if word in (COMMANDS["left"], COMMANDS["right"]) and self.predict_open:
            self.predictions[login] = 0 if word == COMMANDS["left"] else 1
            self.ledger.event("predict", login, side=self.predictions[login])
            await self.send_panels()
        elif word == COMMANDS["xp"]:
            await self.chat.say(f"@{name} has {self.ledger.xp(login)} experience.")
        elif word == COMMANDS["fight"]:
            if any(q["login"] == login and q["kind"] == "fight" for q in self.queue):
                return
            if self.ledger.spend(login, CONFIG["fight_cost"]):
                self.queue.append({"viewer": name, "login": login, "kind": "fight"})
                self.ledger.event("fight_queued", login)
                await self.chat.say(f"@{name} is in the queue to fight. Watch the stream for your join code.")
                await self.send_panels()
            else:
                await self.chat.say(f"@{name} needs {CONFIG['fight_cost']} experience to fight, and has {self.ledger.xp(login)}.")
        elif word == COMMANDS["submit"]:
            tree = self.decode(rest)
            if tree is None:
                await self.chat.say(f"@{name}, that share code could not be read. Make one in the BT Lab's editor.")
                return
            # A tree costs submit_cost experience (Sam, 2026-10-07), taken
            # before the lab checks it and given back if the lab refuses it.
            cost = CONFIG["submit_cost"]
            if not self.ledger.spend(login, cost):
                await self.chat.say(f"@{name} needs {cost} experience to submit a tree, and has {self.ledger.xp(login)}.")
                return
            res = await self.check_tree(tree)
            if not res.get("ok"):
                self.ledger.add(login, cost)
            if res.get("ok"):
                self.queue.append({"viewer": name, "login": login, "kind": "tree", "tree": tree})
                self.ledger.event("tree_submitted", login, tree=tree)
                await self.chat.say(f"@{name}, your tree is in the queue.")
                await self.send_panels()
            else:
                await self.chat.say(f"@{name}, that tree was refused by the lab ({res.get('key')}).")

    @staticmethod
    def decode(code):
        import base64
        try:
            tree = json.loads(base64.b64decode(code.strip()).decode("utf-8"))
            return json.dumps(tree)
        except Exception:
            return None

    # --- the loop ------------------------------------------------------------------------
    async def run_fight(self, msg, predict=True):
        self.result = None
        self.predictions = {}
        self.predict_open = predict
        self.predict_until = time.time() + CONFIG["predict_seconds"]
        await self.send_trees()
        await self.send(msg)
        await self.send_panels()
        # The timeout counts fight time, so a quarter-speed fight gets four
        # times as long on the clock.
        played = 0
        while self.result is None and played < CONFIG["fight_timeout"]:
            played += 0.5 * self.speed
            if self.predict_open and time.time() > self.predict_until:
                self.predict_open = False
                await self.send_panels()
            await asyncio.sleep(0.5)
        self.predict_open = False
        return self.result

    def pay_predictions(self, winner):
        right = [l for l, side in self.predictions.items() if side == winner]
        for login in right:
            self.ledger.add(login, CONFIG["predict_reward"])
        self.ledger.event("predictions_paid", None, winner=winner, right=len(right), total=len(self.predictions))
        return len(right)

    async def next_turn(self):
        if not self.page or not self.roster:
            await asyncio.sleep(2)
            return
        fightable = [r for r in self.roster if r not in ("scarecrow", "guardian_deity")]
        turn = self.queue.pop(0) if self.queue else None
        if turn and turn["kind"] == "fight":
            code = "".join(secrets.choice(ROOM_ALPHABET) for _ in range(6))
            opponent = random.choice(fightable)
            self.challenge_state = None
            self.result = None
            await self.send_trees()
            await self.send({"type": "challenge", "code": code, "viewer": turn["viewer"], "opponent": opponent})
            await self.chat.say(f"@{turn['viewer']}, your turn: open sgilson7.github.io/vagrancy, choose Online, join room {code}, and press Ready.")
            self.ledger.event("challenge_started", turn["login"], opponent=opponent)
            start = time.time()
            while self.challenge_state != "playing" and time.time() - start < CONFIG["join_seconds"]:
                await asyncio.sleep(1)
            if self.challenge_state != "playing":
                self.ledger.add(turn["login"], CONFIG["fight_cost"])  # refunded
                self.ledger.event("challenge_missed", turn["login"])
                await self.chat.say(f"@{turn['viewer']} did not join in time; the experience is refunded.")
                await self.send({"type": "exhibition", "left": {"id": random.choice(fightable)}, "right": {"id": random.choice(fightable)}})
                return
            start = time.time()
            while self.result is None and time.time() - start < CONFIG["fight_timeout"]:
                await asyncio.sleep(1)
            won = bool(self.result and self.result.get("winner") == "viewer")
            if won:
                self.ledger.add(turn["login"], CONFIG["challenge_win_reward"])
            self.ledger.event("challenge_done", turn["login"], won=won, wins=(self.result or {}).get("wins"))
            await self.chat.say(f"@{turn['viewer']} {'won' if won else 'lost'} against the {opponent.replace('_', ' ')}.")
        elif turn and turn["kind"] == "tree":
            tree = json.loads(turn["tree"])
            opponent = random.choice(fightable)
            msg = {"type": "exhibition", "left": {"tree": turn["tree"], "name": str(tree.get("name") or "")[:40], "by": turn["viewer"]}, "right": {"id": opponent}}
            self.ledger.add(turn["login"], CONFIG["tree_reward"])
            res = await self.run_fight(msg)
            if res and res.get("winner") is not None:
                self.pay_predictions(res["winner"])
                if res["winner"] == 0:
                    self.ledger.add(turn["login"], CONFIG["tree_win_reward"])
            self.ledger.event("tree_fought", turn["login"], opponent=opponent, result=res)
        else:
            left, right = random.sample(fightable, 2)
            res = await self.run_fight({"type": "exhibition", "left": {"id": left}, "right": {"id": right}})
            if res and res.get("winner") is not None:
                n = self.pay_predictions(res["winner"])
                if n:
                    await self.chat.say(f"{n} right predictions earned {CONFIG['predict_reward']} experience each.")
        await self.send_panels()
        await asyncio.sleep(CONFIG["between_fights"])

    async def loop(self):
        while True:
            try:
                await self.next_turn()
            except Exception:
                log.exception("turn failed")
                await asyncio.sleep(3)

    async def main(self):
        async with websockets.serve(self.page_handler, "127.0.0.1", CONFIG["port"]):
            log.info("listening for the arena page on 127.0.0.1:%d", CONFIG["port"])
            await asyncio.gather(*([self.chat.run()] if self.use_chat else []), self.loop())


if __name__ == "__main__":
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(ROOT / "logs" / "bot.log")])
    asyncio.run(Arena().main())
