"""Посредник для потокового видео на 127.0.0.1.

Некоторые сайты (VK) выдают ссылку на видео под заголовки того, кто её
запросил: без них сервер отвечает 400. ffmpeg заголовки передать умеет, плеер
Qt — нет. Плеер и ffmpeg ходят сюда, а отсюда запрос уходит дальше с нужными
заголовками и через системный прокси. Перемотка проходит как есть — через Range.
"""
import hashlib
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_routes: dict = {}
_opener = urllib.request.build_opener()
_server = None
_lock = threading.Lock()

PASS = ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Last-Modified")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self._relay(body=False)

    def do_GET(self):
        self._relay(body=True)

    def _relay(self, body):
        route = _routes.get(self.path.lstrip("/"))
        if route is None:
            self.send_error(404)
            return
        url, headers = route
        first, last = _range(self.headers.get("Range"))
        r = _open(url, headers, first, last, body)
        if isinstance(r, int):
            self.send_error(r)
            return
        self.send_response(r.status)
        for k in PASS:
            if r.headers.get(k):
                self.send_header(k, r.headers[k])
        self.end_headers()
        if not body:
            r.close()
            return
        need = int(r.headers.get("Content-Length") or 0)
        sent, retries = 0, 3
        while not need or sent < need:
            try:
                block = r.read(1 << 16)
            except OSError:
                block = b""
            if not block:
                # Сервер оборвал передачу посередине — докачиваем с того же места,
                # плеер обрыва не видит. Раньше он получал обрывок и застывал.
                r.close()
                if not need or retries == 0:
                    return
                retries -= 1
                r = _open(url, headers, first + sent, last, True)
                if isinstance(r, int):
                    return
                continue
            try:
                self.wfile.write(block)
            except (BrokenPipeError, ConnectionResetError):
                r.close()
                return    # плеер перематывает: бросает старый запрос и открывает новый
            sent += len(block)
        r.close()


def _range(header):
    """«bytes=100-» → (100, None); без заголовка — весь файл."""
    if not header or not header.startswith("bytes="):
        return 0, None
    a, _, b = header[6:].split(",")[0].partition("-")
    try:
        return int(a or 0), (int(b) if b else None)
    except ValueError:
        return 0, None


def _open(url, headers, first, last, body):
    """Запрос к сайту с повтором: через прокси соединение иногда не открывается
    с первого раза, особенно когда плеер часто перематывает. Неудача — код ошибки."""
    h = dict(headers)
    if first or last is not None:
        h["Range"] = f"bytes={first}-{'' if last is None else last}"
    code = 502
    for attempt in range(3):
        req = urllib.request.Request(url, headers=h, method="GET" if body else "HEAD")
        try:
            return _opener.open(req, timeout=20)
        except urllib.error.HTTPError as e:
            code = e.code
            if e.code < 500:
                return code
        except OSError:
            code = 502
        time.sleep(0.4 * (attempt + 1))
    return code


def add(url: str, headers: dict) -> str:
    """Местная ссылка, за которой стоит url с этими заголовками."""
    global _server
    with _lock:
        if _server is None:
            _server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
            _server.daemon_threads = True
            threading.Thread(target=_server.serve_forever, daemon=True).start()
    token = hashlib.md5(url.encode()).hexdigest()[:20]
    _routes[token] = (url, dict(headers))
    return f"http://127.0.0.1:{_server.server_address[1]}/{token}"
