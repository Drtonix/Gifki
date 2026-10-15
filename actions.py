"""Каналы гиф-сервера. Одно действие — один канал, пол — метка в тексте сообщения.

М / Ж — одиночное действие. МЖ / ЖМ / ММ / ЖЖ — автор, затем адресат.
Без метки — универсальная гифка, подходит любому режиму.
"""
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

LABELS = ("М", "Ж", "МЖ", "ЖМ", "ММ", "ЖЖ")
UNIVERSAL = "Универсальные"


@dataclass(frozen=True)
class Channel:
    name: str
    group: str
    en: str = ""              # запрос к Giphy: «anime …»
    booru: tuple = ()         # теги Danbooru и Safebooru, каждый идёт в паре с animated
    apis: tuple = ()          # категории аниме-API, «источник:категория»
    mutual: bool = False      # взаимное: пара «парень и девушка» годится и как МЖ, и как ЖМ
    collect: bool = True


def _c(name, group, en="", booru=(), apis=(), mutual=False, collect=True):
    return Channel(name, group, en, tuple(booru), tuple(apis), mutual, collect)


CHANNELS = [
    _c("поцеловать", "общие", "kiss", ["kiss", "kissing_cheek", "kissing_forehead"],
       ["otaku:kiss", "purr:kiss", "nekoslife:kiss", "nekosbest:kiss", "nekosbest:peck", "waifu:kiss"], mutual=True),
    _c("обнять", "общие", "hug", ["hug", "hug_from_behind", "glomp"],
       ["otaku:hug", "purr:hug", "nekoslife:hug", "nekosbest:hug", "waifu:hug", "waifu:glomp"], mutual=True),
    _c("погладить", "общие", "head pat", ["headpat"],
       ["otaku:pat", "purr:pat", "nekoslife:pat", "nekosbest:pat", "waifu:pat"]),
    _c("шлёпнуть", "общие", "slap", ["slapping"],
       ["otaku:slap", "purr:slap", "nekoslife:slap", "nekosbest:slap", "waifu:slap"]),
    _c("ткнуть", "общие", "poke", ["poking", "cheek_poking"],
       ["otaku:poke", "purr:poke", "nekosbest:poke", "waifu:poke"]),
    _c("защекотать", "общие", "tickle", ["tickling"],
       ["otaku:tickle", "purr:tickle", "nekoslife:tickle", "nekosbest:tickle"]),
    _c("прижаться", "общие", "cuddle", ["cuddling"],
       ["otaku:cuddle", "purr:cuddle", "nekoslife:cuddle", "nekosbest:cuddle", "waifu:cuddle"], mutual=True),
    _c("лизнуть", "общие", "lick", ["licking"], ["otaku:lick", "purr:lick", "waifu:lick"]),
    _c("укусить", "общие", "bite", ["biting"],
       ["otaku:bite", "purr:bite", "nekosbest:bite", "waifu:bite"]),
    _c("ударить", "общие", "punch", ["punching"], ["otaku:punch", "nekosbest:punch"]),
    _c("уставиться", "общие", "stare", ["staring"], ["otaku:stare", "nekosbest:stare"]),
    _c("чай", "общие", "drinking tea", ["tea"], ["otaku:sip"]),
    _c("помахать", "общие", "wave", ["waving"],
       ["otaku:wave", "nekosbest:wave", "waifu:wave"]),

    _c("воздушный-поцелуй", "эмоции", "blow kiss", ["blowing_kiss"], ["otaku:airkiss"]),
    _c("взять-за-руку", "эмоции", "holding hands", ["holding_hands"],
       ["otaku:handhold", "nekosbest:handhold", "waifu:handhold"], mutual=True),
    _c("уткнуться", "эмоции", "nuzzle", ["nuzzle", "head_on_chest"], ["otaku:nuzzle"]),
    _c("признаться", "эмоции", "love confession", ["confession", "love_letter"], ["otaku:love"]),
    _c("ущипнуть", "эмоции", "cheek pinch", ["cheek_pinching"], ["otaku:pinch"]),
    _c("подзатыльник", "эмоции", "bonk", ["karate_chop", "bonk"], ["otaku:smack"]),
    _c("подмигнуть", "эмоции", "wink", ["one_eye_closed"],
       ["otaku:wink", "nekosbest:wink", "waifu:wink"]),
    _c("показать-язык", "эмоции", "tongue out", ["akanbe", "tongue_out"], ["otaku:bleh"]),
    _c("подглядеть", "эмоции", "peek", ["peeking_out", "peeking"], ["otaku:peek"]),
    _c("кулачок", "эмоции", "fist bump", ["fist_bump"], ["otaku:brofist"], mutual=True),
    _c("похлопать", "эмоции", "clapping", ["clapping"], ["otaku:clap"]),
    _c("медленно-похлопать", "эмоции", "slow clap", [], ["otaku:slowclap"]),
    _c("одобрить", "эмоции", "thumbs up", ["thumbs_up"], ["otaku:thumbsup", "nekosbest:thumbsup"]),
    _c("извиниться", "эмоции", "sorry", ["apologizing", "bowing", "dogeza"], ["otaku:sorry"]),
    _c("чокнуться", "эмоции", "cheers", ["toast_(gesture)"], ["otaku:cheers"], mutual=True),
    _c("угостить", "эмоции", "feeding", ["feeding", "incoming_food"],
       ["nekoslife:feed", "nekosbest:feed"]),
    _c("радость", "эмоции", "happy", ["happy"], ["otaku:happy", "nekosbest:happy", "waifu:happy"]),
    _c("улыбка", "эмоции", "smile", ["smile"],
       ["otaku:smile", "purr:smile", "nekosbest:smile", "waifu:smile"]),
    _c("смех", "эмоции", "laugh", ["laughing"], ["otaku:laugh", "nekosbest:laugh"]),
    _c("ура", "эмоции", "yay", ["\\o/", "cheering"], ["otaku:yay"]),
    _c("праздник", "эмоции", "celebrate", ["confetti", "party"], ["otaku:celebrate"]),
    _c("танец", "эмоции", "dance", ["dancing"],
       ["otaku:dance", "purr:dance", "nekosbest:dance", "waifu:dance"]),
    _c("песня", "эмоции", "singing", ["singing"], ["otaku:sing"]),
    _c("смущение", "эмоции", "blush", ["embarrassed", "blush"],
       ["otaku:blush", "purr:blush", "nekosbest:blush", "waifu:blush"]),
    _c("стеснение", "эмоции", "shy", ["shy"], ["otaku:shy"]),
    _c("обида", "эмоции", "pout", ["pout"], ["otaku:pout", "purr:pout", "nekosbest:pout"]),
    _c("слёзы", "эмоции", "cry", ["crying"],
       ["otaku:cry", "purr:cry", "nekosbest:cry", "waifu:cry"]),
    _c("грусть", "эмоции", "sad", ["sad"], ["otaku:sad"]),
    _c("вздох", "эмоции", "sigh", ["sigh"], ["otaku:sigh"]),
    _c("усталость", "эмоции", "tired", [], ["otaku:tired"]),
    _c("зевота", "эмоции", "yawn", ["yawning"], ["otaku:yawn", "nekosbest:yawn"]),
    _c("сон", "эмоции", "sleep", ["sleeping"], ["otaku:sleep", "nekosbest:sleep"]),
    _c("непонимание", "эмоции", "confused", ["confused", "?"], ["otaku:confused"]),
    _c("пожать-плечами", "эмоции", "shrug", ["shrugging"], ["otaku:shrug", "nekosbest:shrug"]),
    _c("фейспалм", "эмоции", "facepalm", ["facepalm"], ["otaku:facepalm", "nekosbest:facepalm"]),
    _c("волнение", "эмоции", "nervous", ["nervous", "nervous_sweating"], ["otaku:nervous"]),
    _c("испуг", "эмоции", "scared", ["scared"], ["otaku:scared"]),
    _c("удивление", "эмоции", "surprised", ["surprised"], ["otaku:surprised"]),
    _c("восторг", "эмоции", "excited", ["sparkling_eyes", "excited"], ["otaku:woah"]),
    _c("невозмутимость", "эмоции", "unbothered", ["expressionless", "smug"], ["otaku:cool"]),
]

