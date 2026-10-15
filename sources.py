"""Где искать гифки и как их скачивать.

Каждый источник — генератор кандидатов для канала. Сборщик сам решает, сколько
взять: проверяет повторы по ссылке и MD5 ещё до скачивания, качает в несколько
потоков, после скачивания отсеивает неподвижные и повторы по отпечатку кадра.
"""
import base64
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from hashlib import md5 as _md5
from pathlib import Path

import actions
import media
from i18n import t, tf
from store import INBOX, Store, sha256

UA = "Gifki/1.0 (personal collection tool; DrTonix; bdub.space)"
MAX_BYTES = 30 * 1024 * 1024
MAX_SECONDS = 15.0   # длиннее — уже не гифка, такое режут в нарезке

# Только для рейтинга sensitive: у general эти теги — семейные сцены, у
# sensitive — то, что брать нельзя.
CHILD = {"loli", "shota", "female_child", "male_child", "child", "toddler", "aged_down"}
REAL = {"photo_(medium)", "real_life", "cosplay"}

NAMES = {
    "danbooru": "Danbooru", "safebooru": "Safebooru", "otaku": "otakugifs",
    "purr": "purrbot", "nekoslife": "nekos.life", "nekosbest": "nekos.best",
    "waifu": "waifu.pics", "giphy": "Giphy", "sakuga": "Sakugabooru", "reddit": "Reddit",
}
ORDER = ("danbooru", "safebooru", "sakuga", "reddit", "otaku", "purr", "nekoslife", "nekosbest",
         "waifu", "giphy")
# Ключи свои у пользователя: без них источник просто не опрашивается.
KEYED = ("giphy", "reddit")
# Сакуга — клипы лучших моментов анимации: длиннее и тяжелее гифок, это сырьё для нарезки.
LONG = {"sakuga": (60 * 1024 * 1024, 90.0)}


class SourceDown(Exception):
    """Источник отказал. final — насовсем (закрыт доступ), иначе сбой связи."""

    def __init__(self, text, final=False):
        super().__init__(text)
        self.final = final


@dataclass
class Candidate:
    source: str
    url: str
    ext: str
    ref: str = ""
    page: str = ""
    md5: str = ""
    tags: set = field(default_factory=set)
    size: int = 0
    later: bool = False   # в конец канала: источник сам не уверен, что это то действие
    score: int = 0


_VIA_PROXY = urllib.request.build_opener()
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_direct_hosts: set = set()


def _open(url, data=None, headers=None, timeout=12):
    """Через системный прокси, а если сайт за 8 секунд не ответил — напрямую.

    Safebooru молча держит соединения с адреса прокси, напрямую отвечает за
    полсекунды. Сайт, ушедший напрямую, так и ходит до конца работы.
    """
    host = urllib.parse.urlparse(url).netloc
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    if host not in _direct_hosts:
        try:
            return _VIA_PROXY.open(req, timeout=8)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            _direct_hosts.add(host)
    return _DIRECT.open(req, timeout=timeout)


