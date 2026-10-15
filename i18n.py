"""Язык интерфейса. Ключ перевода — сама русская строка.

Имена каналов, группы и метки М/Ж не переводятся: это данные гиф-сервера,
их читают боты."""
import os

from PySide6.QtCore import QLocale, QSettings

LANGS = ("ru", "en")
SETTINGS = os.environ.get("GIFKI_SETTINGS", "Gifki")

EN = {
    "Показать в Finder": "Show in Finder",
    "Показать в проводнике": "Show in Explorer",
    "с": "s",
    "Разбор": "Sort", "Нарезка": "Cut", "Сбор": "Collect", "Подборка": "Library",
    "О программе {name}": "About {name}",
    "Закрыть": "Close",
    "Вид": "View", "Язык": "Language", "Оформление": "Appearance",
    "Как в системе": "System", "Светлое": "Light", "Тёмное": "Dark",
    "Сохранить": "Save",
    "Отменить": "Undo",
    "Отменено": "Cancelled",
    "отменено": "cancelled",
    "Не вышло: {e}": "Failed: {e}",
    "Папка подборки": "Library folder",
    "Мужчина один": "One man", "Женщина одна": "One woman",
    "Мужчина — женщине": "Man to woman", "Женщина — мужчине": "Woman to man",
    "Мужчина — мужчине": "Man to man", "Женщина — женщине": "Woman to woman",
    "Пол не важен или не виден — подходит любой паре": "Gender doesn't matter or isn't visible — fits any pair",
    "{tip}. Клавиша {n}; с Shift — добавить к другим меткам": "{tip}. Key {n}; with Shift — add to other labels",
    "Все каналы — {n}": "All channels — {n}",
    "Все каналы": "All channels",
    "Канал этой гифки": "This GIF's channel",
    "Очередь: все каналы": "Queue: all channels",
    "Очередь: {name}": "Queue: {name}",
    "Какие каналы разбирать": "Which channels to sort",
    "Добавить файлы…": "Add files…",
    "Сохранить с меткой — кто действует и на кого. Shift — несколько меток, Enter — сохранить":
        "Save with a label — who acts on whom. Shift — several labels, Enter — save",
    "Выкинуть": "Drop", "Пропустить": "Skip", "В нарезку": "To Cut",
    "Следующий канал": "Next channel", "Перенести в канал…": "Move to channel…",
    "Больше не показывать": "Don't show again",
    "Отложить в конец этого канала": "Put off to the end of this channel",
    "Вырезать кусок в «Нарезке»": "Cut a piece in Cut",
    "Отложить весь канал, перейти к следующему": "Put off the whole channel, go to the next one",
    "Гифка подходит к другому действию": "The GIF fits another action",
    "Вернуть последнее решение": "Undo the last decision",
    "в очереди {n}": "{n} in queue",
    "в канале {here} · всего {n}": "{here} in channel · {n} total",
    "{ch} — позже": "{ch} — later",
    "В канале «{name}» пусто": "Channel “{name}” is empty",
    "Очередь пуста": "The queue is empty",
    "без канала": "no channel",
    "Сначала канал": "Choose a channel first",
    "выкинута": "dropped",
    "перенесена в {name}": "moved to {name}",
    "Видео по ссылке": "Video from a link",
    "Видео по ссылке…": "Video from a link…",
    "ссылка: YouTube, VK Видео, Rutube, файл — или запрос для поиска на YouTube":
        "link: YouTube, VK Video, Rutube, a file — or a YouTube search query",
    "Поиск…": "Searching…", "Открытие…": "Opening…", "Скачивание…": "Downloading…",
    "Ничего не нашлось": "Nothing found",
    "YouTube, VK Видео, Rutube, Одноклассники, Дзен или ссылка прямо на файл":
        "YouTube, VK Video, Rutube, OK, Dzen or a direct link to a file",
    "Открыть видео…": "Open video…",
    "Видео или гифка": "Video or GIF",
    "Обведите мышью, чтобы обрезать кадр; двойной щелчок — сбросить":
        "Drag to crop the frame; double-click to reset",
    "Края рамки — начало и конец; рамку можно тащить целиком. Щелчок — перемотка."
    " Колесо или щипок — масштаб, прокрутка вбок — сдвиг":
        "The frame edges are the start and end; drag the whole frame to move it. Click to seek."
        " Wheel or pinch to zoom, sideways scroll to pan",
    "Пуск": "Play", "Пауза": "Pause",
    "Пуск и пауза; стрелки — кадр, с Shift — секунда": "Play and pause; arrows — a frame, with Shift — a second",
    "Начало": "In", "Конец": "Out",
    "Начало отрезка — текущий кадр": "Segment start — the current frame",
    "Конец отрезка — текущий кадр": "Segment end — the current frame",
    "Предпросмотр": "Preview",
    "Собрать гифку из отрезка и показать как есть — с размером и весом. P или щелчок — закрыть":
        "Build the GIF from the segment and show it as is — with size and weight. P or click — close",
    "Сохранить выделенный отрезок как гифку: канал и метка. Видео остаётся открытым —"
    " следующий отрезок можно сразу в другой канал":
        "Save the selected segment as a GIF: channel and label. The video stays open —"
        " the next segment can go straight to another channel",
    "Канал…": "Channel…",
    "Канал: {name}": "Channel: {name}",
    "Куда сохранить отрезок": "Where to save the segment",
    "Ширина, px": "Width, px", "Кадров/с": "Frames/s",
    "Ширина гифки. Больше — чётче, но тяжелее; Discord берёт до 10 МБ":
        "GIF width. Larger is sharper but heavier; Discord takes up to 10 MB",
    "Плавность: больше кадров — плавнее и тяжелее": "Smoothness: more frames — smoother and heavier",
    "Размер будущей гифки в пикселях": "Size of the GIF in pixels",
    "Удалить последнюю сохранённую гифку": "Delete the last saved GIF",
    "Сборка предпросмотра…": "Building the preview…",
    "{w}×{h} · {mb} МБ — так гифка будет выглядеть": "{w}×{h} · {mb} MB — this is how the GIF will look",
    "Предпросмотр не собрался: {e}": "The preview failed: {e}",
    "Видео": "Video",
    "Видео и гифки": "Videos and GIFs",
    "Видео не открылось: {e}": "The video didn't open: {e}",
    "Поток не открылся — скачивание…": "The stream didn't open — downloading…",
    "отрезок {s}": "segment {s}",
    "кадр обрезан": "frame cropped",
    "отрывок": "clip",
    "Сохранено: {target} / {labels} · {s}": "Saved: {target} / {labels} · {s}",
    "Последняя гифка удалена": "The last GIF is deleted",
    "Каналы": "Channels",
    "Новый канал": "New channel",
    "Канал на гиф-сервере": "Channel on the GIF server",
    "Группа — папка в подборке": "Group — a folder in the library",
    "Теги Danbooru и Safebooru": "Danbooru and Safebooru tags",
    "Запрос Giphy — ищется как «anime …» и «cartoon …»": "Giphy query — searched as “anime …” and “cartoon …”",
    "Аниме-API — реакция: у всех API или одного, otaku, purr, nekoslife, nekosbest, waifu":
        "Anime APIs — a reaction: in all APIs or one of otaku, purr, nekoslife, nekosbest, waifu",
    "hug  или  otaku:hug": "hug  or  otaku:hug",
    "Взаимное: пара «парень и девушка» — сразу МЖ и ЖМ": "Mutual: a “guy and girl” pair counts as both МЖ and ЖМ",
    "  · свой": "  · custom",
    "Вернуть как было": "Restore defaults",
    "Удалить канал": "Delete channel",
    "Нужно название канала.": "The channel needs a name.",
    "Канал «{name}» уже есть.": "Channel “{name}” already exists.",
    "Таких реакций в аниме-API нет: ": "The anime APIs have no such reactions: ",
    "Источники": "Sources",
    "ключ API": "API key",
    "ID приложения": "App ID",
    "секрет": "secret",
    "Изменить…": "Edit…",
    "С каждого источника на канал": "From each source per channel",
    "Собрать": "Collect",
    "Остановить": "Stop",
    "Сбор…": "Collecting…",
    "Остановлено. Новых: {n}": "Stopped. New: {n}",
    "Новых: {n}": "New: {n}",
    ", отключён": ", disabled",
    "доступ закрыт (ответ {code})": "access denied (response {code})",
    "ответ {code}": "response {code}",
    "не отвечает": "not responding",
    "отвечает не тем": "unexpected response",
    "ключ не подошёл": "the key didn't work",
    "слишком большой файл": "file too large",
    "Канал": "Channel", "Очередь": "Queue", "Универсальные": "Universal",
    "гифка": "GIF",
    "{what} не сохранился: {e}": "{what} not saved: {e}",
    "Гифки и видео": "GIFs and videos",
    "Добавление: {n} из {total}": "Adding: {n} of {total}",
}

_BACK = {v: k for k, v in EN.items()}
_lang = None


def current():
    global _lang
    if _lang is None:
        saved = QSettings("local", SETTINGS).value("lang", "")
        if saved in LANGS:
            _lang = saved
        else:
            _lang = "ru" if QLocale.system().language() == QLocale.Russian else "en"
    return _lang


def set_current(lang):
    global _lang
    if lang in LANGS:
        _lang = lang
        QSettings("local", SETTINGS).setValue("lang", lang)


def key_of(text):
    if text in EN:
        return text
    return _BACK.get(text)


def t(s):
    return EN.get(s, s) if current() == "en" else s


def tf(fmt, **kw):
    return t(fmt).format(**kw)
