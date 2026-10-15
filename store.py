"""Очередь кандидатов и решения по ним.

База и скачанные файлы лежат в Application Support (на Windows — в
%LOCALAPPDATA%): приложению из Finder туда доступ открыт без вопросов, и
очередь не попадает под выгрузку iCloud.
"""
import hashlib
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

def _data_dir() -> Path:
    # GIFKI_DATA — для проверок на отдельной базе.
    if os.environ.get("GIFKI_DATA"):
        return Path(os.environ["GIFKI_DATA"])
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Gifki"
    return Path.home() / "Library" / "Application Support" / "Gifki"


DATA = _data_dir()
INBOX = DATA / "inbox"
NEAR = 5  # бит разницы отпечатка, при которых кадр считается тем же
MASK = (1 << 64) - 1

SCHEMA = """
create table if not exists items(
    id       integer primary key,
    channel  text,
    source   text not null,
    ref      text,
    page     text,
    url      text,
    md5      text,
    sha      text,
    dhash    integer,
    path     text not null,
    own      integer not null default 1,
    suggest  text not null default '',
    width    integer, height integer, duration real,
    status   text not null default 'new',
    bumped   real not null default 0,
    labels   text not null default '',
    out      text,
    added    real,
    decided  real
);
create index if not exists items_queue on items(status, channel, id);
create index if not exists items_md5 on items(md5);
create index if not exists items_sha on items(sha);
create index if not exists items_url on items(url);
create table if not exists cursors(
    source text, query text, value text,
    primary key (source, query)
);
"""


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def usable_hash(h) -> bool:
    # Ровный кадр (чёрный, белый, заливка) даёт почти пустой отпечаток и
    # «совпадает» со всеми такими же — по нему повторы не ищем.
    return h is not None and 4 <= bin(h).count("1") <= 60


