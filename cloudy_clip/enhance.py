"""AI Enhance: Real-ESRGAN upscaling / clean-up and RIFE frame interpolation.

Engines are the official portable ncnn-Vulkan builds (no Python dependencies):
  * Real-ESRGAN ncnn Vulkan (xinntao, MIT; models BSD-3-Clause)
  * RIFE ncnn Vulkan (nihui, MIT; RIFE v4.6 model, MIT)
They are downloaded only when the user presses "Установить AI", into a separate folder
(%LOCALAPPDATA%\\CloudyClipStudio\\ai), and every file is checked against a pinned SHA-256.
Only the needed files are fetched from the official release archives (HTTP range requests),
so RIFE costs ~12 MB instead of the 431 MB archive.

The general-video models realesr-general-x4v3 / -wdn-x4v3 (official Real-ESRGAN weights,
BSD-3-Clause) were converted to ncnn for this app and ship in assets/ai_models.

Where it sits in the montage: the AI improves the piece of the SOURCE video that a clip uses,
before framing, subtitles, banner and music are added, so text and the ad stay crisp and only
the picture goes through the model. RIFE (optional) runs on the finished clip: 30 -> 60 fps.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zlib
from pathlib import Path
from typing import Callable

from .media import NO_WINDOW, Cancelled, ffmpeg_path, nvenc_available, probe

AI_PACK_VERSION = 1
PLATFORM = 'windows' if sys.platform.startswith('win') else 'ubuntu'
EXE = '.exe' if PLATFORM == 'windows' else ''

ESRGAN_URL = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-{p}.zip'
RIFE_URL = 'https://github.com/nihui/rife-ncnn-vulkan/releases/download/20221029/rife-ncnn-vulkan-20221029-{p}.zip'

# file inside the archive -> (path inside our component folder, sha256, size)
_FILES = {
    'esrgan': {
        'windows': {
            'realesrgan-ncnn-vulkan.exe': ('realesrgan-ncnn-vulkan.exe', '07e49f7cbb4ede01ae4dd4c399d3a7e5846e3d2085c3128eff881e55cb7b1a0c', 6161408),
            'vcomp140.dll': ('vcomp140.dll', '8f72ef2e483465444b2059fc6744d6cb22cd8d8a27f6fa56befd2a42dcd0f78b', 182704),
        },
        'ubuntu': {
            'realesrgan-ncnn-vulkan': ('realesrgan-ncnn-vulkan', '22c2296a39b40cc43ac92615c827ab6d4b60b7142e8cee59f718e3f8e2cdbda9', 11399776),
        },
        'common': {
            'models/realesr-animevideov3-x2.param': ('models/realesr-animevideov3-x2.param', 'b88ff4f00ebf019a7fdac17fdd45a7fd3665d37509efc5baf2e4da2e24420a04', 3173),
            'models/realesr-animevideov3-x2.bin': ('models/realesr-animevideov3-x2.bin', '548a36f9c3f4ab8da56cd3b13badf23968bee207b396dad14d04b830e5f2ab2d', 1247368),
            'models/realesrgan-x4plus.param': ('models/realesrgan-x4plus.param', '35330ececcea33b6c397a72548e788d5d53becee4734c50b7fada36e89f10a86', 116029),
            'models/realesrgan-x4plus.bin': ('models/realesrgan-x4plus.bin', '713ee713b0353afaa27976f0563a64a5043bd70b9bd8936c2e26e25ebcdbcddf', 33424520),
        },
    },
    'rife': {
        'windows': {
            'rife-ncnn-vulkan-20221029-windows/rife-ncnn-vulkan.exe': ('rife-ncnn-vulkan.exe', '4b970319db2814c82b15fceed8193151560a676a9eb63f20d4877be77b98f44f', 6974464),
            'rife-ncnn-vulkan-20221029-windows/vcomp140.dll': ('vcomp140.dll', '54fe6b087528b33c2969143d811eb62f1bd49071d37de9db0745fc079764d698', 181680),
            'rife-ncnn-vulkan-20221029-windows/LICENSE': ('LICENSE', 'de18cbedb0c3b0d1eeb9ccac3988cdf69c21fa89039cd97dd8846cb68f661f81', 1093),
            'rife-ncnn-vulkan-20221029-windows/rife-v4.6/flownet.param': ('rife-v4.6/flownet.param', '28df14d57a225725ee5386f52eba422488450d37c9f40800ed4f62e8ba846692', 16749),
            'rife-ncnn-vulkan-20221029-windows/rife-v4.6/flownet.bin': ('rife-v4.6/flownet.bin', 'f334ed2260149ce0188a6dcf049844e8b0cdd912e01cbcfb63553157d2508958', 10614320),
        },
        'ubuntu': {
            'rife-ncnn-vulkan-20221029-ubuntu/rife-ncnn-vulkan': ('rife-ncnn-vulkan', '5c256556195216ddfca103073b0fd37e33e154c8aa40666775fcae8d6a6580b4', 9892352),
            'rife-ncnn-vulkan-20221029-ubuntu/LICENSE': ('LICENSE', 'a73beab18143600af0b10c6050a953ec233775ce31c2bf3373a794db535329fd', 1072),
            'rife-ncnn-vulkan-20221029-ubuntu/rife-v4.6/flownet.param': ('rife-v4.6/flownet.param', '724569596bcd1e7b9fa50455c604777ebed99746d2ef40aa86e31b5725f1053c', 16532),
            'rife-ncnn-vulkan-20221029-ubuntu/rife-v4.6/flownet.bin': ('rife-v4.6/flownet.bin', 'f334ed2260149ce0188a6dcf049844e8b0cdd912e01cbcfb63553157d2508958', 10614320),
        },
        'common': {},
    },
}
COMPONENT_TITLES = {'esrgan': 'Real-ESRGAN (улучшение картинки)', 'rife': 'RIFE (плавность 60 кадров/с)'}
DOWNLOAD_MB = {'esrgan': 39, 'rife': 12}  # compressed bytes actually fetched, roughly

# quality mode -> (model name, scale). Balanced swaps to the weak-denoise model when denoise is off.
MODES = {
    'fast': ('realesr-animevideov3', 2),
    'balanced': ('realesr-general-x4v3', 4),
    'best': ('realesrgan-x4plus', 4),
}
MODE_TITLES = {'fast': 'Быстро', 'balanced': 'Баланс', 'best': 'Максимум'}
TARGETS = {'original': 0, '720p': 720, '1080p': 1080, '1440p': 1440}
BATCH = 120          # frames per AI call: bounds disk use and lets the user cancel quickly
SHARPEN = 'cas=strength=0.35'


def ai_dir() -> Path:
    base = os.environ.get('LOCALAPPDATA') if PLATFORM == 'windows' else os.path.join(Path.home(), '.local', 'share')
    return Path(base or Path.home()) / 'CloudyClipStudio' / 'ai'


def _bundled_models_dir() -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    return base / 'assets' / 'ai_models'


def _wanted(component: str) -> dict:
    files = dict(_FILES[component][PLATFORM]); files.update(_FILES[component]['common'])
    return files


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _manifest() -> dict:
    try:
        return json.loads((ai_dir() / 'manifest.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


def installed(component: str) -> bool:
    """Every file present with the right size (hashes were checked when they were written)."""
    root = ai_dir() / component
    if _manifest().get(component, {}).get('pack') != AI_PACK_VERSION: return False
    for dest, _sha, size in _wanted(component).values():
        p = root / dest
        if not p.is_file() or p.stat().st_size != size: return False
    if component == 'esrgan':
        for f in _bundled_models_dir().glob('*.bin'):
            if not (root / 'models' / f.name).is_file(): return False
    return True


def exe_path(component: str) -> Path:
    return ai_dir() / component / (('realesrgan-ncnn-vulkan' if component == 'esrgan' else 'rife-ncnn-vulkan') + EXE)


# --------------------------------------------------------------------------- download (only the needed files)

class _RemoteZip:
    """Reads single members of a zip on a web server with HTTP range requests."""

    def __init__(self, url: str, cancel: Callable[[], bool] | None = None):
        self.url, self.cancel = url, cancel or (lambda: False)
        self._range_abs(0, 0)                    # learn the archive size (suffix ranges are refused by GitHub)
        self.size = self._total
        tail_from = max(0, self.size - 65536)
        head = self._range_abs(tail_from, self.size - 1)
        i = head.rfind(b'PK\x05\x06')
        if i < 0: raise RuntimeError('Архив повреждён: не найден каталог файлов')
        _, _, _, _, count, cd_size, cd_off, _ = struct.unpack('<IHHHHIIH', head[i:i + 22])
        cd = self._range_abs(cd_off, cd_off + cd_size - 1)
        self.entries, p = {}, 0
        for _ in range(count):
            (sig, _v1, _v2, _fl, method, _t, _d, crc, csize, usize, nlen, xlen, clen, _dn, _ia, _ea, off) = \
                struct.unpack('<IHHHHHHIIIHHHHHII', cd[p:p + 46])
            if sig != 0x02014b50: raise RuntimeError('Архив повреждён')
            name = cd[p + 46:p + 46 + nlen].decode('utf-8', 'replace')
            self.entries[name] = (method, crc, csize, usize, off)
            p += 46 + nlen + xlen + clen

    def _open(self, rng: str):
        req = urllib.request.Request(self.url, headers={'User-Agent': 'CloudyClipStudio-AI', 'Range': rng})
        return urllib.request.urlopen(req, timeout=60)

    def _range_abs(self, a: int, b: int, progress: Callable[[int], None] | None = None) -> bytes:
        with self._open(f'bytes={a}-{b}') as r:
            if r.status != 206: raise RuntimeError('Сервер не поддерживает частичную загрузку')
            total = r.headers.get('Content-Range', '').rsplit('/', 1)[-1]
            if total.isdigit(): self._total = int(total)
            out = bytearray()
            while True:
                if self.cancel(): raise Cancelled()
                chunk = r.read(1 << 16)
                if not chunk: break
                out += chunk
                if progress: progress(len(chunk))
            return bytes(out)

    def read(self, name: str, progress: Callable[[int], None] | None = None) -> bytes:
        method, crc, csize, usize, off = self.entries[name]
        hdr = self._range_abs(off, off + 29)
        nlen, xlen = struct.unpack('<HH', hdr[26:30])
        start = off + 30 + nlen + xlen
        raw = self._range_abs(start, start + csize - 1, progress) if csize else b''
        data = zlib.decompress(raw, -15) if method == 8 else raw
        if len(data) != usize or (zlib.crc32(data) & 0xffffffff) != crc:
            raise RuntimeError(f'Файл {name} скачался с ошибкой')
        return data


class _LocalZip:
    """Fallback: the whole archive into a temp file, then the same read() interface."""

    def __init__(self, url: str, progress, cancel):
        import zipfile
        self._tmp = tempfile.NamedTemporaryFile(prefix='cloudy_ai_', suffix='.zip', delete=False)
        req = urllib.request.Request(url, headers={'User-Agent': 'CloudyClipStudio-AI'})
        with urllib.request.urlopen(req, timeout=60) as r, self._tmp as f:
            total = int(r.headers.get('Content-Length') or 0) or 1; got = 0
            while True:
                if cancel and cancel(): raise Cancelled()
                chunk = r.read(1 << 16)
                if not chunk: break
                f.write(chunk); got += len(chunk)
                progress(min(0.95, got / total), f'Загрузка архива {got / 1e6:.0f} из {total / 1e6:.0f} МБ')
        self._zip = zipfile.ZipFile(self._tmp.name)
        self.entries = {i.filename: (i.compress_type, i.CRC, i.compress_size, i.file_size, i.header_offset) for i in self._zip.infolist()}

    def read(self, name: str, progress=None) -> bytes:
        data = self._zip.read(name)
        if progress: progress(self.entries[name][2])
        return data

    def __del__(self):
        try:
            self._zip.close(); os.remove(self._tmp.name)
        except Exception:
            pass


def install(component: str, progress: Callable[[float, str], None] | None = None,
            cancel: Callable[[], bool] | None = None) -> None:
    """Download and verify one component. Safe to repeat: finished files are kept."""
    progress = progress or (lambda f, t: None)
    url = (ESRGAN_URL if component == 'esrgan' else RIFE_URL).format(p=PLATFORM)
    root = ai_dir() / component
    root.mkdir(parents=True, exist_ok=True)
    wanted = _wanted(component)
    todo = {}
    for member, (dest, sha, size) in wanted.items():
        p = root / dest
        if p.is_file() and p.stat().st_size == size and _sha256(p) == sha: continue
        todo[member] = (dest, sha, size)
    if todo:
        progress(0.0, 'Подключение к GitHub…')
        try:
            rz = _RemoteZip(url, cancel)
        except Cancelled:
            raise
        except Exception:
            try:
                rz = _LocalZip(url, progress, cancel)   # no partial download: fetch the whole archive once
            except Cancelled:
                raise
            except Exception as exc:
                raise RuntimeError(f'Не удалось скачать AI-модуль: {exc}. Проверьте интернет и попробуйте ещё раз.') from exc
        total = sum(rz.entries[m][2] for m in todo if m in rz.entries) or 1
        done = [0]

        def tick(n):
            done[0] += n
            progress(min(0.98, done[0] / total), f'Загрузка {done[0] / 1e6:.1f} из {total / 1e6:.1f} МБ')
        for member, (dest, sha, size) in todo.items():
            if member not in rz.entries: raise RuntimeError(f'В архиве нет файла {member}')
            data = rz.read(member, tick)
            if hashlib.sha256(data).hexdigest() != sha:
                raise RuntimeError(f'Файл {Path(dest).name} не прошёл проверку целостности. Попробуйте установить ещё раз.')
            p = root / dest; p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + '.part'); tmp.write_bytes(data); os.replace(tmp, p)
            if not EXE and p.name in ('realesrgan-ncnn-vulkan', 'rife-ncnn-vulkan'): p.chmod(0o755)
    if component == 'esrgan':   # general-video models bundled with the app
        for f in _bundled_models_dir().iterdir():
            if f.suffix in ('.param', '.bin'):
                dst = root / 'models' / f.name; dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.is_file() or _sha256(dst) != _sha256(f): shutil.copy2(f, dst)
    m = _manifest(); m[component] = {'pack': AI_PACK_VERSION, 'installed': time.strftime('%Y-%m-%d %H:%M')}
    (ai_dir() / 'manifest.json').write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding='utf-8')
    _DEVICES.pop(component, None)
    progress(1.0, 'Готово')


def remove(component: str) -> None:
    shutil.rmtree(ai_dir() / component, ignore_errors=True)
    m = _manifest(); m.pop(component, None)
    try: (ai_dir() / 'manifest.json').write_text(json.dumps(m), encoding='utf-8')
    except OSError: pass


# --------------------------------------------------------------------------- devices

_DEVICES: dict[str, list[tuple[int, str]]] = {}


def list_devices(component: str = 'esrgan') -> list[tuple[int, str]]:
    """Vulkan devices the engine sees, e.g. [(0, 'AMD Radeon 680M'), (1, 'NVIDIA GeForce RTX 4060 Laptop GPU')]."""
    if component in _DEVICES: return _DEVICES[component]
    devs: list[tuple[int, str]] = []
    if installed(component):
        with tempfile.TemporaryDirectory(prefix='cloudy_ai_') as td:
            src = os.path.join(td, 'a.png')
            subprocess.run([ffmpeg_path(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=gray:s=32x32', '-frames:v', '1', src],
                           capture_output=True, **NO_WINDOW)
            if component == 'esrgan':
                cmd = [str(exe_path('esrgan')), '-i', src, '-o', os.path.join(td, 'b.png'), '-n', 'realesr-animevideov3', '-s', '2',
                       '-m', str(ai_dir() / 'esrgan' / 'models')]
            else:
                cmd = [str(exe_path('rife')), '-0', src, '-1', src, '-o', os.path.join(td, 'b.png'), '-m', str(ai_dir() / 'rife' / 'rife-v4.6')]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(exe_path(component).parent), **NO_WINDOW)
                text = (p.stderr or '') + (p.stdout or '')
            except Exception as exc:
                text = str(exc)
            for m in re.finditer(r'^\[(\d+) (.+?)\]\s+queueC', text, re.M):
                devs.append((int(m.group(1)), m.group(2).strip()))
    _DEVICES[component] = devs
    return devs


def device_kind(name: str) -> str:
    n = name.lower()
    if 'llvmpipe' in n or 'swiftshader' in n or 'lavapipe' in n: return 'cpu'
    if any(k in n for k in ('nvidia', 'geforce', 'rtx', 'gtx', 'quadro')): return 'nvidia'
    return 'gpu'


def auto_device(component: str = 'esrgan') -> tuple[int, str] | None:
    """Best device: NVIDIA first, then any other GPU, software Vulkan (CPU) last."""
    devs = list_devices(component)
    if not devs: return None
    order = {'nvidia': 0, 'gpu': 1, 'cpu': 2}
    return sorted(devs, key=lambda d: (order[device_kind(d[1])], d[0]))[0]


def resolve_device(pref, component: str = 'esrgan') -> tuple[int, str] | None:
    devs = list_devices(component)
    if isinstance(pref, int):
        for d in devs:
            if d[0] == pref: return d
    return auto_device(component)


# --------------------------------------------------------------------------- helpers

def _fps(info: dict) -> float:
    try:
        a, b = str(info.get('fps') or '0/1').split('/') if '/' in str(info.get('fps')) else (info.get('fps'), 1)
        v = float(a) / float(b)
        return v if 5 <= v <= 120 else 30.0
    except Exception:
        return 30.0


def _hq_codec() -> list[str]:
    """Near-lossless intermediate: the montage re-encodes it once more."""
    if nvenc_available():
        return ['-c:v', 'h264_nvenc', '-preset', 'p5', '-rc', 'vbr', '-cq', '14', '-b:v', '0', '-pix_fmt', 'yuv420p']
    return ['-c:v', 'libx264', '-preset', 'fast', '-crf', '12', '-pix_fmt', 'yuv420p']


def _run_watch(cmd: list[str], cancel: Callable[[], bool], on_line: Callable[[str], None] | None = None,
               cwd: str | None = None) -> tuple[int, str]:
    """Run a tool, kill it at once on cancel, report output lines; returns (exit code, last output)."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', cwd=cwd, **NO_WINDOW)
    tail: list[str] = []

    def reader():
        for line in p.stdout:
            line = line.rstrip()
            tail.append(line); del tail[:-30]
            if on_line: on_line(line)
    th = threading.Thread(target=reader, daemon=True); th.start()
    while p.poll() is None:
        if cancel():
            p.kill(); p.wait(); th.join(2); raise Cancelled()
        time.sleep(0.15)
    th.join(5)
    return p.returncode, '\n'.join(tail)