GROUPS = ("общие", "эмоции")
KEYS = {}           # ключи из выгрузок ботов: «Обнять (hug)» → канал
ALIASES = {}        # другие названия тех же действий

# Свой набор (channels_local.py рядом) заменяет встроенный целиком: группы,
# каналы и ключи выгрузок — у каждого гиф-сервера свои.
try:
    import channels_local as _local
except ImportError:
    _local = None
if _local is not None:
    CHANNELS = list(_local.CHANNELS)
    GROUPS = tuple(_local.GROUPS)
    KEYS = dict(getattr(_local, "KEYS", {}))
    ALIASES = dict(getattr(_local, "ALIASES", {}))

BY_NAME = {c.name: c for c in CHANNELS}
DEFAULTS = dict(BY_NAME)
API_SOURCES = ("otaku", "purr", "nekoslife", "nekosbest", "waifu")
# Наборы у аниме-API закрытые: только эти реакции, только гифки, без 18+.
API_CATEGORIES = {
    "otaku": set("""airkiss angrystare bite bleh blush brofist celebrate cheers clap confused cool
        cry cuddle dance drool evillaugh facepalm handhold happy headbang hug huh kiss laugh lick
        love mad nervous no nom nosebleed nuzzle nyah pat peek pinch poke pout punch roll run sad
        scared shout shrug shy sigh sing sip slap sleep slowclap smack smile smug sneeze sorry
        stare stop surprised sweat thumbsup tickle tired wave wink woah yawn yay yes""".split()),
    "purr": set("""angry bite blush comfy cry cuddle dance fluff hug kiss lay lick pat poke pout
        slap smile tail tickle""".split()),
    "nekoslife": set("hug pat cuddle tickle feed slap kiss smug".split()),
    "nekosbest": set("""baka bite blush bored cry cuddle dance facepalm feed handhold handshake
        happy highfive hug kick kiss laugh lurk nod nom nope pat peck poke pout punch run shoot
        shrug slap sleep smile smug stare think thumbsup tickle wave wink yawn yeet""".split()),
    "waifu": set("""bully cuddle cry hug awoo kiss lick pat smug bonk yeet blush smile wave highfive
        handhold nom bite glomp slap kill kick happy wink poke dance cringe""".split()),
}


