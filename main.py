import os, sys, traceback
from pathlib import Path

# Started from the shortcut with pythonw.exe there is no console: stdout/stderr are None
# and progress bars of libraries (model downloads) would crash. Send them to a log file.
LOG_DIR = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'CloudyClipStudio'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'app.log'
if sys.stdout is None or sys.stderr is None:
    _log = open(LOG_FILE, 'a', encoding='utf-8', buffering=1)
    if sys.stdout is None: sys.stdout = _log
    if sys.stderr is None: sys.stderr = _log


def _excepthook(exc_type, exc, tb):
    text = ''.join(traceback.format_exception(exc_type, exc, tb))
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f: f.write(text + '\n')
    except Exception:
        pass
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance():
            QMessageBox.critical(None, 'Cloudy Clip Studio — ошибка', f'{exc}\n\nПодробности сохранены в:\n{LOG_FILE}')
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = _excepthook

# NVIDIA DLL paths must be registered before anything imports ctranslate2 / faster_whisper.
from cloudy_clip.gpu import add_nvidia_dll_dirs
add_nvidia_dll_dirs()

from cloudy_clip.ui import main
if __name__ == '__main__':
    main()