def _get(url, data=None, timeout=12, headers=None):
    headers = dict(headers or {})
    if data is not None and not isinstance(data, bytes):
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    try:
        with _open(url, data, headers, timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code in (401, 403):
            raise SourceDown(tf("доступ закрыт (ответ {code})", code=e.code), final=True) from None
        raise SourceDown(tf("ответ {code}", code=e.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SourceDown(t("не отвечает")) from None
    except ValueError:
        raise SourceDown(t("отвечает не тем")) from None


def _ext(url: str) -> str:
    return Path(urllib.parse.urlparse(url).path).suffix.lower().lstrip(".")


_LISTS: dict = {}   # тег → (когда, кандидаты по убыванию счёта)


def _danbooru_list(tag, halt):
    """Все анимации тега, лучшие первыми.

    Без аккаунта Danbooru даёт два тега на запрос, и order:score — третий.
    Поэтому список берётся целиком (до 2000 постов, это 10 запросов) и
    сортируется здесь; на шесть часов он запоминается.
    """
    hit = _LISTS.get(tag)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    out = []
    for page in range(1, 11):
        if halt.is_set():
            return None
        q = urllib.parse.urlencode({"tags": f"{tag} animated rating:g,s", "limit": 200, "page": page})
        posts = _get("https://danbooru.donmai.us/posts.json?" + q)
        if halt.wait(0.6):
            return None
        for p in posts or []:
            tags = set(p.get("tag_string", "").split())
            ext = p.get("file_ext")
            url = p.get("file_url")
            dur = (p.get("media_asset") or {}).get("duration") or 0
            if not url or ext not in ("gif", "mp4", "webm"):
                continue
            if (p.get("file_size") or 0) > MAX_BYTES or dur > MAX_SECONDS:
                continue
            # Рейтинг проверяется и здесь, а не только в запросе: теги каналов
            # теперь задаёт пользователь.
            if p.get("rating") not in ("g", "s"):
                continue
            if tags & REAL or (p.get("rating") != "g" and tags & CHILD):
                continue
            out.append(Candidate("danbooru", url, ext, str(p["id"]),
                                 f"https://danbooru.donmai.us/posts/{p['id']}",
                                 p.get("md5", ""), tags, p.get("file_size") or 0,
                                 score=p.get("score") or 0))
        if not posts or len(posts) < 200:
            break
    out.sort(key=lambda c: -c.score)
    _LISTS[tag] = (time.time(), out)
    return out


def danbooru(ch, store: Store, key, halt):
    for tag in ch.booru:
        found = _danbooru_list(tag, halt)
        if found is None:
            return
        yield from found


def safebooru(ch, store: Store, key, halt):
    for tag in ch.booru:
        pid = int(store.cursor("safebooru", tag) or 0)
        while True:
            q = urllib.parse.urlencode({"page": "dapi", "s": "post", "q": "index", "json": 1,
                                        "limit": 100, "pid": pid,
                                        "tags": f"{tag} animated sort:score:desc"})
            if halt.is_set():
                return
            posts = _get("https://safebooru.org/index.php?" + q)
            if halt.wait(0.6):
                return
            if not posts:
                store.set_cursor("safebooru", tag, None)
                break
            for p in posts:
                tags = set((p.get("tags") or "").split())
                image = p.get("image", "")
                ext = _ext(image)
                if ext not in ("gif", "mp4", "webm") or p.get("rating") not in ("general", "safe"):
                    continue
                if tags & REAL:
                    continue
                url = f"https://safebooru.org/images/{p.get('directory')}/{image}"
                yield Candidate("safebooru", url, ext, str(p.get("id")),
                                f"https://safebooru.org/index.php?page=post&s=view&id={p.get('id')}",
                                p.get("hash", ""), tags)
            pid += 1
            store.set_cursor("safebooru", tag, pid)


def sakuga(ch, store: Store, key, halt):
    """Sakugabooru: клипы из самих аниме, теги про анимацию — crying, dancing,
    fighting, running. Совпадающие с Danbooru теги каналов находят своё."""
    for tag in ch.booru:
        page = int(store.cursor("sakuga", tag) or 1)
        while True:
            if halt.is_set():
                return
            q = urllib.parse.urlencode({"tags": f"{tag} rating:s order:score", "limit": 100, "page": page})
            posts = _get("https://www.sakugabooru.com/post.json?" + q)
            if halt.wait(0.6):
                return
            if not posts:
                store.set_cursor("sakuga", tag, None)
                break
            for p in posts:
                ext = p.get("file_ext")
                url = p.get("file_url")
                if not url or ext not in ("mp4", "webm", "gif") or p.get("rating") != "s":
                    continue
                if (p.get("file_size") or 0) > LONG["sakuga"][0]:
                    continue
                yield Candidate("sakuga", url, ext, str(p.get("id")),
                                f"https://www.sakugabooru.com/post/show/{p.get('id')}",
                                p.get("md5", ""), set((p.get("tags") or "").split()),
                                p.get("file_size") or 0, score=p.get("score") or 0)
            page += 1
            store.set_cursor("sakuga", tag, page)


REDDIT_UA = "macos:space.bdub.gifki:v1.0 (personal collection tool)"
_TOKENS: dict = {}


def _reddit_token(cred: str) -> str:
    """Токен приложения без входа пользователя: только чтение открытых сабреддитов."""
    hit = _TOKENS.get(cred)
    if hit and hit[1] > time.time() + 60:
        return hit[0]
    cid, _, secret = cred.partition(":")
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    d = _get("https://www.reddit.com/api/v1/access_token", data=b"grant_type=client_credentials",
             headers={"Authorization": f"Basic {auth}", "User-Agent": REDDIT_UA,
                      "Content-Type": "application/x-www-form-urlencoded"})
    if not d or not d.get("access_token"):
        raise SourceDown(t("ключ не подошёл"), final=True)
    _TOKENS[cred] = (d["access_token"], time.time() + float(d.get("expires_in") or 3600))
    return d["access_token"]


def _reddit_media(p):
    """Ссылка на сам ролик: видео Reddit без звука, гифка i.redd.it, imgur."""
    for box in (p.get("secure_media"), p.get("media")):
        v = (box or {}).get("reddit_video") or {}
        if v.get("fallback_url"):
            return v["fallback_url"].split("?")[0], "mp4"
    url = p.get("url_overridden_by_dest") or p.get("url") or ""
    ext = _ext(url)
    if "i.redd.it" in url and ext in ("gif", "mp4"):
        return url, ext
    if "imgur.com" in url and ext == "gifv":
        return url[:-5] + ".mp4", "mp4"
    if "i.imgur.com" in url and ext in ("gif", "mp4"):
        return url, ext
    prev = ((p.get("preview") or {}).get("reddit_video_preview") or {}).get("fallback_url")
    if prev:
        return prev.split("?")[0], "mp4"
    return None


def reddit(ch, store: Store, key, halt):
    if not key or not ch.en:
        return
    query = f"animegifs:{ch.en}"
    after = store.cursor("reddit", query)
    while not halt.is_set():
        token = _reddit_token(key)
        params = {"q": ch.en, "restrict_sr": 1, "sort": "top", "t": "all", "limit": 100,
                  "raw_json": 1, "type": "link"}
        if after:
            params["after"] = after
        d = _get("https://oauth.reddit.com/r/animegifs/search?" + urllib.parse.urlencode(params),
                 headers={"Authorization": f"Bearer {token}", "User-Agent": REDDIT_UA})
        data = (d or {}).get("data") or {}
        for c in data.get("children") or []:
            p = c.get("data") or {}
            if p.get("over_18"):
                continue
            found = _reddit_media(p)
            if not found:
                continue
            url, ext = found
            yield Candidate("reddit", url, ext, p.get("id", ""),
                            "https://www.reddit.com" + p.get("permalink", ""), score=p.get("score") or 0)
        after = data.get("after")
        store.set_cursor("reddit", query, after)
        if not after:
            break
        if halt.wait(1):
            return


def _api_urls(name, cat):
    if name == "otaku":
        d = _get(f"https://api.otakugifs.xyz/gif?reaction={cat}&format=gif")
        return [d["url"]] if d and d.get("url") else []
    if name == "purr":
        d = _get(f"https://api.purrbot.site/v2/img/sfw/{cat}/gif")
        return [d["link"]] if d and not d.get("error") and d.get("link") else []
    if name == "nekoslife":
        d = _get(f"https://nekos.life/api/v2/img/{cat}")
        return [d["url"]] if d and d.get("url") else []
    if name == "nekosbest":
        d = _get(f"https://nekos.best/api/v2/{cat}?amount=20")
        return [r["url"] for r in (d or {}).get("results", []) if r.get("url")]
    if name == "waifu":
        d = _get(f"https://api.waifu.pics/many/sfw/{cat}", data={"exclude": []})
        return list((d or {}).get("files", []))
    return []


def _api(name):
    def run(ch, store: Store, key, halt):
        cats = [a.split(":", 1)[1] for a in ch.apis if a.split(":", 1)[0] == name]
        for cat in cats:
            stale, asked = 0, 0
            # Выдача случайная: двадцать известных подряд — значит, набор исчерпан.
            while stale < 20 and asked < 150:
                # Известные ссылки наружу не выходят, поэтому флаг проверяем здесь.
                if halt.is_set():
                    return
                asked += 1
                urls = _api_urls(name, cat)
                if halt.wait(0.3):
                    return
                if not urls:
                    break
                for url in urls:
                    if store.known(url=url):
                        stale += 1
                        continue
                    stale = 0
                    yield Candidate(name, url, _ext(url) or "gif", url)
    return run


def _names_action(ch, *texts) -> bool:
    """Поиск Giphy нечёткий: на «anime kiss» отдаёт и мишку Винни, и рекламу
    газировки. Гифки без слова действия в названии уходят в конец канала — не
    выкидываются: среди них и нормальные сцены вроде «otp-taiga-ryuuji»."""
    words = [w for w in ch.en.lower().split() if len(w) >= 3]
    tokens = re.split(r"[^a-z]+", " ".join(texts).lower())
    return any(t.startswith(w) for t in tokens if t for w in words)


def giphy(ch, store: Store, key, halt):
    if not key or not ch.en:
        return
    for prefix in ("anime", "cartoon"):
        query = f"{prefix} {ch.en}"
        offset = int(store.cursor("giphy", query) or 0)
        while offset < 4950 and not halt.is_set():
            q = urllib.parse.urlencode({"api_key": key, "q": query, "limit": 50,
                                        "offset": offset, "rating": "pg", "lang": "en"})
            d = _get("https://api.giphy.com/v1/gifs/search?" + q)
            data = (d or {}).get("data") or []
            if not data:
                store.set_cursor("giphy", query, None)
                break
            for g in data:
                orig = (g.get("images") or {}).get("original") or {}
                size = int(orig.get("size") or 0)
                url = orig.get("url") if size and size <= media.LIMIT else orig.get("mp4")
                if not url:
                    continue
                yield Candidate("giphy", url, "gif" if url == orig.get("url") else "mp4",
                                g.get("id", ""), g.get("url", ""), size=size,
                                later=not _names_action(ch, g.get("slug", ""), g.get("title", "")))
            offset += len(data)
            store.set_cursor("giphy", query, offset)
            if halt.wait(0.5):
                return


SOURCES = {
    "danbooru": danbooru, "safebooru": safebooru, "sakuga": sakuga, "reddit": reddit,
    "otaku": _api("otaku"), "purr": _api("purr"), "nekoslife": _api("nekoslife"),
    "nekosbest": _api("nekosbest"), "waifu": _api("waifu"), "giphy": giphy,
}


def offers(ch, source: str) -> bool:
    if not ch.collect:
        return False
    if source in ("danbooru", "safebooru", "sakuga"):
        return bool(ch.booru)
    if source in ("giphy", "reddit"):
        return bool(ch.en)
    return any(a.split(":", 1)[0] == source for a in ch.apis)


class Stopped(Exception):
    pass


def download(c: Candidate, halt) -> Path:
    name = _md5(c.url.encode()).hexdigest()[:16]
    dst = INBOX / f"{c.source}-{name}.{c.ext or 'gif'}"
    part = dst.with_suffix(dst.suffix + ".part")
    got = 0
    try:
        with _open(c.url, timeout=20) as r, open(part, "wb") as f:
            while True:
                block = r.read(1 << 16)
                if not block:
                    break
                # Проверка на каждом куске: остановка не ждёт конца тридцатимегабайтного файла.
                if halt.is_set():
                    raise Stopped
                got += len(block)
                if got > LONG.get(c.source, (MAX_BYTES,))[0]:
                    raise ValueError(t("слишком большой файл"))
                f.write(block)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.replace(dst)
    return dst


def admit(store: Store, path: Path, channel, source, ref="", page="", url="", md5="",
          suggest=(), own=1, later=False, seconds=MAX_SECONDS * 2) -> str:
    """Проверяет скачанный или добавленный файл и ставит в очередь.

    Возвращает 'new', 'dup' или 'skip'. Отказы тоже записываются, чтобы
    сборщик не качал их снова.
    """
    info = media.probe(path)
    status = "new"
    sha = dh = None
    if info.frames < 2 or not info.width or (own and info.duration > seconds):
        status = "skip"
    else:
        sha = sha256(path)
        dh = media.dhash(path, info.duration / 2 if info.duration else 0)
        if store.duplicate(sha, dh):
            status = "dup"
    if status != "new" and own:
        path.unlink(missing_ok=True)
    store.add(channel=channel, source=source, ref=ref, page=page, url=url, md5=md5,
              sha=sha, dhash=dh if status == "new" else None,
              path=str(path) if status == "new" or not own else "", own=own,
              suggest=" ".join(suggest), width=info.width, height=info.height,
              duration=info.duration, status=status,
              # Длинный ролик — сырьё для нарезки: готовые гифки канала идут раньше.
              bumped=time.time() if later or info.duration > MAX_SECONDS else 0)
    return status


class Collector:
    """Обходит каналы и источники. Работает в стороннем потоке, наружу — через emit.

    У каждого источника свой поток: ограничения на частоту запросов у них свои,
    и ждать Danbooru, пока крутится случайная выдача otakugifs, незачем.
    """

    def __init__(self, store: Store, channels, sources, want: int, keys: dict, emit):
        self.store = store
        self.channels = channels
        self.keys = {k: v for k, v in (keys or {}).items() if v}
        self.sources = [s for s in ORDER if s in sources and (s not in KEYED or s in self.keys)]
        self.want = want
        self.emit = emit
        self.halt = threading.Event()
        self.down: dict = {}
        self.total = 0
        self.lock = threading.Lock()

    def stop(self):
        self.halt.set()

    @property
    def stopped(self) -> bool:
        return self.halt.is_set()

    def run(self):
        if not self.sources:
            return
        outer = ThreadPoolExecutor(len(self.sources))
        jobs = [outer.submit(self._source, s) for s in self.sources]
        # Ждём кусками: после остановки не сидим на потоках, повисших в рукопожатии
        # с сервером, — прервать его нельзя, только бросить.
        while not all(j.done() for j in jobs):
            if self.halt.wait(0.2):
                break
        outer.shutdown(wait=False, cancel_futures=True)

    def _source(self, src):
        pool = ThreadPoolExecutor(3)
        fails = 0
        i = 0
        try:
            while i < len(self.channels):
                ch = self.channels[i]
                if self.stopped:
                    return
                self.emit("progress", src, i, len(self.channels), ch.name)
                if not offers(ch, src):
                    i += 1
                    continue
                try:
                    self._take(pool, ch, src)
                    fails = 0
                    i += 1
                except SourceDown as e:
                    if self.stopped:
                        return
                    # Сбой связи бывает разовым: прокси на секунду отдал 503, рукопожатие
                    # не уложилось в срок. Выбываем после трёх подряд или сразу, если
                    # доступ закрыт.
                    fails += 1
                    if e.final or fails >= 3:
                        text = t("ключ не подошёл") if e.final and src in KEYED else str(e)
                        self.down[src] = text
                        self.emit("down", src, text, e.final)
                        return
                    # Тот же канал ещё раз: из-за разовой заминки его не пропускаем.
                    if self.halt.wait(5):
                        return
                except Exception as e:
                    if self.stopped:
                        return
                    self.down[src] = repr(e)[:200]
                    self.emit("down", src, self.down[src], False)
                    return
            self.emit("progress", src, len(self.channels), len(self.channels), "")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _take(self, pool, ch, src):
        got = 0
        batch = []
        urls = set()
        for c in SOURCES[src](ch, self.store, self.keys.get(src, ""), self.halt):
            if self.stopped:
                return
            # Случайная выдача повторяется и внутри одной пачки.
            if c.url in urls or self.store.known(url=c.url, md5=c.md5 or None, ref=c.ref, source=src):
                continue
            urls.add(c.url)
            batch.append(c)
            if len(batch) >= min(8, self.want - got):
                got += self._fetch(pool, ch, batch)
                batch = []
                if got >= self.want:
                    return
        if batch:
            self._fetch(pool, ch, batch)

    def _fetch(self, pool, ch, batch) -> int:
        def one(c):
            try:
                path = download(c, self.halt)
            except Exception:
                return c, None
            if self.stopped:
                # Докачалось уже после остановки — в очередь не ставим.
                path.unlink(missing_ok=True)
                return c, None
            return c, path

        added = 0
        pending = {pool.submit(one, c) for c in batch}
        while pending and not self.stopped:
            done, pending = wait(pending, timeout=0.3, return_when=FIRST_COMPLETED)
            for job in done:
                c, path = job.result()
                if path is None or self.stopped:
                    continue
                status = admit(self.store, path, ch.name, c.source, c.ref, c.page, c.url, c.md5,
                               actions.suggest(ch.name, c.tags), later=c.later,
                               seconds=LONG.get(c.source, (0, MAX_SECONDS * 2))[1])
                if status == "new":
                    added += 1
                    with self.lock:
                        self.total += 1
                    self.emit("added", ch.name)
        return added
