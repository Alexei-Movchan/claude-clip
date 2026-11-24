"""Build release/Cloudy_Clip_Studio_Source.zip from the files tracked by git.

Usage:  python tools/make_release.py
Then publish a GitHub release whose tag matches APP_VERSION (e.g. v1.7.0) and attach the zip.
The app's updater downloads exactly this asset name.
"""
from __future__ import annotations
import re, subprocess, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = 'CloudyClipStudio'


def main() -> int:
    version = re.search(r"APP_VERSION = '([^']+)'", (ROOT / 'cloudy_clip' / 'updater.py').read_text(encoding='utf-8')).group(1)
    file_version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    if version != file_version:
        print(f'VERSION ({file_version}) != APP_VERSION ({version})'); return 1
    files = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split('\n')
    files = [f for f in files if f and not f.startswith(('tools/', '.github/'))]
    out = ROOT / 'release' / 'Cloudy_Clip_Studio_Source.zip'
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(ROOT / f, f'{TOP}/{f}')
    print(f'{out}  ({out.stat().st_size / 1e6:.1f} MB, {len(files)} files, version {version})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