def _ffmpeg(args: list[str]) -> None:
    p = subprocess.run([ffmpeg_path(), '-v', 'error', '-y', *args], capture_output=True, text=True, errors='replace', **NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError('Ошибка FFmpeg при AI-обработке:\n' + (p.stderr or '')[-1200:])


def model_for(opts: dict) -> tuple[str, int]:
    mode = opts.get('mode', 'balanced')
    name, scale = MODES.get(mode, MODES['balanced'])
    if mode == 'balanced' and not opts.get('denoise', True):
        name = 'realesr-general-wdn-x4v3'  # weak denoise: keeps film grain and fine texture
    return name, scale


def output_size(src_w: int, src_h: int, opts: dict) -> tuple[int, int]:
    """Size of the enhanced source. Never smaller than the original."""
    target = TARGETS.get(opts.get('resolution', '1080p'), 1080) or src_h
    h = min(max(src_h, target), src_h * 4)   # the model does up to its own scale, lanczos the rest
    w = int(round(src_w * h / src_h / 2)) * 2
    return w, int(h) // 2 * 2


class _Upscaler:
    """Runs Real-ESRGAN on a folder; on out-of-memory retries with smaller tiles, then a lighter model."""

    def __init__(self, opts: dict, cancel: Callable[[], bool]):
        if not installed('esrgan'): raise RuntimeError('AI-модуль не установлен. Откройте раздел «AI-улучшение» и нажмите «Установить AI».')
        self.cancel = cancel
        self.model, self.scale = model_for(opts)
        dev = resolve_device(opts.get('device'))
        if dev is None:
            raise RuntimeError('AI не нашёл видеокарту с поддержкой Vulkan. Обновите драйвер видеокарты '
                               'или выключите AI-улучшение — обычный монтаж работает без него.')
        self.device = dev
        self.tiles = [0, 256, 128, 64, 32]
        self.notes: list[str] = []

    def run(self, in_dir: str, out_dir: str, on_file: Callable[[], None]) -> None:
        while True:
            cmd = [str(exe_path('esrgan')), '-i', in_dir, '-o', out_dir, '-n', self.model, '-s', str(self.scale),
                   '-m', str(ai_dir() / 'esrgan' / 'models'), '-g', str(self.device[0]), '-t', str(self.tiles[0]),
                   '-f', 'jpg', '-v']
            code, tail = _run_watch(cmd, self.cancel, lambda l: on_file() if l.endswith(' done') else None,
                                    cwd=str(exe_path('esrgan').parent))
            made = {os.path.splitext(f)[0] for f in os.listdir(out_dir)}
            missing = [f for f in os.listdir(in_dir) if os.path.splitext(f)[0] not in made]
            if code == 0 and not missing: return
            # most failures here are video memory: smaller tiles, then a lighter model
            if len(self.tiles) > 1:
                self.tiles.pop(0); self.notes.append(f'мало видеопамяти: тайлы {self.tiles[0]}')
            elif self.model == 'realesrgan-x4plus':
                self.model, self.scale = 'realesr-general-x4v3', 4; self.tiles = [0, 128, 64, 32]
                self.notes.append('модель «Максимум» не поместилась, использована «Баланс»')
            else:
                raise RuntimeError('Real-ESRGAN завершился с ошибкой. Обновите драйвер видеокарты или выберите режим «Быстро».\n'
                                   + tail[-800:])
            for f in os.listdir(out_dir):
                os.remove(os.path.join(out_dir, f))


# --------------------------------------------------------------------------- source piece

def enhance_segment(source: str, start: float, duration: float, out_path: str, opts: dict,
                    keep: list[tuple[float, float]] | None = None,
                    progress: Callable[[float], None] | None = None,
                    cancel: Callable[[], bool] | None = None) -> dict:
    """AI-improved copy of source[start, start+duration] with the original sound.

    Only frames that stay in the clip (`keep`, seconds relative to start) go through the model;
    frames of cut pauses are just resized. Work is done in batches of BATCH frames so disk use stays
    small and cancel reacts within seconds.
    """
    progress = progress or (lambda f: None); cancel = cancel or (lambda: False)
    t0 = time.monotonic()
    info = probe(source); fps = _fps(info)
    src_w, src_h = info['width'], info['height']
    out_w, out_h = output_size(src_w, src_h, opts)
    up = _Upscaler(opts, cancel)
    total = max(1, int(round(duration * fps)))
    pad = 0.15

    def needs_ai(i: int) -> bool:
        if not keep: return True
        t = i / fps
        return any(a - pad <= t <= b + pad for a, b in keep)
    flags = [needs_ai(i) for i in range(total)]
    n_ai = sum(flags)
    weight = n_ai + 0.05 * (total - n_ai) or 1
    done = [0.0]
    vf_tail = f'scale={out_w}:{out_h}:flags=lanczos' + (f',{SHARPEN}' if opts.get('sharpen') else '') + ',format=yuv420p'
    with tempfile.TemporaryDirectory(prefix='cloudy_ai_') as td:
        segs = []
        for b0 in range(0, total, BATCH):
            if cancel(): raise Cancelled()
            n = min(BATCH, total - b0)
            src_dir = os.path.join(td, 'src'); ai_in = os.path.join(td, 'ai_in'); ai_out = os.path.join(td, 'ai_out')
            for d in (src_dir, ai_in, ai_out):
                shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
            # frames b0..b0+n-1 of the piece; seeking exactly to frame b0 keeps every batch on the same frame grid
            _ffmpeg(['-ss', f'{start + b0 / fps:.6f}', '-i', source, '-an', '-sn', '-vf', f'fps={fps:.6f}',
                     '-frames:v', str(n), '-q:v', '1', '-start_number', str(b0 + 1), os.path.join(src_dir, '%07d.jpg')])
            got = sorted(os.listdir(src_dir))
            while len(got) < n:   # end of file: repeat the last frame so the length stays exact
                last = got[-1] if got else None
                if last is None: raise RuntimeError('Не удалось прочитать кадры исходного видео для AI.')
                nxt = f'{b0 + len(got) + 1:07d}.jpg'; shutil.copy(os.path.join(src_dir, last), os.path.join(src_dir, nxt)); got.append(nxt)
            ai_names = [f'{b0 + k + 1:07d}.jpg' for k in range(n) if flags[b0 + k]]
            for name in ai_names:
                os.replace(os.path.join(src_dir, name), os.path.join(ai_in, name))
            if ai_names:
                def on_file():
                    done[0] += 1; progress(min(0.97, done[0] / weight))
                up.run(ai_in, ai_out, on_file)
            # encode runs of consecutive frames: AI frames from ai_out, the rest straight from the source frames
            k = 0
            while k < n:
                ai = flags[b0 + k]; j = k
                while j < n and flags[b0 + j] == ai: j += 1
                seg = os.path.join(td, f'seg_{len(segs):05d}.mp4')
                _ffmpeg(['-framerate', f'{fps:.6f}', '-start_number', str(b0 + k + 1), '-i', os.path.join(ai_out if ai else src_dir, '%07d.jpg'),
                         '-frames:v', str(j - k), '-vf', vf_tail, '-r', f'{fps:.6f}', *_hq_codec(), '-an', seg])
                segs.append(seg)
                if not ai:
                    done[0] += 0.05 * (j - k); progress(min(0.97, done[0] / weight))
                k = j
            for d in (src_dir, ai_in, ai_out): shutil.rmtree(d, ignore_errors=True)
        lst = os.path.join(td, 'list.txt')
        with open(lst, 'w', encoding='utf-8') as f:
            f.write(''.join(f"file '{s}'\n" for s in segs))
        tmp_out = out_path + '.part.mkv'
        _ffmpeg(['-f', 'concat', '-safe', '0', '-i', lst, '-ss', f'{start:.6f}', '-t', f'{total / fps:.6f}', '-i', source,
                 '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'pcm_s16le', '-t', f'{total / fps:.6f}', tmp_out])
        os.replace(tmp_out, out_path)
    progress(1.0)
    return {'model': up.model, 'mode': opts.get('mode', 'balanced'), 'device': up.device[1],
            'src_size': [src_w, src_h], 'out_size': [out_w, out_h], 'factor': out_w / max(1, src_w),
            'frames': total, 'frames_ai': n_ai, 'seconds': round(time.monotonic() - t0, 1), 'notes': up.notes}


def enhance_image(src_image: str, out_image: str, opts: dict, repeat: int = 4) -> dict:
    """One frame for the before/after comparison; also measures seconds per frame for an estimate."""
    info = probe(src_image)
    out_w, out_h = output_size(info['width'], info['height'], opts)
    up = _Upscaler(opts, lambda: False)
    with tempfile.TemporaryDirectory(prefix='cloudy_ai_') as td:
        def timed(count: int) -> float:
            i_dir, o_dir = os.path.join(td, f'i{count}'), os.path.join(td, f'o{count}')
            os.makedirs(i_dir); os.makedirs(o_dir)
            for k in range(count): shutil.copy(src_image, os.path.join(i_dir, f'{k:03d}.jpg' if src_image.lower().endswith('.jpg') else f'{k:03d}.png'))
            t = time.monotonic(); up.run(i_dir, o_dir, lambda: None); return time.monotonic() - t
        t1 = timed(1)
        tn = timed(1 + repeat) if repeat else t1
        per_frame = max(0.01, (tn - t1) / repeat) if repeat else t1
        first = sorted(os.listdir(os.path.join(td, 'o1')))[0]
        vf = f'scale={out_w}:{out_h}:flags=lanczos' + (f',{SHARPEN}' if opts.get('sharpen') else '')
        _ffmpeg(['-i', os.path.join(td, 'o1', first), '-vf', vf, '-frames:v', '1', out_image])
    return {'per_frame': per_frame, 'src_size': [info['width'], info['height']], 'out_size': [out_w, out_h],
            'model': up.model, 'device': up.device[1], 'notes': up.notes}


# --------------------------------------------------------------------------- RIFE: 30 -> 60 fps on the finished clip

def _scene_cuts(path: str, fps: float) -> set[int]:
    """Frame numbers that start a new shot: no in-between frame is invented across a cut."""
    p = subprocess.run([ffmpeg_path(), '-v', 'error', '-i', path, '-an', '-vf', 'scdet=threshold=12,metadata=print:key=lavfi.scd.time:file=-',
                        '-f', 'null', '-'], capture_output=True, text=True, errors='replace', **NO_WINDOW)
    cuts = set()
    for m in re.finditer(r'pts_time:([\d.]+)', p.stdout or ''):
        cuts.add(int(round(float(m.group(1)) * fps)))
    return cuts


def interpolate_video(path: str, out_path: str, opts: dict, progress: Callable[[float], None] | None = None,
                      cancel: Callable[[], bool] | None = None) -> dict:
    """Doubles the frame rate with RIFE v4.6. Sound is copied untouched, duration stays the same."""
    progress = progress or (lambda f: None); cancel = cancel or (lambda: False)
    if not installed('rife'): raise RuntimeError('Модуль плавности (RIFE) не установлен. Установите его в разделе «AI-улучшение».')
    dev = resolve_device(opts.get('device'), 'rife')
    if dev is None: raise RuntimeError('RIFE не нашёл видеокарту с поддержкой Vulkan.')
    t0 = time.monotonic()
    info = probe(path); fps = _fps(info)
    total = max(2, int(round(info['duration'] * fps)))
    cuts = _scene_cuts(path, fps)
    from .media import _vcodec
    vargs, _gpu = _vcodec(18)
    with tempfile.TemporaryDirectory(prefix='cloudy_rife_') as td:
        segs = []; done = 0
        for b0 in range(0, total, BATCH):
            if cancel(): raise Cancelled()
            n = min(BATCH, total - b0)
            last = b0 + n >= total
            take = n if last else n + 1       # one frame of overlap so the joint gets its in-between frame
            i_dir, o_dir = os.path.join(td, 'i'), os.path.join(td, 'o')
            for d in (i_dir, o_dir): shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
            _ffmpeg(['-ss', f'{b0 / fps:.6f}', '-i', path, '-an', '-vf', f'fps={fps:.6f}', '-frames:v', str(take), '-q:v', '1',
                     os.path.join(i_dir, '%08d.jpg')])
            got = sorted(os.listdir(i_dir))
            while len(got) < take:
                nxt = f'{len(got) + 1:08d}.jpg'; shutil.copy(os.path.join(i_dir, got[-1]), os.path.join(i_dir, nxt)); got.append(nxt)
            cmd = [str(exe_path('rife')), '-i', i_dir, '-o', o_dir, '-m', str(ai_dir() / 'rife' / 'rife-v4.6'),
                   '-g', str(dev[0]), '-n', str(2 * take), '-f', '%08d.jpg']
            code, tail = _run_watch(cmd, cancel, cwd=str(exe_path('rife').parent))
            outs = sorted(os.listdir(o_dir))
            if code != 0 or len(outs) < 2 * n:
                raise RuntimeError('RIFE завершился с ошибкой. Обновите драйвер видеокарты или выключите плавность.\n' + tail[-800:])
            for k in range(n):   # across a cut: repeat the previous frame instead of a blend of two shots
                if b0 + k + 1 in cuts:
                    shutil.copy(os.path.join(o_dir, outs[2 * k]), os.path.join(o_dir, outs[2 * k + 1]))
            seg = os.path.join(td, f'seg_{len(segs):05d}.mp4')
            _ffmpeg(['-framerate', f'{2 * fps:.6f}', '-i', os.path.join(o_dir, '%08d.jpg'), '-frames:v', str(2 * n),
                     '-vf', 'format=yuv420p', '-r', f'{2 * fps:.6f}', *vargs, '-an', seg])
            segs.append(seg); done += n; progress(min(0.98, done / total))
            for d in (i_dir, o_dir): shutil.rmtree(d, ignore_errors=True)
        lst = os.path.join(td, 'list.txt')
        with open(lst, 'w', encoding='utf-8') as f: f.write(''.join(f"file '{s}'\n" for s in segs))
        tmp = out_path + '.part.mp4'
        _ffmpeg(['-f', 'concat', '-safe', '0', '-i', lst, '-i', path, '-map', '0:v:0', '-map', '1:a:0?', '-c', 'copy',
                 '-t', f'{info["duration"]:.6f}', '-movflags', '+faststart', tmp])
        os.replace(tmp, out_path)
    progress(1.0)
    return {'fps': round(2 * fps, 3), 'device': dev[1], 'seconds': round(time.monotonic() - t0, 1), 'cuts': len(cuts)}
