from __future__ import annotations

"""Best-effort face/lip-motion guided crop. This is not biometric identification.

Version 3 (YuNet + fallback Haar): the crop can switch between people. Each second we pick the face whose
mouth moves most while Whisper hears speech; a switch needs a clear advantage and
a minimum hold time, so the frame does not jitter between faces.
"""
import sys
from pathlib import Path
from typing import Any

YUNET_FILE = 'face_detection_yunet_2023mar.onnx'


def _yunet_path() -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    return base / 'assets' / 'models' / YUNET_FILE


def _make_detector(cv2, width: int, height: int, scale: float):
    """YuNet (neural, sees profiles and dim faces, gives mouth corners); Haar as a fallback.

    Returns (name, detect(bgr_small) -> list of (x, y, w, h, mouth_rect, eyes_rect) in small-image pixels).
    """
    sw, sh = max(1, int(width * scale)), max(1, int(height * scale))
    model = _yunet_path()
    if model.exists() and hasattr(cv2, 'FaceDetectorYN'):
        try:
            det = cv2.FaceDetectorYN.create(str(model), '', (sw, sh), 0.75, 0.3, 50)

            def detect_yunet(img):
                _, faces = det.detect(img)
                out = []
                for f in (faces if faces is not None else []):
                    x, y, w, h = (float(v) for v in f[:4])
                    if h < sh * 0.06: continue  # tiny background faces
                    rex, rey, lex, ley, _, _, rmx, rmy, lmx, lmy = (float(v) for v in f[4:14])
                    mw = max(4.0, abs(lmx - rmx)); mcx, mcy = (lmx + rmx) / 2, (lmy + rmy) / 2
                    mouth = (mcx - mw * .75, mcy - mw * .45, mw * 1.5, mw * .9)
                    ew = max(4.0, abs(lex - rex)); ecx, ecy = (lex + rex) / 2, (ley + rey) / 2
                    eyes = (ecx - ew * .8, ecy - ew * .3, ew * 1.6, ew * .6)
                    out.append((x, y, w, h, mouth, eyes))
                return out
            return 'YuNet', detect_yunet
        except Exception:
            pass
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    if cascade.empty():
        return None, None

    def detect_haar(img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        out = []
        for x, y, w, h in cascade.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=6,
                                                   minSize=(max(24, int(sh * 0.07)),) * 2):
            out.append((x, y, w, h, (x + w * .2, y + h * .62, w * .6, h * .33), (x + w * .15, y + h * .2, w * .7, h * .25)))
        return out
    return 'Haar', detect_haar


