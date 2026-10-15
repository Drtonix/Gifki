#!/bin/zsh
# Самодостаточный Gifki.app: свой Python, Qt и ffmpeg.
set -e
setopt null_glob
cd "${0:A:h}"
SRC="$PWD"
OUT="$SRC/build"
APP="$OUT/Gifki.app"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.12.14%2B20260901-aarch64-apple-darwin-install_only_stripped.tar.gz"

say() { print -P "%F{green}==>%f $*"; }

rm -rf "$APP"
mkdir -p "$OUT" "$APP/Contents/MacOS" "$APP/Contents/Resources"
RES="$APP/Contents/Resources"

say "переносимый Python"
[ -f "$OUT/python.tar.gz" ] || curl -fsSL "$PY_URL" -o "$OUT/python.tar.gz"
mkdir -p "$RES/python"
tar xzf "$OUT/python.tar.gz" -C "$RES/python" --strip-components=1
PY="$RES/python/bin/python3"

say "библиотеки"
"$PY" -m pip -q install --upgrade pip
# yt-dlp модулем, а не бинарником: тот распаковывает себя при каждом запуске.
"$PY" -m pip -q install PySide6 yt-dlp

say "чистка лишнего"
SP="$RES/python/lib/python3.12/site-packages"
# Нужны виджеты и QtMultimedia — на нём проигрыватель. Остальное выкидываем.
for m in Qt3D QtCharts QtDataVis QtDesigner QtQuick3D QtSensors QtSerial QtSql \
         QtTest QtBluetooth QtNfc QtRemoteObjects QtScxml QtSpatialAudio \
         QtStateMachine QtTextToSpeech QtHelp QtUiTools QtPdf QtMultimediaQuick \
         QtWebEngine QtWebView QtWebChannel QtWebSockets QtPositioning \
         QtLocation QtQuick QtQml QtGraphs QtVirtualKeyboard QtHttpServer; do
    rm -rf "$SP/PySide6/Qt/lib/${m}"*.framework "$SP/PySide6/${m}"* 2>/dev/null || true
done
rm -rf "$SP/PySide6/Qt/translations" "$SP/PySide6/Qt/qml" \
       "$SP/PySide6/Designer.app" "$SP/PySide6/assistant.app" \
       "$SP/PySide6/linguist.app" "$SP/PySide6/examples" 2>/dev/null || true
find "$SP" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$RES/python/lib" -name "test" -type d -prune -exec rm -rf {} + 2>/dev/null || true

say "ffmpeg"
# Своя сборка: готовые либо x86_64, либо с --enable-nonfree (распространять
# нельзя). Здесь arm64 и чистый LGPL 2.1. Сеть и системный TLS macOS нужны
# нарезке потокового видео: ffmpeg берёт с сервера только вырезанные секунды.
mkdir -p "$RES/app/bin" "$OUT/tools"
if [ ! -f "$OUT/tools/ffmpeg" ]; then
    say "  сборка ffmpeg из исходников, это несколько минут"
    rm -rf "$OUT/ffsrc"; mkdir -p "$OUT/ffsrc"
    curl -fsSL "https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz" -o "$OUT/ffsrc/ff.tar.xz"
    tar xf "$OUT/ffsrc/ff.tar.xz" -C "$OUT/ffsrc" --strip-components=1
    ( cd "$OUT/ffsrc" && ./configure --prefix="$OUT/ffsrc/out" --disable-doc \
        --disable-ffplay --disable-debug --enable-small --disable-autodetect \
        --enable-zlib --enable-videotoolbox --enable-securetransport >/dev/null 2>&1 \
      && make -j"$(sysctl -n hw.ncpu)" >/dev/null 2>&1 \
      && make install >/dev/null 2>&1 )
    cp "$OUT/ffsrc/out/bin/ffmpeg" "$OUT/ffsrc/out/bin/ffprobe" "$OUT/tools/"
    rm -rf "$OUT/ffsrc"
fi
cp "$OUT/tools/ffmpeg" "$OUT/tools/ffprobe" "$RES/app/bin/"
chmod +x "$RES/app/bin/"*

say "исходники"
cp app.py actions.py i18n.py media.py relay.py sources.py store.py _style.py "$RES/app/"
# Свой набор каналов — только у себя, в репозитории его нет.
[ -f channels_local.py ] && cp channels_local.py "$RES/app/"

