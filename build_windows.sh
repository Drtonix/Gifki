#!/bin/zsh
# Gifki для Windows, собирается на маке: переносимый Python с python.org,
# колёса PySide6 под win_amd64, ffmpeg под LGPL от BtbN, установщик NSIS.
# Результат — build/Gifki-Setup.exe. Ставится без прав администратора.
set -e
setopt null_glob
cd "${0:A:h}"
SRC="$PWD"
OUT="$SRC/build/windows"
DL="$SRC/build/downloads"
ROOT="$OUT/Gifki"
PY_VER=3.12.10
PY_URL="https://www.python.org/ftp/python/$PY_VER/python-$PY_VER-embed-amd64.zip"
FF_ZIP="ffmpeg-n8.1-latest-win64-lgpl-shared-8.1.zip"
FF_URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/$FF_ZIP"
VERSION=1.1

say() { print -P "%F{green}==>%f $*"; }

rm -rf "$OUT"
mkdir -p "$ROOT/python" "$ROOT/app/bin" "$DL"

say "переносимый Python $PY_VER"
[ -f "$DL/python-embed.zip" ] || curl -fsSL "$PY_URL" -o "$DL/python-embed.zip"
unzip -q "$DL/python-embed.zip" -d "$ROOT/python"
# Встраиваемый Python видит только то, что перечислено здесь: стандартную
# библиотеку, свои библиотеки и папку приложения.
cat > "$ROOT/python/python312._pth" <<'PTH'
python312.zip
.
Lib\site-packages
..\app
import site
PTH
# Имя процесса в диспетчере задач — имя файла: Gifki, а не pythonw.
cp "$ROOT/python/pythonw.exe" "$ROOT/python/Gifki.exe"

say "PySide6 под Windows"
SP="$ROOT/python/Lib/site-packages"
mkdir -p "$SP"
rm -rf "$DL/wheels"
python3.12 -m pip download -q PySide6 yt-dlp --platform win_amd64 --only-binary=:all: \
    --python-version 3.12 --implementation cp -d "$DL/wheels"
