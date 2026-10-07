#!/bin/zsh
# Run the arena stream: ./stream.sh start|stop|status|refresh|say <text>|leaders|log
# Secrets stay in the Keychain; nothing here prints one.
cd "${0:A:h}"
PY=.venv/bin/python
bot_up() { pgrep -f "arena.bot" >/dev/null; }
obs_up() { pgrep -x OBS >/dev/null; }
case "$1" in
  start)
    bot_up || { nohup $PY -m arena.bot >> logs/bot.out 2>&1 & ; echo "bot started"; }
    if obs_up; then
      sleep 3; $PY obs/status.py --refresh StartStream | sed -n 1,2p
    else
      $PY obs/setup_obs.py --start
      echo "OBS is launching; it starts streaming when it opens. Run ./stream.sh status in a minute."
    fi ;;
  stop)
    obs_up && $PY obs/status.py StopStream | sed -n 1p
    pkill -f arena.bot && echo "bot stopped" ;;
  status)
    if obs_up; then $PY obs/status.py; else echo "OBS: not running"; fi
    bot_up && echo "bot: running" || echo "bot: not running"
    tail -n 8 logs/bot.log 2>/dev/null ;;
  refresh) $PY obs/status.py --refresh | sed -n 1p ;;
  say) shift; $PY -m arena.say "$*" ;;
  leaders) sqlite3 arena.sqlite "select name, xp from viewers order by xp desc limit ${2:-10}" ;;
  log) tail -n ${2:-40} logs/bot.log ;;
  *) echo "usage: ./stream.sh start|stop|status|refresh|say <text>|leaders [n]|log [n]"; exit 1 ;;
esac
