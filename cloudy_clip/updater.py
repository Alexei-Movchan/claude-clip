"""Updates from GitHub Releases: check on start, download, verify, swap files, restart.

The release must contain an asset named Cloudy_Clip_Studio_Source.zip (made by
tools/make_release.py). User data is never touched: .venv, settings (in the user
profile), and output videos (in Videos) stay where they are.
"""
from __future__ import annotations
import hashlib, json, os, re, shutil, subprocess, tempfile, urllib.request, zipfile
from pathlib import Path
from typing import Callable

APP_VERSION = '1.8.0'
DEFAULT_OWNER = 'Alexei-Movchan'
DEFAULT_REPO = 'claude-clip'
ASSET_NAME = 'Cloudy_Clip_Studio_Source.zip'
GITHUB_API = 'https://api.github.com/repos/{owner}/{repo}/releases/latest'


class UpdateError(RuntimeError):
    pass


def parse_version(text: str) -> tuple[int, int, int]:
    nums = [int(n) for n in re.findall(r'\d+', text or '')[:3]]
    return tuple(nums + [0] * (3 - len(nums)))  # type: ignore[return-value]


def is_newer(tag: str, current: str = APP_VERSION) -> bool:
    return parse_version(tag) > parse_version(current)


def check_release(owner: str = DEFAULT_OWNER, repo: str = DEFAULT_REPO) -> dict:
    owner, repo = (owner or DEFAULT_OWNER).strip(), (repo or DEFAULT_REPO).strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', owner) or not re.fullmatch(r'[A-Za-z0-9_.-]+', repo):
        raise UpdateError('Укажите корректные GitHub owner и repository.')
    req = urllib.request.Request(GITHUB_API.format(owner=owner, repo=repo), headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'CloudyClipStudio-Updater',
        'X-GitHub-Api-Version': '2022-11-28'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 404: raise UpdateError('В репозитории пока нет опубликованных версий.') from e
        raise UpdateError(f'GitHub ответил ошибкой {e.code}.') from e
    except Exception as e:
        raise UpdateError(f'Не удалось проверить обновления: {e}') from e
    if data.get('draft') or data.get('prerelease'):
        raise UpdateError('Последний релиз — черновик или предварительная версия.')
    asset = next((a for a in data.get('assets') or [] if a.get('name') == ASSET_NAME), None)
    if not asset:
        raise UpdateError(f'В релизе нет файла {ASSET_NAME}.')
    digest = asset.get('digest') or ''
    return {'tag': data.get('tag_name', ''), 'name': data.get('name') or data.get('tag_name', ''),
            'html_url': data.get('html_url', ''), 'body': data.get('body') or '',
            'asset_url': asset['browser_download_url'], 'asset_size': int(asset.get('size') or 0),
            'sha256': digest.split(':', 1)[1].lower() if digest.startswith('sha256:') else ''}


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ''


HELPER = r'''@echo off
setlocal
title Cloudy Clip Studio - updating
set "TARGET=%~1"
set "SOURCE=%~2"
set "STAGING=%~3"
set "APP_PID=%~4"
set "DEPS=%~5"
set "GPUDEPS=%~6"
echo Updating Cloudy Clip Studio. Please wait...
:waitloop
tasklist /FI "PID eq %APP_PID%" 2>nul | find "%APP_PID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto waitloop
)
robocopy "%SOURCE%" "%TARGET%" /E /R:3 /W:1 /XD .venv __pycache__ .git /XF .env /NFL /NDL /NJH /NJS /NP
if errorlevel 8 goto failed
cd /d "%TARGET%"
if "%DEPS%"=="1" (
    echo Installing new packages...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
)
if "%GPUDEPS%"=="1" (
    echo Updating GPU libraries...
    ".venv\Scripts\python.exe" -m pip install -r requirements-gpu.txt
)
rmdir /s /q "%STAGING%" >nul 2>nul
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%TARGET%\main.py"
) else (
    start "" "%TARGET%\run.bat"
)
exit /b 0
:failed
echo.
echo [ERROR] The update could not be applied. Your previous version was kept where possible.
echo Take a screenshot of this window.
pause
exit /b 1
'''


def download_and_stage(release: dict, install_dir: str | Path,
                       progress: Callable[[int, int], None] | None = None) -> Path:
    """Download + verify + unpack, then start the helper that swaps files after the app exits.

    The caller must quit the application right after this returns.
    """
    install_dir = Path(install_dir).resolve()
    staging = Path(tempfile.mkdtemp(prefix='cloudy_update_'))
    archive = staging / 'update.zip'
    req = urllib.request.Request(release['asset_url'], headers={'User-Agent': 'CloudyClipStudio-Updater'})
    try:
        with urllib.request.urlopen(req, timeout=60) as response, archive.open('wb') as out:
            total = int(response.headers.get('Content-Length') or release.get('asset_size') or 0)
            done = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk: break
                out.write(chunk); done += len(chunk)
                if progress: progress(done, total)
        if release.get('asset_size') and archive.stat().st_size != release['asset_size']:
            raise UpdateError('Файл обновления скачался не полностью. Попробуйте ещё раз.')
        if release.get('sha256') and _file_hash(archive) != release['sha256']:
            raise UpdateError('Контрольная сумма обновления не совпала — файл повреждён. Попробуйте ещё раз.')
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            if not names or any(Path(n).is_absolute() or '..' in Path(n).parts for n in names):
                raise UpdateError('Архив обновления имеет небезопасную структуру.')
            zf.extractall(staging / 'payload')
    except Exception as e:
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(e, UpdateError): raise
        raise UpdateError(f'Не удалось скачать или распаковать обновление: {e}') from e
    payload = staging / 'payload'
    roots = list(payload.iterdir())
    source = roots[0] if len(roots) == 1 and roots[0].is_dir() else payload
    if not (source / 'main.py').exists() or not (source / 'cloudy_clip').is_dir():
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError('В архиве не найдена ожидаемая структура Cloudy Clip Studio.')
    deps = _file_hash(source / 'requirements.txt') != _file_hash(install_dir / 'requirements.txt')
    gpu_deps = False
    if _file_hash(source / 'requirements-gpu.txt') != _file_hash(install_dir / 'requirements-gpu.txt'):
        try:
            from .gpu import gpu_libs_installed
            gpu_deps = gpu_libs_installed()  # only refresh GPU libraries for people who installed them
        except Exception:
            gpu_deps = False
    helper = Path(tempfile.gettempdir()) / 'cloudy_apply_update.bat'
    helper.write_text(HELPER.replace('\n', '\r\n'), encoding='ascii')
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
    subprocess.Popen(['cmd.exe', '/c', str(helper), str(install_dir), str(source), str(staging), str(os.getpid()),
                      '1' if deps else '0', '1' if gpu_deps else '0'], cwd=str(install_dir), creationflags=flags)
    return staging
