"""The experience ledger: a local SQLite file, never uploaded.

Viewers are kept by their Twitch login for the stream's own use (balances,
the leaderboard). Study events are written only when the config names an
IRB approval, and then with the login replaced by a random id that only
this file can map back (see README, "The study").
"""
import json, secrets, sqlite3, time


class Ledger:
    def __init__(self, path, study=None):
        self.db = sqlite3.connect(str(path))
        self.study = study
        self.db.executescript("""
            create table if not exists viewers (login text primary key, name text, xp integer, pid text);
            create table if not exists events (at real, kind text, pid text, data text);
        """)
        self.db.commit()

    def seen(self, login, name, start_xp):
        if self.db.execute("select 1 from viewers where login=?", (login,)).fetchone() is None:
            self.db.execute("insert into viewers values (?,?,?,?)", (login, name, start_xp, secrets.token_hex(8)))
        else:
            self.db.execute("update viewers set name=? where login=?", (name, login))
        self.db.commit()

    def xp(self, login):
        row = self.db.execute("select xp from viewers where login=?", (login,)).fetchone()
        return row[0] if row else 0

    def add(self, login, n):
        self.db.execute("update viewers set xp = xp + ? where login=?", (n, login))
        self.db.commit()

    def spend(self, login, n):
        if self.xp(login) < n:
            return False
        self.add(login, -n)
        return True

    def leaders(self, n):
        return [{"viewer": name, "xp": xp} for name, xp in
                self.db.execute("select name, xp from viewers order by xp desc, name limit ?", (n,))]

    def event(self, kind, login, **data):
        """A study event: kept only under an IRB approval, and pseudonymous."""
        if not self.study:
            return
        pid = None
        if login:
            row = self.db.execute("select pid from viewers where login=?", (login,)).fetchone()
            pid = row[0] if row else None
        self.db.execute("insert into events values (?,?,?,?)", (time.time(), kind, pid, json.dumps(data)))
        self.db.commit()