say "лицензии"
LIC="$RES/Лицензии"
mkdir -p "$LIC"
# find, а не шаблон: zsh на пустом совпадении падает, а с set -e рвёт сборку.
find "$SP" -maxdepth 1 -type d -name "*.dist-info" | while read -r d; do
    pkg=$(basename "$d" .dist-info)
    find "$d" -maxdepth 2 \( -name "LICENSE*" -o -name "COPYING*" -o -name "NOTICE*" \) \
        -type f 2>/dev/null | while read -r f; do
        mkdir -p "$LIC/$pkg"
        cp "$f" "$LIC/$pkg/" 2>/dev/null || true
    done
done
cat > "$LIC/О лицензиях.txt" <<'LICNOTE'
Из чего собран Gifki и на каких условиях.

Qt / PySide6 — LGPL 3.0
    Библиотеки Qt лежат в приложении отдельными файлами и не вкомпилированы
    в него, поэтому их можно заменить своими сборками. Исходники:
    https://download.qt.io/official_releases/qt/

ffmpeg — LGPL 2.1 или новее
    Собран без компонентов под GPL: ./configure --disable-doc --disable-ffplay
    --disable-debug --enable-small --disable-autodetect --enable-zlib
    --enable-videotoolbox --enable-securetransport
    Исходники: https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz

Python — PSF License
LICNOTE

say "интерпретатор в MacOS"
# macOS зовёт программу по имени файла процесса: питон из Resources даёт
# в доке ракету и имя «python3». Интерпретатор кладём в MacOS под именем
# приложения; он статический, свою установку находит по PYTHONHOME.
cp "$RES/python/bin/python3.12" "$APP/Contents/MacOS/Gifki"

say "оболочка"
cat > "$APP/Contents/MacOS/launcher" <<'LAUNCH'
#!/bin/zsh
LOG="$HOME/Library/Logs/Gifki.log"
mkdir -p "$HOME/Library/Logs"
# Проигрыватель Qt пишет в лог по несколько строк на каждую показанную гифку.
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG")" -gt 5000000 ]; then : > "$LOG"; fi
exec >> "$LOG" 2>&1
echo "=== запуск $(date) ==="
DIR="${0:A:h}"
RES="$DIR/../Resources"
export PATH="$RES/app/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONHOME="$RES/python"
# Бандл подписан и после установки не меняется: запись внутрь — и macOS
# при следующем запуске проверяет его заново. Байт-код собран заранее.
export PYTHONDONTWRITEBYTECODE=1
cd "$RES/app"
exec "$DIR/Gifki" "$RES/app/app.py"
LAUNCH
chmod +x "$APP/Contents/MacOS/launcher"
# Assets.car — значок в светлом и тёмном варианте; icns — для старых систем.
cp icon/AppIcon.icns "$RES/AppIcon.icns"
cp icon/Assets.car "$RES/Assets.car"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleDevelopmentRegion</key><string>ru</string>
<key>CFBundleLocalizations</key><array><string>ru</string><string>en</string></array>
<key>CFBundleDisplayName</key><string>Gifki</string>
<key>CFBundleExecutable</key><string>launcher</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundleIconName</key><string>AppIcon</string>
<key>CFBundleIdentifier</key><string>space.bdub.gifki</string>
<key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
<key>CFBundleName</key><string>Gifki</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSDocumentsFolderUsageDescription</key><string>Gifki добавляет гифки и видео из папки «Документы».</string>
<key>NSDownloadsFolderUsageDescription</key><string>Gifki добавляет гифки и видео из папки «Загрузки».</string>
<key>NSDesktopFolderUsageDescription</key><string>Gifki добавляет гифки и видео с рабочего стола.</string>
<key>NSRemovableVolumesUsageDescription</key><string>Gifki открывает видео с внешних дисков.</string>
<key>NSHumanReadableCopyright</key><string>DrTonix · bdub.space</string>
</dict></plist>
PLIST

say "байт-код"
"$PY" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$RES/python/lib/python3.12" >/dev/null 2>&1 || true
"$PY" -m compileall -q --invalidation-mode unchecked-hash "$RES/app" >/dev/null

say "подпись"
# Без подписи macOS считает скачанное приложение повреждённым, а первый запуск
# большого бандла после установки идёт около 29 с.
codesign --force --deep --sign - "$APP" 2>/dev/null
codesign --verify --deep --strict "$APP"

say "готово: $(du -sh "$APP" | cut -f1)  ->  $APP"

# Копия в build — не второе приложение в Launchpad и Spotlight: снимаем с учёта.
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u "$APP" >/dev/null 2>&1 || true