class Store:
    def __init__(self, path: Path = DATA / "gifki.db"):
        DATA.mkdir(parents=True, exist_ok=True)
        INBOX.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma journal_mode=wal")
        self.db.executescript(SCHEMA)
        # bumped появился позже: пропущенная гифка уходит в конец своего канала насовсем.
        cols = {r[1] for r in self.db.execute("pragma table_info(items)")}
        if "bumped" not in cols:
            self.db.execute("alter table items add column bumped real not null default 0")
        self.hashes = [r[0] & MASK for r in self.db.execute(
            "select dhash from items where dhash is not null")]
        self._purge()

    def _purge(self):
        """Скачанные файлы разобранных удаляются при следующем запуске, а не сразу.

        До тех пор решение можно отменить, а на Windows файл, который ещё
        открыт проигрывателем, не даёт себя ни переместить, ни удалить.
        """
        with self.lock:
            rows = self.db.execute(
                "select id, path from items where own = 1 and status != 'new' and path != ''").fetchall()
            for r in rows:
                Path(r["path"]).unlink(missing_ok=True)
            self.db.execute("update items set path = '' where own = 1 and status != 'new'")
        old = INBOX / ".done"  # так было до 1.1: разобранное переносилось сюда
        if old.exists():
            for f in old.iterdir():
                f.unlink(missing_ok=True)
            old.rmdir()

    def known(self, url=None, md5=None, ref=None, source=None) -> bool:
        with self.lock:
            if md5 and self.db.execute("select 1 from items where md5 = ?", (md5,)).fetchone():
                return True
            if url and self.db.execute("select 1 from items where url = ?", (url,)).fetchone():
                return True
            if ref and source and self.db.execute(
                    "select 1 from items where source = ? and ref = ?", (source, ref)).fetchone():
                return True
        return False

    def duplicate(self, sha: str, dh) -> bool:
        with self.lock:
            if self.db.execute("select 1 from items where sha = ?", (sha,)).fetchone():
                return True
            if usable_hash(dh):
                return any(bin(dh ^ h).count("1") <= NEAR for h in self.hashes if usable_hash(h))
        return False

    def add(self, **row) -> int:
        row.setdefault("added", time.time())
        h = row.get("dhash")
        if h is not None and h > (MASK >> 1):
            # SQLite хранит целые со знаком: старший бит уходит в минус.
            row["dhash"] = h - (1 << 64)
        with self.lock:
            cols = ", ".join(row)
            marks = ", ".join("?" for _ in row)
            cur = self.db.execute(f"insert into items({cols}) values({marks})", tuple(row.values()))
            if h is not None:
                self.hashes.append(h)
            return cur.lastrowid

    def keep_rates(self) -> dict:
        """Насколько часто пользователь оставляет гифки источника в канале.

        Пока решений мало, оценка опирается на общий процент источника по всем
        каналам, а тот — на половину. Так один выкинутый файл не хоронит источник.
        """
        with self.lock:
            rows = self.db.execute(
                "select channel, source, sum(status = 'kept'), sum(status = 'dropped')"
                " from items where status in ('kept', 'dropped') group by channel, source").fetchall()
        total = {}
        for _, src, k, d in rows:
            tk, td = total.get(src, (0, 0))
            total[src] = (tk + k, td + d)
        prior = {src: (k + 1) / (k + d + 2) for src, (k, d) in total.items()}
        rates = {}
        for ch, src, k, d in rows:
            rates[(ch, src)] = (k + 4 * prior[src]) / (k + d + 4)
        return {"pair": rates, "source": prior}

    def queue(self, channel=None, order=(), limit=40) -> list:
        """Новые кандидаты. Без канала — по порядку каналов, чтобы не прыгать между
        действиями. Внутри канала — сначала источники, которые пользователь чаще
        оставляет; пропущенные и длинные — в конце, в порядке пропуска."""
        with self.lock:
            if channel:
                rows = self.db.execute("select * from items where status = 'new' and channel = ?",
                                       (channel,)).fetchall()
            else:
                rows = self.db.execute("select * from items where status = 'new'").fetchall()
        rates = self.keep_rates()

        def rate(r):
            return rates["pair"].get((r["channel"], r["source"]), rates["source"].get(r["source"], 0.5))

        rank = {name: i for i, name in enumerate(order)}
        # Файлы без канала — в конце: им канал выбирают вручную.
        rows.sort(key=lambda r: (0 if channel else rank.get(r["channel"], 10_000),
                                 r["bumped"] > 0, r["bumped"], -round(rate(r), 2), r["id"]))
        return rows[:limit]

    def bump(self, item_id: int):
        with self.lock:
            self.db.execute("update items set bumped = ? where id = ?", (time.time(), item_id))

    def waiting(self) -> dict:
        with self.lock:
            return {r[0]: r[1] for r in self.db.execute(
                "select coalesce(channel, ''), count(*) from items where status = 'new' group by channel")}

    def get(self, item_id: int):
        with self.lock:
            return self.db.execute("select * from items where id = ?", (item_id,)).fetchone()

    def decide(self, item_id: int, status: str, channel=None, labels="", out=None):
        with self.lock:
            self.db.execute(
                "update items set status = ?, channel = coalesce(?, channel), labels = ?, out = ?,"
                " decided = ? where id = ?",
                (status, channel, labels, out, time.time(), item_id))

    def undo(self, item_id: int):
        with self.lock:
            row = self.get(item_id)
            if row["out"] and Path(row["out"]).exists():
                Path(row["out"]).unlink()
            self.db.execute(
                "update items set status = 'new', labels = '', out = null, decided = null"
                " where id = ?", (item_id,))

    def rename_channel(self, old: str, new: str):
        with self.lock:
            self.db.execute("update items set channel = ? where channel = ?", (new, old))

    def set_channel(self, item_id: int, channel: str):
        with self.lock:
            self.db.execute("update items set channel = ? where id = ?", (channel, item_id))

    def cursor(self, source: str, query: str):
        with self.lock:
            r = self.db.execute("select value from cursors where source = ? and query = ?",
                                (source, query)).fetchone()
        return r[0] if r else None

    def set_cursor(self, source: str, query: str, value):
        with self.lock:
            if value is None:
                self.db.execute("delete from cursors where source = ? and query = ?", (source, query))
            else:
                self.db.execute("insert or replace into cursors values(?, ?, ?)",
                                (source, query, str(value)))
