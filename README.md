# Vagrancy arena

A Twitch stream of [Vagrancy](https://sgilson7.github.io/vagrancy/) where
viewers predict who wins, spend the experience they earn on a live turn
against the game's opponents, and submit behavior trees they wrote in the
[BT Lab](https://sgilson7.github.io/vagrancy/bt-lab.html).

Everything here runs on the streaming machine. The game and its arena page
are on GitHub Pages; this repository holds the bot that tells the arena page
what to show, keeps the experience ledger, and reads chat, plus the script
that sets OBS up.

## Pieces

- `arena/bot.py`: Twitch chat (anonymous and read-only unless a chat token
  is in the Keychain as `vagrancy-twitch-chat-token`), the loop of fights,
  and a WebSocket on 127.0.0.1:8787 for the arena page.
- `arena/ledger.py`: experience in a local SQLite file (`arena.sqlite`,
  not committed).
- `obs/setup_obs.py`: an OBS profile and scene showing
  `arena.html?bot=ws://127.0.0.1:8787`, with the stream key read from the
  Keychain (`vagrancy-twitch-stream-key`) straight into OBS's own settings.
- `tests/`: unit tests, and `tests/smoke.py`, which runs the bot, the arena
  page and a viewer joining a challenge end to end.

## Chat commands

| command | what it does |
|---|---|
| `!left`, `!right` | predict the winner while predictions are open (20 experience if right) |
| `!xp` | your experience |
| `!fight` | spend 100 experience for a turn; a join code appears on stream, used in the game's Online mode |
| `!submit <code>` | queue a tree from the BT Lab's editor (a share code); 100 experience when it fights, 100 more if it wins |

New viewers start with 50. A missed join is refunded.

Anyone can type `!trees off` or `!trees on` to hide or show the behavior
trees over the fighters for five minutes (`trees_hold_seconds`); while that
holds, nobody, moderators included, can change it, and then the trees go back
to the standing setting. The broadcaster and moderators can make the standing
setting `!trees sometimes` (about half the fights); `"trees"` in
`config.json` is where it starts.

Anyone can type `!speed quarter`, `!speed half`, `!speed normal` or
`!speed double` to change how fast the fights play. It stays at that speed,
and nobody can change it again for a minute (`speed_lock_seconds`). A live
`!fight` always plays at normal speed, since its player is in real time.

## Running it

```
python3 -m venv .venv && .venv/bin/pip install websockets
.venv/bin/python obs/setup_obs.py            # once, and after the key changes
.venv/bin/python -m arena.bot &              # the bot
.venv/bin/python obs/setup_obs.py --start    # OBS, streaming
```

See `RUNBOOK.md` for running it unattended.

## The study

The stream may become data for a paper on learnersourcing through games
and live platforms. That is human-subjects research: no event is kept for
it until NC State's IRB has approved it and its number is in
`config.json` as `irb_approval`. With it set, events are kept with each
viewer's login replaced by a random id; with it empty (as now), only
balances are kept, for the stream itself.