for w in "$DL/wheels"/*.whl; do unzip -q -o "$w" -d "$SP"; done

say "чистка лишнего"
P="$SP/PySide6"
# Нужны виджеты и QtMultimedia — на нём проигрыватель. Остальное выкидываем.
for m in WebEngine WebChannel WebSockets WebView Quick Qml Pdf 3D Charts DataVisualization \
         Graphs Designer Sensors SerialPort SerialBus Sql Test Bluetooth Nfc RemoteObjects \
         Scxml SpatialAudio StateMachine TextToSpeech Help UiTools Positioning Location \
         VirtualKeyboard HttpServer ShaderTools Quick3D Labs Concurrent Xml NetworkAuth \
         OpenGLWidgets Svg PrintSupport DBus MultimediaQuick MultimediaWidgets Lottie CanvasPainter; do
    rm -f "$P"/Qt6${m}*.dll "$P"/Qt${m}*.pyd "$P"/Qt${m}*.pyi
done
rm -rf "$P/qml" "$P/translations" "$P/resources" "$P/include" "$P/typesystems" \
       "$P/glue" "$P/doc" "$P/examples" "$P/scripts" "$P/metatypes" "$P/lib" \
       "$P/opengl32sw.dll" "$P"/*.exe "$P"/pyside6qml*.dll
for d in sqldrivers qmltooling designer webview position sensors geoservices \
         sceneparsers renderers canbus texttospeech virtualkeyboard qmllint \
         networkinformation printsupport scxmldatamodel generic geometryloaders \
         renderplugins assetimporters vectorimageformats platforminputcontexts iconengines; do
    rm -rf "$P/plugins/$d"
done
# Плагины, которым нужны выкинутые модули: без них они только пишут ошибки загрузки.
rm -f "$P/plugins/imageformats/qpdf.dll" "$P/plugins/imageformats/qsvg.dll" \
      "$P/plugins/platforms/qdirect2d.dll"
find "$SP" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$SP"/*.dist-info/RECORD

say "ffmpeg под LGPL"
[ -f "$DL/$FF_ZIP" ] || curl -fsSL "$FF_URL" -o "$DL/$FF_ZIP"
rm -rf "$DL/ff" && mkdir -p "$DL/ff"
unzip -q "$DL/$FF_ZIP" -d "$DL/ff"
FFB=$(find "$DL/ff" -type d -name bin | head -1)
cp "$FFB"/ffmpeg.exe "$FFB"/ffprobe.exe "$FFB"/*.dll "$ROOT/app/bin/"
FFL=$(dirname "$FFB")/LICENSE.txt

say "исходники и значок"
cp app.py actions.py i18n.py media.py relay.py sources.py store.py _style.py "$ROOT/app/"
# Свой набор каналов — только у себя, в репозитории его нет.
[ -f channels_local.py ] && cp channels_local.py "$ROOT/app/"
mkdir -p "$ROOT/app/icon"
cp icon/AppIcon.ico "$ROOT/app/icon/AppIcon.ico"
cp icon/AppIcon.ico "$ROOT/Gifki.ico"

say "лицензии"
LIC="$ROOT/Лицензии"
mkdir -p "$LIC"
cp "$ROOT/python/LICENSE.txt" "$LIC/Python.txt" 2>/dev/null || true
[ -f "$FFL" ] && cp "$FFL" "$LIC/ffmpeg.txt"
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
    Библиотеки Qt лежат отдельными файлами в python\Lib\site-packages\PySide6
    и не вкомпилированы в приложение, их можно заменить своими сборками.
    Исходники: https://download.qt.io/official_releases/qt/

ffmpeg — LGPL 2.1 или новее, сборка BtbN без компонентов под GPL.
    Лежит в app\bin. Исходники и параметры сборки:
    https://github.com/BtbN/FFmpeg-Builds

Python — PSF License
LICNOTE

say "установщик"
SIZE=$(du -sk "$ROOT" | cut -f1)
cat > "$OUT/gifki.nsi" <<NSI
Unicode true
SetCompressor /SOLID lzma
!include "MUI2.nsh"
Name "Gifki"
OutFile "$SRC/build/Gifki-Setup.exe"
InstallDir "\$LOCALAPPDATA\\Programs\\Gifki"
RequestExecutionLevel user
BrandingText "DrTonix · bdub.space"
!define MUI_ICON "$ROOT/Gifki.ico"
!define MUI_UNICON "$ROOT/Gifki.ico"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION Launch
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Russian"
VIProductVersion "$VERSION.0.0"
VIAddVersionKey /LANG=\${LANG_RUSSIAN} "ProductName" "Gifki"
VIAddVersionKey /LANG=\${LANG_RUSSIAN} "CompanyName" "DrTonix"
VIAddVersionKey /LANG=\${LANG_RUSSIAN} "FileDescription" "Установка Gifki"
VIAddVersionKey /LANG=\${LANG_RUSSIAN} "FileVersion" "$VERSION"
VIAddVersionKey /LANG=\${LANG_RUSSIAN} "LegalCopyright" "DrTonix · bdub.space"

Function Launch
  SetOutPath "\$INSTDIR\\app"
  Exec '"\$INSTDIR\\python\\Gifki.exe" "\$INSTDIR\\app\\app.py"'
FunctionEnd

Section
  SetOutPath "\$INSTDIR"
  ; Старая версия убирается целиком: иначе в папке остаются выкинутые модули Qt.
  RMDir /r "\$INSTDIR\\python"
  RMDir /r "\$INSTDIR\\app"
  File /r "$ROOT/*"
  SetOutPath "\$INSTDIR\\app"
  CreateShortcut "\$SMPROGRAMS\\Gifki.lnk" "\$INSTDIR\\python\\Gifki.exe" '"\$INSTDIR\\app\\app.py"' "\$INSTDIR\\Gifki.ico"
  CreateShortcut "\$DESKTOP\\Gifki.lnk" "\$INSTDIR\\python\\Gifki.exe" '"\$INSTDIR\\app\\app.py"' "\$INSTDIR\\Gifki.ico"
  WriteUninstaller "\$INSTDIR\\Удалить Gifki.exe"
  !define UNINST "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Gifki"
  WriteRegStr HKCU "\${UNINST}" "DisplayName" "Gifki"
  WriteRegStr HKCU "\${UNINST}" "DisplayVersion" "$VERSION"
  WriteRegStr HKCU "\${UNINST}" "Publisher" "DrTonix"
  WriteRegStr HKCU "\${UNINST}" "DisplayIcon" "\$INSTDIR\\Gifki.ico"
  WriteRegStr HKCU "\${UNINST}" "UninstallString" '"\$INSTDIR\\Удалить Gifki.exe"'
  WriteRegDWORD HKCU "\${UNINST}" "EstimatedSize" $SIZE
  WriteRegDWORD HKCU "\${UNINST}" "NoModify" 1
  WriteRegDWORD HKCU "\${UNINST}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  ; Подборка и очередь не трогаются: они в «Изображениях» и в AppData.
  Delete "\$SMPROGRAMS\\Gifki.lnk"
  Delete "\$DESKTOP\\Gifki.lnk"
  RMDir /r "\$INSTDIR"
  DeleteRegKey HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Gifki"
SectionEnd
NSI
# makensis падает с bad_alloc, если локаль не UTF-8 (в чистой оболочке она «C»).
LC_ALL=en_US.UTF-8 makensis -V2 "$OUT/gifki.nsi"

say "готово: $(du -sh "$ROOT" | cut -f1) в папке, установщик $(du -sh "$SRC/build/Gifki-Setup.exe" | cut -f1)"
