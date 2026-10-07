# Runbook: keeping the arena stream up

For the Claude Code session left to manage the stream. The stream key and
chat token are in the macOS Keychain; never print, log or commit them.

## Start

1. `cd ~/Documents/vagrancy-arena`
2. `nohup .venv/bin/python -m arena.bot >> logs/bot.out 2>&1 &`
3. `.venv/bin/python obs/setup_obs.py --start`

## Every few minutes

- `tail -n 20 logs/bot.log`: expect "arena page connected" and turns going
  by. "arena page left" for more than a minute means the browser source
  dropped: in OBS, refresh the "Arena page" source.
- `pgrep -f arena.bot`: if the bot died, start it again (step 2). The
  ledger survives.
- `pgrep -x OBS`: if OBS closed, step 3.

## When a match hangs

The bot gives up on a fight after `fight_timeout` seconds and moves on; a
challenge whose viewer does not join in `join_seconds` is refunded.

## Moderation

The bot only acts on its commands. Viewer names and tree names appear on
stream as data; a tree's name is cut to 40 characters. If a name is
abusive, remove the viewer's queued turn by restarting the bot; their
balance stays.

## Stop

`pkill -f arena.bot`, then stop streaming in OBS.

## Letting the bot speak in chat

1. At dev.twitch.tv/console/apps, register an application: any name, OAuth
   Redirect URL `http://localhost`, Category "Other", Client Type "Public".
   Copy its Client ID into `config.json` as `twitch_client_id` (not a secret).
2. `.venv/bin/python obs/twitch_auth.py`, then open twitch.tv/activate, sign in
   as the channel and enter the code it prints. The tokens go into the
   Keychain; nothing is printed.
3. Restart the bot. Its log says "speaking" and it sets the stream title and
   category from `config.json` (`stream_title`, `stream_category`). It renews
   the token itself from the refresh token.
