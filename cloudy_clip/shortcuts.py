"""Desktop / Start-menu shortcuts that start the app without a console window."""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path

APP_NAME = 'Cloudy Clip Studio'
APP_DIR = Path(__file__).resolve().parents[1]


def _ps(script: str) -> str:
    p = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
                       creationflags=0x08000000)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip()[:400])
    return p.stdout.strip()


def _folders() -> list[Path]:
    # GetFolderPath handles a Desktop moved into OneDrive; Programs = Start menu.
    out = _ps("[Environment]::GetFolderPath('Desktop'); [Environment]::GetFolderPath('Programs')")
    return [Path(line.strip()) for line in out.splitlines() if line.strip()]


def shortcut_paths() -> list[Path]:
    if os.name != 'nt': return []
    try:
        return [f / f'{APP_NAME}.lnk' for f in _folders()]
    except Exception:
        return []


def shortcut_exists() -> bool:
    paths = shortcut_paths()
    return bool(paths) and paths[0].exists()


def create_shortcuts(app_dir: Path = APP_DIR) -> list[Path]:
    if os.name != 'nt':
        raise RuntimeError('Ярлыки создаются только в Windows.')
    pythonw = app_dir / '.venv' / 'Scripts' / 'pythonw.exe'
    if not pythonw.exists():
        raise RuntimeError('Не найдено окружение .venv — сначала запустите install.bat.')
    icon = app_dir / 'assets' / 'icon.ico'
    made = []
    for lnk in shortcut_paths():
        lnk.parent.mkdir(parents=True, exist_ok=True)
        q = lambda p: str(p).replace("'", "''")  # PowerShell single-quote escaping
        _ps("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('" + q(lnk) + "');"
            "$s.TargetPath='" + q(pythonw) + "';"
            "$s.Arguments='\"" + q(app_dir / 'main.py') + "\"';"
            "$s.WorkingDirectory='" + q(app_dir) + "';"
            "$s.IconLocation='" + q(icon) + ",0';"
            "$s.Description='Нарезка длинных видео на вертикальные ролики';"
            "$s.Save()")
        made.append(lnk)
    return made


if __name__ == '__main__':  # used by install.bat:  python -m cloudy_clip.shortcuts
    try:
        for p in create_shortcuts():
            print('Shortcut created:', p.encode('ascii', 'replace').decode())
    except Exception as e:
        print('[WARNING] Could not create shortcuts:', str(e).encode('ascii', 'replace').decode())
        sys.exit(0)
