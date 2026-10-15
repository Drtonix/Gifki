"""ffmpeg: длительность, отпечаток кадра, перекодирование в GIF."""
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIMIT = 8 * 1024 * 1024   # Discord без Nitro принимает до 10 МБ, берём с запасом
MAX_SIDE = 480


WINDOWS = sys.platform == "win32"


def tool(name: str) -> str:
    own = HERE / "bin" / (name + ".exe" if WINDOWS else name)
    if own.exists():
        return str(own)
    return shutil.which(name) or name


def _run(args, timeout=120) -> subprocess.CompletedProcess:
    # Без флага Windows на каждый вызов ffmpeg открывает и гасит окно консоли.
    flags = subprocess.CREATE_NO_WINDOW if WINDOWS else 0
    return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=flags)


@dataclass
class Info:
    width: int = 0
    height: int = 0
    duration: float = 0.0
    fps: float = 0.0
    frames: int = 0


def _headers(headers) -> list:
    """Заголовки для ссылки на поток: некоторые сайты выдают её под конкретный браузер."""
    return ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())] if headers else []


def probe(path, timeout=30, headers=None) -> Info:
    try:
        r = _run([tool("ffprobe"), "-v", "error", *_headers(headers), "-select_streams", "v:0",
                  "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames:format=duration",
                  "-of", "json", str(path)], timeout=timeout)
    except subprocess.TimeoutExpired:
        return Info()
    try:
        data = json.loads(r.stdout or b"{}")
        s = (data.get("streams") or [{}])[0]
    except (ValueError, IndexError):
        return Info()

    def rate(text):
        try:
            a, b = (text or "0/1").split("/")
            return float(a) / float(b) if float(b) else 0.0
        except ValueError:
            return 0.0

    fps = rate(s.get("avg_frame_rate")) or rate(s.get("r_frame_rate"))
    try:
        dur = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        dur = 0.0
    try:
        frames = int(s.get("nb_frames") or 0)
    except ValueError:
        frames = 0
    if not frames and fps and dur:
        frames = round(fps * dur)
    return Info(int(s.get("width") or 0), int(s.get("height") or 0), dur, fps, frames)


def dhash(path, at: float) -> int | None:
    """Разностный хэш кадра 9×8: у перекодированных копий расходится на пару бит."""
    r = _run([tool("ffmpeg"), "-v", "error", "-ss", f"{max(at, 0):.2f}", "-i", str(path),
              "-frames:v", "1", "-vf", "scale=9:8:flags=area,format=gray",
              "-f", "rawvideo", "-"], timeout=30)
    px = r.stdout
    if len(px) < 72:
        return None
    bits = 0
    for y in range(8):
        row = px[y * 9:(y + 1) * 9]
        for x in range(8):
            bits = (bits << 1) | (row[x] > row[x + 1])
    return bits


def frame_png(path, at: float, height: int, headers=None) -> bytes:
    """Один кадр для ленты нарезки, PNG нужной высоты. Не вышло — пусто."""
    try:
        r = _run([tool("ffmpeg"), "-v", "error", *_headers(headers), "-ss", f"{max(at, 0):.3f}",
                  "-i", str(path), "-frames:v", "1", "-vf", f"scale=-2:{height}",
                  "-f", "image2pipe", "-vcodec", "png", "-"], timeout=30)
    except subprocess.TimeoutExpired:
        return b""
    return r.stdout if r.returncode == 0 else b""


def _gif_filter(width: int, fps: int, crop: str = "") -> str:
    # Длинная сторона не больше width, вторая — чётная и по пропорции.
    scale = (f"scale='if(gte(iw,ih),min({width},iw),-2)':"
             f"'if(gte(iw,ih),-2,min({width},ih))':flags=lanczos")
    chain = f"{crop + ',' if crop else ''}fps={fps},{scale}"
    # diff и rectangle: палитра по движущимся частям, перерисовывается только изменившееся.
    return (f"{chain},split[a][b];[a]palettegen=stats_mode=diff[p];"
            f"[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")


def to_gif(src, dst, start: float = 0.0, length: float = 0.0, crop: str = "",
           side: int = MAX_SIDE, fps: int = 20, headers=None) -> Path:
    """Кодирует в GIF без звука. Если не влезает в лимит, ужимает размер и частоту."""
    dst = Path(dst)
    tmp = dst.with_suffix(".part.gif")
    steps = [(side, fps), (min(side, 400), min(fps, 15)), (320, 12), (240, 10)]
    for width, rate in steps:
        args = [tool("ffmpeg"), "-v", "error", "-y", *_headers(headers)]
        if start > 0:
            args += ["-ss", f"{start:.3f}"]
        if length > 0:
            args += ["-t", f"{length:.3f}"]
        args += ["-i", str(src), "-an", "-sn",
                 "-filter_complex", _gif_filter(width, rate, crop),
                 "-loop", "0", "-f", "gif", str(tmp)]
        r = _run(args, timeout=600)
        if r.returncode != 0 or not tmp.exists():
            raise RuntimeError((r.stderr or b"").decode(errors="replace").strip()[-300:] or "ffmpeg")
        if tmp.stat().st_size <= LIMIT:
            break
    os.replace(tmp, dst)
    return dst


def keep_as_gif(src, dst) -> Path:
    """Готовую GIF подходящего размера копирует как есть, остальное перекодирует."""
    src, dst = Path(src), Path(dst)
    if src.suffix.lower() == ".gif" and src.stat().st_size <= LIMIT:
        info = probe(src)
        if max(info.width, info.height) <= 640:
            shutil.copyfile(src, dst)
            return dst
    return to_gif(src, dst)