def searchable(ch) -> bool:
    return ch.collect and bool(ch.booru or ch.apis or ch.en)


def clean_name(text: str) -> str:
    """Как Discord называет канал: строчные, пробелы — дефисы, без знаков."""
    name = re.sub(r"\s+", "-", text.strip().lower())
    return re.sub(r"[^\w-]", "", name).strip("-_")


def clean_tags(text) -> list:
    """Теги бур: по одному, без метатегов вроде rating: и без исключений через минус —
    рейтинг сборщик задаёт сам, а лишний тег упирается в предел Danbooru."""
    items = text.split() if isinstance(text, str) else list(text)
    out = []
    for t in items:
        t = t.strip().strip(",").lower()
        if t and ":" not in t and t[0] not in "-~" and t not in out:
            out.append(t)
    return out


def clean_apis(text) -> tuple:
    """«otaku:hug» — категория одного API, просто «hug» — у всех, где она есть.
    Возвращает найденное и слова, которых нет ни в одном наборе."""
    items = text.replace(",", " ").split() if isinstance(text, str) else list(text)
    out, unknown = [], []
    for a in items:
        a = a.strip().lower()
        src, _, cat = a.partition(":")
        pairs = [(src, cat)] if cat else [(s, src) for s in API_SOURCES]
        hits = [f"{s}:{c}" for s, c in pairs if c in API_CATEGORIES.get(s, ())]
        if not hits and a not in unknown:
            unknown.append(a)
        out += [h for h in hits if h not in out]
    return out, unknown


def entry(ch) -> dict:
    return {"name": ch.name, "group": ch.group, "booru": list(ch.booru), "en": ch.en,
            "apis": list(ch.apis), "mutual": ch.mutual}


def apply(entries):
    """Встроенные каналы с правками плюс свои. Списки меняются на месте: на них
    уже держат ссылки остальные модули."""
    by = dict(DEFAULTS)
    custom = []
    for e in entries:
        name = clean_name(e.get("name", ""))
        if not name:
            continue
        fields = dict(group=e.get("group") if e.get("group") in GROUPS else GROUPS[0],
                      en=str(e.get("en", "")).strip().lower(),
                      booru=tuple(clean_tags(e.get("booru", ()))),
                      apis=tuple(clean_apis(e.get("apis", ()))[0]),
                      mutual=bool(e.get("mutual")))
        if name in by:
            by[name] = replace(by[name], **fields)
        else:
            custom.append(Channel(name=name, **fields))
    ordered = []
    for g in GROUPS:
        ordered += [by[n] for n in DEFAULTS if by[n].group == g]
        ordered += [c for c in custom if c.group == g]
    CHANNELS[:] = ordered
    BY_NAME.clear()
    BY_NAME.update({c.name: c for c in CHANNELS})


def load(path) -> list:
    try:
        entries = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        entries = []
    entries = [e for e in entries if isinstance(e, dict)]
    apply(entries)
    return entries


def save(path, entries):
    Path(path).write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    apply(entries)

def channel_for_folder(name: str):
    """Канал по имени папки: «обнять», «Обнять (hug)», «взять-за-руку»."""
    low = name.strip().lower()
    if low in BY_NAME:
        return low
    if "(" in low and low.endswith(")"):
        key = low[low.rindex("(") + 1:-1].strip()
        if key in KEYS:
            return KEYS[key]
        low = low[:low.rindex("(")].strip()
    dashed = low.replace(" ", "-")
    if dashed in BY_NAME:
        return dashed
    return ALIASES.get(dashed)


def suggest(channel: str, tags: set) -> tuple:
    """Метки по составу сцены из тегов бур. Пусто, если теги не решают."""
    def count(word):
        n = 0
        for t in tags:
            if t == f"1{word}":
                n = max(n, 1)
            elif t == f"2{word}s":
                n = max(n, 2)
            elif t[:1].isdigit() and t.endswith(f"{word}s"):
                n = max(n, 3)
            elif t == f"multiple_{word}s":
                n = max(n, 2)
        return n

    girls, boys, others = count("girl"), count("boy"), count("other")
    if others:
        return ()
    if girls + boys == 1:
        return ("Ж",) if girls else ("М",)
    if girls == 2 and not boys:
        return ("ЖЖ",)
    if boys == 2 and not girls:
        return ("ММ",)
    if girls == 1 and boys == 1:
        ch = BY_NAME.get(channel)
        return ("МЖ", "ЖМ") if ch and ch.mutual else ()
    return ()


def label_folder(labels) -> str:
    return " ".join(l for l in LABELS if l in labels) or UNIVERSAL
