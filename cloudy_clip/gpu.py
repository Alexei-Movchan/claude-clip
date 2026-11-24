"""Make the NVIDIA libraries installed by enable_gpu.bat visible to faster-whisper (CTranslate2).

pip puts cuBLAS / cuDNN DLLs into site-packages/nvidia/<lib>/bin. Windows does not
search there, so without this CTranslate2 fails with "cublas64_12.dll is not found"
and speech recognition silently falls back to the much slower CPU.
Must run BEFORE ctranslate2 / faster_whisper are imported.
"""
from __future__ import annotations
import glob, os, site, sys

_done: list[str] | None = None


def nvidia_dll_dirs() -> list[str]:
    roots = set()
    for p in list(sys.path) + (site.getsitepackages() if hasattr(site, 'getsitepackages') else []):
        if p and os.path.isdir(os.path.join(p, 'nvidia')): roots.add(p)
    dirs = []
    for r in sorted(roots):
        dirs += [d for d in glob.glob(os.path.join(r, 'nvidia', '*', 'bin')) if os.path.isdir(d)]
    return dirs


def add_nvidia_dll_dirs() -> list[str]:
    global _done
    if _done is not None: return _done
    _done = []
    if os.name != 'nt': return _done
    for d in nvidia_dll_dirs():
        try:
            os.add_dll_directory(d)   # for DLLs loaded by ctypes / Python extensions
        except OSError:
            continue
        _done.append(d)
    if _done:  # cuDNN loads its sub-libraries with plain LoadLibrary → needs PATH too
        os.environ['PATH'] = os.pathsep.join(_done + [os.environ.get('PATH', '')])
    return _done


def gpu_libs_installed() -> bool:
    dirs = nvidia_dll_dirs()
    has = lambda pattern: any(glob.glob(os.path.join(d, pattern)) for d in dirs)
    return has('cublas64_12.dll') and has('cudnn_ops64_9.dll')


def cuda_device_count() -> int:
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


if __name__ == '__main__':  # used by enable_gpu.bat:  python -m cloudy_clip.gpu
    add_nvidia_dll_dirs()
    n = cuda_device_count()
    libs = gpu_libs_installed()
    print(f'NVIDIA GPUs visible: {n}')
    print(f'cuBLAS/cuDNN libraries: {"OK" if libs else "MISSING"}')
    if n and libs:
        try:
            import ctranslate2
            types = ctranslate2.get_supported_compute_types('cuda')
            print('GPU compute types:', ', '.join(sorted(types)))
            print('RESULT: speech recognition will run on the GPU.')
        except Exception as e:
            print('RESULT: GPU check failed:', e)
    else:
        print('RESULT: speech recognition will run on the CPU.')
