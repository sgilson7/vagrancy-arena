"""Post one line to the channel's chat as the signed-in account, then leave.

    .venv/bin/python -m arena.say "text"

Lines starting with ! are commands the bot obeys: the channel's own account
is the broadcaster, so `!trees sometimes` and the timed holds work from here.
The token is read from the Keychain and never printed.
"""
import asyncio, sys
import websockets
from arena.bot import CONFIG, keychain, refresh_token


async def send(token, text):
    async with websockets.connect("wss://irc-ws.chat.twitch.tv:443") as ws:
        await ws.send(f"PASS oauth:{token}")
        await ws.send(f"NICK {CONFIG['bot_nick']}")
        while True:
            m = await asyncio.wait_for(ws.recv(), 10)
            if "Login authentication failed" in m or "Improperly formatted auth" in m:
                return False
            if " 376 " in m:  # the end of the welcome: signed in
                break
        await ws.send(f"PRIVMSG #{CONFIG['channel']} :{text}")
        await asyncio.sleep(1)
        return True


def main():
    text = " ".join(sys.argv[1:]).strip()
    if not text:
        sys.exit("usage: python -m arena.say \"text\"")
    token = keychain("vagrancy-twitch-chat-token")
    if not token:
        sys.exit("No chat token in the Keychain; run obs/twitch_auth.py first.")
    if not asyncio.run(send(token, text)):
        token = refresh_token()
        if not token or not asyncio.run(send(token, text)):
            sys.exit("Twitch refused the chat token; run obs/twitch_auth.py again.")
    print("sent")


if __name__ == "__main__":
    main()
