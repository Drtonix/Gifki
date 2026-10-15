# Third-party components

The MIT license in `LICENSE` covers the code in this repository only. The
distributed application also contains the components below. Their full license
texts are inside the bundle, in `Contents/Resources/Лицензии`.

## Bundled in the application

| Component | Version | License | Source |
|---|---|---|---|
| Qt (via PySide6) | 6.11.2 | LGPL-3.0 | https://download.qt.io/official_releases/QtForPython/ |
| FFmpeg (macOS) | 7.1 | LGPL-2.1-or-later | https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz |
| FFmpeg (Windows) | 8.1, BtbN LGPL shared build | LGPL-2.1-or-later | https://github.com/BtbN/FFmpeg-Builds |
| CPython | 3.12 | PSF-2.0 | https://github.com/astral-sh/python-build-standalone, https://www.python.org |
| yt-dlp | 2026.8.19 | Unlicense | https://github.com/yt-dlp/yt-dlp |

FFmpeg for macOS is built from unmodified upstream sources with
`--disable-autodetect` and no GPL components enabled, so it is distributed
under LGPL-2.1. The exact configure flags are in `build_app.sh`.

Qt and FFmpeg are dynamically linked. To relink the application against your
own builds, replace the libraries in the bundled `PySide6` folder or the
`ffmpeg` and `ffprobe` binaries in `Contents/Resources/app/bin`.