def analyze_active_speaker(path: str, clip_start: float, clip_end: float,
                           words: list[dict], sample_fps: float = 4.0, progress=None) -> dict[str, Any]:
    """Return crop-center keyframes [(t relative to clip start, x in source pixels)].

    Empty keyframes → the caller keeps the safe letterbox framing.
    """
    try:
        import cv2
        import numpy as np
    except Exception:
        return {'keyframes': [], 'enabled': False, 'reason': 'OpenCV недоступен'}

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return {'keyframes': [], 'enabled': False, 'reason': 'Не удалось открыть видео'}
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if not width or not height or width / height <= 9 / 16:
        cap.release()
        return {'keyframes': [], 'enabled': False, 'reason': 'Исходник уже вертикальный'}
    scale = min(1.0, 960 / width)
    detector_name, detect = _make_detector(cv2, width, height, scale)
    if detect is None:
        cap.release()
        return {'keyframes': [], 'enabled': False, 'reason': 'Не найдена модель лиц'}

    duration = max(0.1, clip_end - clip_start)
    crop_w = int(height * 9 / 16)
    speech = sorted((float(w['start']) - clip_start - .12, float(w['end']) - clip_start + .12)
                    for w in words if float(w['end']) > clip_start and float(w['start']) < clip_end)

    def speaking(t: float) -> bool:
        return any(a <= t <= b for a, b in speech)

    tracks: list[dict[str, Any]] = []  # {cx, cy, size, last_t, mouth, eyes, samples:[(t,cx,motion,speak)]}
    frame_step = max(1, int(round(fps / sample_fps)))
    frame_no = int(max(0.0, clip_start) * fps)
    end_frame = int(clip_end * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
    k = 0
    gap = 2  # compare mouth with the frame 2 frames later, inside the SAME face box
    while frame_no < end_frame:
        # Sequential grab() is much faster than seeking for every sample.
        if k % frame_step:
            if not cap.grab(): break
            frame_no += 1; k += 1
            continue
        ok, frame = cap.read()
        if not ok: break
        t = frame_no / fps - clip_start
        if progress: progress(max(0.0, min(1.0, t / duration)))
        frame_no += 1; k += 1
        later = None
        for _ in range(gap):
            ok2, f2 = cap.read()
            if not ok2: break
            later = f2; frame_no += 1; k += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(later, cv2.COLOR_BGR2GRAY) if later is not None else gray
        small = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale)))) if scale != 1.0 else frame
        used = set()

        def region(r):
            rx, ry, rw, rh = (v / scale for v in r)
            return (slice(max(0, int(ry)), max(0, int(ry + rh))), slice(max(0, int(rx)), max(0, int(rx + rw))))
        for fx, fy, fw, fh, mrect, erect in detect(small):
            x, y, w, h = (int(v / scale) for v in (fx, fy, fw, fh))
            cx, cy = x + w / 2, y + h / 2
            mr, er = region(mrect), region(erect)
            if gray[mr].size < 16 or gray[er].size < 16: continue
            # Same box in both frames: detector jitter cannot look like talking.
            # Blur first: sensor noise in dark footage must not look like talking.
            blur = lambda img: cv2.GaussianBlur(cv2.resize(img, (48, 24)), (5, 5), 0)
            m = float(np.mean(cv2.absdiff(blur(gray[mr]), blur(gray2[mr]))))
            e = float(np.mean(cv2.absdiff(blur(gray[er]), blur(gray2[er]))))
            motion = max(0.0, m - e)  # noise and nodding/turning change the eyes area too
            best, best_d = None, None
            for i, tr in enumerate(tracks):
                if i in used or t - tr['last_t'] > 2.5: continue
                d = ((tr['cx'] - cx) ** 2 + (tr['cy'] - cy) ** 2) ** .5
                if d < max(w, tr['size']) * 1.2 and (best_d is None or d < best_d):
                    best, best_d = i, d
            if best is None:
                tracks.append({'cx': cx, 'cy': cy, 'size': w, 'last_t': t, 'samples': []})
                best = len(tracks) - 1
            used.add(best)
            tr = tracks[best]
            tr['samples'].append((t, cx, motion, speaking(t)))
            tr.update(cx=cx, cy=cy, size=w, last_t=t)
    cap.release()

    tracks = [tr for tr in tracks if len(tr['samples']) >= 4]
    if not tracks:
        return {'keyframes': [], 'enabled': False, 'reason': 'Недостаточно уверенных кадров с лицами'}

    # Per-second decision with hysteresis.
    step, hold_min = 1.0, 2.0
    current, since, timeline = None, 0.0, []
    t = 0.0
    while t < duration:
        scores = {}
        for i, tr in enumerate(tracks):
            win = [s for s in tr['samples'] if t - 0.5 <= s[0] < t + step + 0.5]
            if not win: continue
            talk = [s[2] for s in win if s[3]]
            scores[i] = (sum(talk) / len(talk)) if talk else 0.0
        if scores:
            best = max(scores, key=scores.get)
            if current is None or current not in scores:
                current, since = best, t
            elif best != current and t - since >= hold_min and scores[best] > scores[current] * 1.6 + 0.02:
                current, since = best, t
        if current is not None:
            near = [s[1] for s in tracks[current]['samples'] if t - 1.0 <= s[0] <= t + step + 1.0]
            if near:
                timeline.append((t, current, float(np.median(near))))
        t += step
    if not timeline:
        return {'keyframes': [], 'enabled': False, 'reason': 'Не удалось уверенно определить говорящего'}

    talk_signal = [s[2] for tr in tracks for s in tr['samples'] if s[3]]
    if len(tracks) > 1 and (not talk_signal or float(np.max([np.mean([x[2] for x in tr['samples'] if x[3]] or [0]) for tr in tracks])) < 0.05):
        return {'keyframes': [], 'enabled': False, 'reason': 'Несколько лиц, но не удалось понять, кто говорит'}

    # Keyframes: hold steady on a person (dead zone), fast 0.35 s pan on a switch.
    dead = crop_w * 0.08
    keyframes = [(0.0, timeline[0][2])]
    last_track, last_x = timeline[0][1], timeline[0][2]
    switches = 0
    for t, tid, x in timeline[1:]:
        if tid != last_track:
            keyframes.append((t, last_x)); keyframes.append((t + 0.35, x))
            last_track, last_x = tid, x; switches += 1
        elif abs(x - last_x) > dead:
            keyframes.append((t, last_x)); keyframes.append((t + 0.8, x))
            last_x = x
    keyframes.append((duration, last_x))
    keyframes = sorted(dict(keyframes).items())[:160]
    return {'keyframes': keyframes, 'enabled': True,
            'reason': f'Кадр следует за говорящим (детектор {detector_name}, лиц: {len(tracks)}, переключений: {switches})',
            'track_count': len(tracks), 'switches': switches, 'crop_width': crop_w}
