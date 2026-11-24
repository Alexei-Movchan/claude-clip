from __future__ import annotations
import json, os, re, subprocess, tempfile, urllib.request, urllib.error
from pathlib import Path
from typing import Any, Callable

# Every intermediate and final file uses the same output format. Mixing frame
# rates / sample rates / channel layouts between pieces is what broke the old
# concat (ad frames were squeezed into a single timestamp).
FPS = 30
SAMPLE_RATE = 48000
OUT_W, OUT_H = 1080, 1920
# Started without a console (pythonw) every ffmpeg call would flash a black window.
NO_WINDOW = {'creationflags': 0x08000000} if os.name == 'nt' else {}


def which(name: str) -> str | None:
    from shutil import which as _which
    return _which(name)


def run(cmd: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE if capture else None,
                              stderr=subprocess.PIPE if capture else None, encoding='utf-8', errors='replace', **NO_WINDOW)
    except subprocess.CalledProcessError as e:
        tail = (e.stderr or '')[-1500:]
        raise RuntimeError(f'Ошибка FFmpeg (код {e.returncode}):\n{tail}') from e


def probe(path: str) -> dict[str, Any]:
    ffprobe = which('ffprobe')
    if not ffprobe:
        raise RuntimeError('Не найден ffprobe. Установите FFmpeg и добавьте его в PATH.')
    p = run([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path])
    data = json.loads(p.stdout)
    video = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), {})
    audio = next((s for s in data.get('streams', []) if s.get('codec_type') == 'audio'), {})
    duration = float(data.get('format', {}).get('duration', 0) or 0) or float(video.get('duration', 0) or 0)
    return {
        'duration': duration,
        'width': int(video.get('width', 0) or 0), 'height': int(video.get('height', 0) or 0),
        'fps': video.get('avg_frame_rate', '0/1'), 'has_audio': bool(audio),
        'video_codec': video.get('codec_name'), 'audio_codec': audio.get('codec_name')
    }


def ffmpeg_available() -> bool:
    return bool(which('ffmpeg') and which('ffprobe'))


def ffmpeg_path() -> str:
    p = which('ffmpeg')
    if not p:
        raise RuntimeError('Не найден ffmpeg. Установите FFmpeg и добавьте его в PATH.')
    return p


def safe_name(s: str) -> str:
    s = re.sub(r'[^\w\- ]+', '', s, flags=re.UNICODE).strip()
    return re.sub(r'\s+', '_', s)[:55] or 'clip'


def _snap(t: float) -> float:
    """Round a time to the output frame grid."""
    return round(float(t) * FPS) / FPS


# --------------------------------------------------------------------------- subtitles

def seconds_to_ass(t: float) -> str:
    cs = max(0, int(round(t * 100)))
    h, rem = divmod(cs, 360000); m, rem = divmod(rem, 6000); sec, cent = divmod(rem, 100)
    return f'{h}:{m:02}:{sec:02}.{cent:02}'


def escape_ass(text: str) -> str:
    return text.replace('\\', r'\\').replace('{', r'\{').replace('}', r'\}').replace('\n', ' ')


# Colours are RGB hex as people know them; ASS wants &H00BBGGRR.
SUB_PRESETS: dict[str, dict] = {
    'Классика': {'font': 'Arial', 'size': 64, 'primary': 'FFFFFF', 'active': 'FFD700', 'outline': 4, 'shadow': 2,
                 'position': 'Низ', 'upper': False, 'max_words': 5},
    'Крупно': {'font': 'Arial Black', 'size': 82, 'primary': 'FFFFFF', 'active': 'FFD700', 'outline': 6, 'shadow': 0,
               'position': 'Нижняя треть', 'upper': True, 'max_words': 3},
    'Неон': {'font': 'Arial', 'size': 68, 'primary': 'FFFFFF', 'active': '39FF14', 'outline': 5, 'shadow': 3,
             'position': 'Низ', 'upper': False, 'max_words': 4},
    'Минимал': {'font': 'Segoe UI', 'size': 54, 'primary': 'FFFFFF', 'active': 'FFE066', 'outline': 2, 'shadow': 0,
                'position': 'Низ', 'upper': False, 'max_words': 6},
}
SUB_POSITIONS = {'Низ': (2, 270), 'Нижняя треть': (2, 520), 'Центр': (5, 0), 'Верх': (8, 300)}
ACTIVE_COLORS = {'Жёлтый': 'FFD700', 'Зелёный': '39FF14', 'Красный': 'FF3B30', 'Голубой': '00C8FF',
                 'Розовый': 'FF4FD8', 'Белый': 'FFFFFF'}


def _ass_color(rgb: str) -> str:
    rgb = (rgb or 'FFFFFF').strip('#').upper().rjust(6, 'F')[:6]
    return f'&H00{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}'


def subtitle_style(style: dict | None) -> dict:
    base = dict(SUB_PRESETS['Классика'])
    if style:
        preset = style.get('preset')
        if preset in SUB_PRESETS: base.update(SUB_PRESETS[preset])
        base.update({k: v for k, v in style.items() if v not in (None, '') and k != 'preset'})
    return base


def _chunks(words: list[dict], max_words: int, max_gap: float = 0.35) -> list[list[dict]]:
    chunks, cur = [], []
    for w in words:
        if cur and float(w['start']) - float(cur[-1]['end']) > max_gap:
            chunks.append(cur); cur = []
        cur.append(w)
        if len(cur) >= max_words or w.get('word', '').strip().endswith(('.', '!', '?', ',', ':', ';', '…')):
            chunks.append(cur); cur = []
    if cur: chunks.append(cur)
    return chunks


def write_ass(path: str, words: list[dict], total: float, style: dict | None = None) -> None:
    """Captions on the FINAL timeline. The word being spoken right now is highlighted.

    `words` must already be mapped to the final clip timeline (after pause removal,
    hook and ad insertion), so captions never drift and never show during ad breaks.
    """
    st = subtitle_style(style)
    align, margin_v = SUB_POSITIONS.get(st['position'], SUB_POSITIONS['Низ'])
    primary, active = _ass_color(st['primary']), _ass_color(st['active'])
    header = (
        '[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n'
        '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, '
        'Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
        f"Style: Default,{st['font']},{int(st['size'])},{primary},{active},&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,"
        f"{int(st['outline'])},{int(st['shadow'])},{align},90,90,{margin_v},1\n\n"
        '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')
    selected = sorted((w for w in words if w['end'] > 0 and w['start'] < total), key=lambda w: w['start'])
    chunks = _chunks(selected, int(st.get('max_words') or 5))
    lines = [header]
    for ci, chunk in enumerate(chunks):
        tokens = []
        for w in chunk:
            t = w.get('word', '').strip()
            tokens.append(escape_ass(t.upper() if st.get('upper') else t))
        chunk_end = min(total, float(chunk[-1]['end']) + 0.15)
        if ci + 1 < len(chunks):
            chunk_end = min(chunk_end, float(chunks[ci + 1][0]['start']))
        for i, w in enumerate(chunk):
            a = max(0.0, float(w['start']))
            b = float(chunk[i + 1]['start']) if i + 1 < len(chunk) else chunk_end
            if b - a < 0.01: continue
            text = ' '.join(('{\\c' + active + '&}' + t + '{\\c' + primary + '&}') if j == i else t
                            for j, t in enumerate(tokens))
            lines.append(f'Dialogue: 0,{seconds_to_ass(a)},{seconds_to_ass(b)},Default,,0,0,0,,{text}\n')
    Path(path).write_text(''.join(lines), encoding='utf-8-sig')


def write_srt(path: str, words: list[dict], total: float) -> None:
    """Plain subtitles for uploading to TikTok/YouTube (same timeline as the video)."""
    def ts(t: float) -> str:
        ms = max(0, int(round(t * 1000)))
        h, rem = divmod(ms, 3600000); m, rem = divmod(rem, 60000); s, ms = divmod(rem, 1000)
        return f'{h:02}:{m:02}:{s:02},{ms:03}'
    selected = sorted((w for w in words if w['end'] > 0 and w['start'] < total), key=lambda w: w['start'])
    out = []
    for n, chunk in enumerate(_chunks(selected, 7, 0.6), 1):
        out.append(f"{n}\n{ts(chunk[0]['start'])} --> {ts(min(total, chunk[-1]['end'] + 0.1))}\n"
                   f"{' '.join(w['word'].strip() for w in chunk)}\n")
    Path(path).write_text('\n'.join(out), encoding='utf-8')


def _ffmpeg_filter_path(path: str) -> str:
    return path.replace('\\', '/').replace(':', '\\:').replace("'", "\\'")


# --------------------------------------------------------------------------- speech recognition

def transcribe(path: str, model_size: str = 'small', device: str = 'auto', progress_callback=None,
               notice_callback: Callable[[str], None] | None = None) -> tuple[list[dict], str]:
    from .gpu import add_nvidia_dll_dirs, gpu_libs_installed, cuda_device_count
    add_nvidia_dll_dirs()
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError('Не установлен faster-whisper. Выполните install.bat или pip install -r requirements.txt') from e
    notice = notice_callback or (lambda m: None)

    def _run(dev: str):
        if dev == 'cuda':
            # float16 + batched decoding: several 30-second chunks per GPU pass.
            model = WhisperModel(model_size, device='cuda', compute_type='float16')
            beam, batch = 5, 8
        else:
            threads = max(4, (os.cpu_count() or 8) // 2)  # ≈ physical cores; default is only 4
            model = WhisperModel(model_size, device='cpu', compute_type='int8', cpu_threads=threads)
            beam, batch = 2, 4
        kwargs = dict(language='ru', word_timestamps=True, vad_filter=True, beam_size=beam,
                      vad_parameters={'min_silence_duration_ms': 500})
        try:
            from faster_whisper import BatchedInferencePipeline
            segments, info = BatchedInferencePipeline(model=model).transcribe(path, batch_size=batch, **kwargs)
        except (ImportError, TypeError):
            segments, info = model.transcribe(path, **kwargs)
        words, full = [], []
        total_duration = max(0.1, float(getattr(info, 'duration', 0) or 0))
        # The generator is lazy: CUDA library errors surface here, not at model creation.
        for seg in segments:
            full.append(seg.text.strip())
            if progress_callback:
                progress_callback(min(100, int(float(seg.end) / total_duration * 100)))
            if seg.words:
                for w in seg.words:
                    words.append({'start': float(w.start), 'end': float(w.end), 'word': w.word})
            else:
                words.append({'start': float(seg.start), 'end': float(seg.end), 'word': seg.text})
        words.sort(key=lambda w: w['start'])  # batched mode may yield chunks slightly out of order
        return words, ' '.join(full)

    want_gpu = device in ('auto', 'cuda') and cuda_device_count() > 0
    if want_gpu:
        notice('Распознавание на видеокарте NVIDIA')
        try:
            return _run('cuda')
        except Exception as exc:
            hint = '' if gpu_libs_installed() else ' Запустите enable_gpu.bat, чтобы включить видеокарту.'
            notice(f'Видеокарта не сработала ({str(exc)[:100]}). Распознаю на процессоре — это медленнее.{hint}')
            if progress_callback: progress_callback(0)
    elif device == 'cuda':
        notice('Видеокарта NVIDIA не найдена. Распознаю на процессоре.')
    else:
        notice('Распознавание на процессоре')
    return _run('cpu')


# --------------------------------------------------------------------------- sentences & clip selection

_SENT_END = ('.', '!', '?', '…')


def build_sentences(words: list[dict], max_pause: float = 0.8, max_words: int = 40) -> list[dict]:
    """Group Whisper words into phrases: punctuation, a pause, or a length limit ends a phrase."""
    sents, cur = [], []

    def flush():
        if cur:
            sents.append({'start': float(words[cur[0]]['start']), 'end': float(words[cur[-1]]['end']),
                          'text': ' '.join(words[i]['word'].strip() for i in cur), 'i0': cur[0], 'i1': cur[-1]})
            cur.clear()

    for i, w in enumerate(words):
        if cur and float(w['start']) - float(words[i - 1]['end']) > max_pause:
            flush()
        cur.append(i)
        if w['word'].strip().endswith(_SENT_END) or len(cur) >= max_words:
            flush()
    flush()
    for k, s in enumerate(sents): s['id'] = k
    return sents


def fit_to_sentences(sents: list[dict], s: int, e: int, tmin: float, tmax: float) -> tuple[int, int] | None:
    """Move clip borders by whole phrases until the duration fits [tmin, tmax]."""
    s = max(0, min(s, len(sents) - 1)); e = max(s, min(e, len(sents) - 1))
    dur = lambda: sents[e]['end'] - sents[s]['start']
    while dur() < tmin:
        if e + 1 < len(sents): e += 1
        elif s > 0: s -= 1
        else: return None
    while dur() > tmax and e > s:
        e -= 1
    if not (tmin <= dur() <= tmax):
        return None
    return s, e


def _candidate_score(text: str) -> float:
    t = text.lower()
    score = min(len(text) / 650, 1.0) * 25
    for token, weight in [('представляешь', 5), ('никогда', 4), ('оказалось', 5), ('в итоге', 4), ('секрет', 5), ('ошибка', 3),
                          ('смешно', 3), ('страшно', 3), ('неожиданно', 5), ('почему', 2), ('как', 1), ('деньги', 2), ('история', 2)]:
        if token in t: score += weight
    return min(100, score)


def _overlap_ratio(a: dict, b: dict) -> float:
    inter = max(0.0, min(a['end'], b['end']) - max(a['start'], b['start']))
    return inter / max(1.0, min(a['end'] - a['start'], b['end'] - b['start']))


def _dedupe(clips: list[dict], max_overlap: float) -> list[dict]:
    result = []
    for c in sorted(clips, key=lambda x: x.get('score', 0), reverse=True):
        if all(_overlap_ratio(c, r) < max_overlap for r in result):
            result.append(c)
    return sorted(result, key=lambda x: x['start'])


def fallback_clips(words: list[dict], target_min: float = 90, target_max: float = 150,
                   taken: list[tuple[float, float]] | None = None) -> list[dict]:
    """Offline selection packed as tightly as possible.

    Candidate windows start and end on phrase borders; then weighted interval scheduling picks
    the largest number of non-overlapping windows (text score breaks ties). `taken` = time
    ranges already used by AI-picked clips, which candidates must not overlap.
    """
    import bisect
    sents = build_sentences(words)
    if not sents: return []
    taken = taken or []
    goals = sorted({target_min + 8, (target_min + target_max) / 2})
    candidates, seen = [], set()
    for i, s in enumerate(sents):
        natural = i == 0 or s['start'] - sents[i - 1]['end'] > 0.6 or sents[i - 1]['text'].endswith(_SENT_END)
        if not natural: continue
        for goal in goals:
            j = i
            while j + 1 < len(sents) and sents[j + 1]['end'] - s['start'] <= goal: j += 1
            fit = fit_to_sentences(sents, i, j, target_min, target_max)
            if not fit or fit in seen: continue
            seen.add(fit); a, b = fit
            st, en = sents[a]['start'], sents[b]['end']
            if any(min(en, y) - max(st, x) > 0.5 for x, y in taken): continue
            text = ' '.join(x['text'] for x in sents[a:b + 1])
            score = _candidate_score(text) + (5 if sents[b]['text'].endswith(_SENT_END) else 0)
            candidates.append({'start': st, 'end': en, 'title': '', 'hook': '', 'score': round(min(100, score), 1),
                               'reason': 'Автоматический подбор по фразам, паузам и текстовым сигналам', 'transcript': text})
    if not candidates: return []
    candidates.sort(key=lambda c: c['end'])
    ends = [c['end'] for c in candidates]
    best = [(0.0, [])]  # best[k] = (weight, chosen indices) using the first k candidates
    for k, c in enumerate(candidates):
        p = bisect.bisect_right(ends, c['start'] + 0.05, 0, k)   # candidates that end before this one starts
        take = (best[p][0] + 1000 + c['score'], best[p][1] + [k])  # count first, then text score
        best.append(take if take[0] > best[k][0] else best[k])
    result = [candidates[k] for k in best[-1][1]]
    for n, c in enumerate(result, 1): c['title'] = f'Нарезка {n}'
    return result


def _strip_model_output(raw: str) -> str:
    raw = re.sub(r'<think>.*?</think>', '', raw or '', flags=re.S).strip()
    raw = re.sub(r'^```(?:json)?|```$', '', raw, flags=re.M).strip()
    return raw


def _salvage_objects(text: str, key: str = 'start_id') -> list[dict]:
    """Pull every complete {...} object containing `key` out of a cut-off JSON answer."""
    dec = json.JSONDecoder(); out, i = [], 0
    while True:
        j = text.find('{', i)
        if j < 0: break
        try:
            obj, end = dec.raw_decode(text, j)
            if isinstance(obj, dict) and key in obj:
                out.append(obj); i = end; continue
        except ValueError:
            pass
        i = j + 1
    return out


def _extract_clip_list(parsed: Any) -> list:
    """Models answer with {"clips": [...]}, {"fragments": [...]}, a bare list, or a single object."""
    if isinstance(parsed, list): return parsed
    if isinstance(parsed, dict):
        if 'start_id' in parsed or 'start' in parsed: return [parsed]
        for v in parsed.values():
            if isinstance(v, list): return v
    return []


class Cancelled(RuntimeError):
    pass


def _json_complete(text: str) -> bool:
    t = _strip_model_output(text)
    if not t or t[-1] not in '}]': return False
    try:
        json.loads(t); return True
    except ValueError:
        return False


def _ollama_chat(base_url: str, model: str, prompt: str, num_ctx: int = 16384, max_tokens: int = 3000,
                 max_seconds: float = 300.0, on_tokens: Callable[[int], None] | None = None,
                 cancel: Callable[[], bool] | None = None) -> str:
    """Call only a loopback Ollama endpoint; no transcript leaves this PC.

    Streams the answer so that it can be watched, cancelled and cut short: in JSON mode
    small models sometimes finish the JSON and then keep emitting whitespace forever.
    """
    from urllib.parse import urlparse
    import time as _time
    parsed = urlparse(base_url)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise RuntimeError('Разрешён только локальный Ollama: http://127.0.0.1:11434')
    payload = json.dumps({'model': model, 'stream': True, 'format': 'json', 'think': False,
        'options': {'temperature': 0.2, 'num_ctx': num_ctx, 'num_predict': max_tokens},
        'messages': [
            {'role': 'system', 'content': 'Ты редактор коротких видео. Анализируй только данную расшифровку. Не выдумывай цитаты и события. Отвечай только JSON.'},
            {'role': 'user', 'content': prompt}
        ]}).encode('utf-8')
    req = urllib.request.Request(base_url.rstrip('/') + '/api/chat', data=payload,
        headers={'Content-Type': 'application/json'}, method='POST')
    parts: list[str] = []
    started = _time.monotonic(); count = 0
    try:
        # timeout = max wait for the NEXT piece (the first one includes loading the model)
        with urllib.request.urlopen(req, timeout=180) as response:
            for line in response:
                if cancel and cancel(): raise Cancelled('Остановлено пользователем')
                line = line.strip()
                if not line: continue
                data = json.loads(line.decode('utf-8'))
                if data.get('error'): raise RuntimeError(f"Ollama: {data['error']}")
                piece = data.get('message', {}).get('content', '')
                if piece:
                    parts.append(piece); count += 1
                    if on_tokens and count % 25 == 0: on_tokens(count)
                    if ('}' in piece or ']' in piece) and _json_complete(''.join(parts)):
                        break  # the answer is complete — do not wait for trailing whitespace
                if data.get('done'): break
                if _time.monotonic() - started > max_seconds:
                    if _json_complete(''.join(parts)): break
                    limit = f'{int(max_seconds // 60)} мин' if max_seconds >= 60 else f'{int(max_seconds)} с'
                    raise RuntimeError(f'модель отвечала дольше {limit}')
    except urllib.error.URLError as exc:
        raise RuntimeError('Ollama не запущен. Установите Ollama и выполните: ollama pull qwen3:4b') from exc
    except TimeoutError as exc:
        raise RuntimeError('Ollama не отвечает') from exc
    return ''.join(parts)


def _sentence_chunks(sents: list[dict], max_tokens: int, overlap_seconds: float) -> list[list[dict]]:
    """Split phrases so each request fits the model context (≈2.6 chars per token for Russian)."""
    chunks, i = [], 0
    while i < len(sents):
        tokens, j = 0, i
        while j < len(sents) and (j == i or tokens + (len(sents[j]['text']) + 20) / 2.6 <= max_tokens):
            tokens += (len(sents[j]['text']) + 20) / 2.6; j += 1
        chunks.append(sents[i:j])
        if j >= len(sents): break
        k = j
        while k - 1 > i and sents[j - 1]['end'] - sents[k - 1]['start'] < overlap_seconds: k -= 1
        i = max(i + 1, k)
    return chunks


def ai_select(words: list[dict], transcript: str, api_key: str = '', base_url: str = 'http://127.0.0.1:11434', model: str = 'qwen3:4b',
              target_min: int = 90, target_max: int = 150, use_local_ai: bool = True,
              notice_callback: Callable[[str], None] | None = None,
              cancel: Callable[[], bool] | None = None, fill: bool = True,
              debug_dir: str | None = None) -> list[dict]:
    """Local-first highlight selection; deterministic offline fallback if Ollama is unavailable.

    The model sees numbered phrases and answers with phrase numbers, not seconds,
    so it cannot invent timecodes, and every clip starts/ends on a phrase border.
    """
    if not words: return []
    if not use_local_ai:
        return fallback_clips(words, target_min, target_max)
    sents = build_sentences(words)
    errors, valid = [], []
    chunks = _sentence_chunks(sents, max_tokens=9000, overlap_seconds=target_max)
    for n, chunk in enumerate(chunks, 1):
        if notice_callback: notice_callback(f'Локальный AI: часть {n}/{len(chunks)}')
        lines = '\n'.join(f"{s['id']}. [{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in chunk)
        prompt = (
            'Ниже расшифровка видео, разбитая на пронумерованные фразы с таймкодами в секундах.\n'
            f'Выбери как можно больше (до 8) хороших самостоятельных фрагментов для TikTok/Shorts. Каждый фрагмент — непрерывный диапазон фраз '
            f'от start_id до end_id длительностью от {target_min} до {target_max} секунд (считай по таймкодам).\n'
            'Фрагмент должен начинаться с начала мысли и заканчиваться законченной мыслью, быть понятным без остального видео.\n'
            'Ищи законченные истории, юмор, эмоции, неожиданные повороты, сильные мысли и интригу. Фрагменты не должны пересекаться.\n'
            'Верни JSON: {"clips": [{"start_id": 0, "end_id": 0, "title": "короткое название", '
            '"hook": "дословная цепляющая фраза из фрагмента", "score": 1-100, "reason": "почему это интересно"}]}\n'
            'Пиши компактно, без отступов и переносов строк: title — до 8 слов, hook — до 12 слов, reason — до 10 слов.\n\n'
            'Фразы:\n' + lines)
        try:
            tokens_note = (lambda k, n=n: notice_callback(f'Локальный AI: часть {n}/{len(chunks)} · ответ модели: {k} токенов')) \
                if notice_callback else None
            raw = _strip_model_output(_ollama_chat(base_url, model, prompt, max_tokens=4000, on_tokens=tokens_note, cancel=cancel))
            if debug_dir:  # keep the raw answer: if the model misbehaves we can see what it wrote
                try: Path(debug_dir, f'ai_answer_part{n}.txt').write_text(raw, encoding='utf-8')
                except OSError: pass
            try:
                items = _extract_clip_list(json.loads(raw))
            except ValueError:
                items = _salvage_objects(raw)   # answer was cut off: keep every fully written clip
                if not items: raise
        except Cancelled:
            raise
        except Exception as exc:
            errors.append(str(exc)[:150])
            if isinstance(exc, RuntimeError) and 'Ollama не запущен' in str(exc): break
            continue
        lo, hi = chunk[0]['id'], chunk[-1]['id']
        for c in items:
            if not isinstance(c, dict): continue
            try:
                s_id, e_id = int(c.get('start_id')), int(c.get('end_id'))
            except (TypeError, ValueError):
                continue
            if not (lo <= s_id <= hi) or e_id < s_id: continue
            fit = fit_to_sentences(sents, s_id, min(e_id, len(sents) - 1), target_min, target_max)
            if not fit: continue
            a, b = fit
            try: score = max(1.0, min(100.0, float(c.get('score', 50))))
            except (TypeError, ValueError): score = 50.0
            valid.append({'start': sents[a]['start'], 'end': sents[b]['end'],
                          'title': str(c.get('title') or '').strip(), 'hook': str(c.get('hook') or '').strip(),
                          'score': score, 'reason': str(c.get('reason') or '').strip(),
                          'transcript': ' '.join(x['text'] for x in sents[a:b + 1])})
    unique = _dedupe(valid, 0.3)
    if unique:
        if fill:  # "as many as possible": add non-overlapping offline windows from the rest of the video
            extra = fallback_clips(words, target_min, target_max, taken=[(c['start'], c['end']) for c in unique])
            for c in extra:
                c['reason'] = 'Добор: ' + c['reason'][0].lower() + c['reason'][1:]; c['title'] = ''
            unique = sorted(unique + extra, key=lambda c: c['start'])
        return unique
    clips = fallback_clips(words, target_min, target_max)
    why = '; '.join(errors) if errors else 'модель не вернула подходящих фрагментов'
    for c in clips: c['reason'] = 'Офлайн-резерв (AI не сработал: ' + why[:150] + ')'
    return clips


def ai_metadata(transcript: str, base_url: str = 'http://127.0.0.1:11434', model: str = 'qwen3:4b') -> dict | None:
    """Title, short description, hashtags and a hook phrase for one clip (local Ollama)."""
    text = transcript.strip()
    if len(text) > 6000: text = text[:6000]
    prompt = ('Это расшифровка короткого вертикального видео для TikTok/Shorts/Reels.\n'
              'Придумай: title — цепляющее название до 60 символов, без кавычек и эмодзи; '
              'description — 1–2 предложения, интригующие, без спойлера концовки; '
              'hashtags — 5–8 хэштегов на русском по теме видео, без #cloudyvpn; '
              'hook — самая цепляющая фраза ДОСЛОВНО из расшифровки, 4–12 слов.\n'
              'Верни JSON: {"title": "...", "description": "...", "hashtags": ["#...", "#..."], "hook": "..."}\n\n'
              'Расшифровка:\n' + text)
    try:
        data = json.loads(_strip_model_output(_ollama_chat(base_url, model, prompt, num_ctx=8192, max_tokens=800,
                                                           max_seconds=120)))
    except Exception:
        return None
    if not isinstance(data, dict): return None
    tags = data.get('hashtags') or []
    if isinstance(tags, str): tags = tags.replace(',', ' ').split()
    tags = ['#' + re.sub(r'[^\w]', '', str(t).lstrip('#'), flags=re.UNICODE) for t in tags]
    tags = [t for t in tags if len(t) > 1 and t.lower() != '#cloudyvpn'][:8]
    return {'title': str(data.get('title') or '').strip().strip('"«»')[:80],
            'description': str(data.get('description') or '').strip(),
            'hashtags': tags, 'hook': str(data.get('hook') or '').strip().strip('"«»')}


# --------------------------------------------------------------------------- render helpers

def plan_keep_ranges(words: list[dict], clip_start: float, clip_end: float, keep_pause: float = 0.5,
                     cut_threshold: float = 1.2, min_duration: float = 90.0) -> list[tuple[float, float]]:
    """Ranges (relative to clip start) that stay after shortening long pauses.

    Each long gap keeps `keep_pause` seconds of air (half on each side) so word
    endings that Whisper times too early are not chopped off.
    """
    duration = max(0.0, clip_end - clip_start)
    local = sorted((max(0.0, float(w['start']) - clip_start), min(duration, float(w['end']) - clip_start))
                   for w in words if float(w['end']) > clip_start and float(w['start']) < clip_end)
    cuts = []
    for (_, prev_end), (next_start, _) in zip(local, local[1:]):
        if next_start - prev_end > cut_threshold:
            left, right = prev_end + keep_pause / 2, next_start - keep_pause / 2
            if right - left > 0.25: cuts.append((left, right))
    merged: list[tuple[float, float]] = []
    for a, b in cuts:
        if merged and a <= merged[-1][1]: merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else: merged.append((a, b))
    requested = sum(b - a for a, b in merged); allowed = max(0.0, duration - min_duration)
    if requested > allowed and requested > 0:
        ratio = allowed / requested
        merged = [((a + b) / 2 - (b - a) * ratio / 2, (a + b) / 2 + (b - a) * ratio / 2) for a, b in merged]
    keep, cursor = [], 0.0
    for a, b in merged:
        if a > cursor: keep.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < duration: keep.append((cursor, duration))
    snapped = []
    for a, b in keep:
        a, b = _snap(a), _snap(b)
        if b - a >= 2 / FPS: snapped.append((a, b))
    return snapped or [(0.0, _snap(duration))]


def make_mapper(keep: list[tuple[float, float]]):
    """Map a time relative to clip start onto the timeline after pause removal."""
    offsets, acc = [], 0.0
    for a, b in keep:
        offsets.append((a, b, acc)); acc += b - a

    def mapper(t: float) -> float:
        for a, b, o in offsets:
            if t < a: return o
            if t <= b: return o + (t - a)
        return acc
    return mapper, acc


def _crop_expression(keyframes: list[tuple[float, float]], crop_w: int, src_w: int) -> str:
    max_x = max(0, src_w - crop_w)
    pts = sorted((max(0.0, float(t)), max(0.0, min(float(x) - crop_w / 2, max_x))) for t, x in keyframes)
    expr = f'{pts[-1][1]:.1f}'
    for idx in range(len(pts) - 2, -1, -1):
        t0, x0 = pts[idx]; t1, x1 = pts[idx + 1]
        if t1 <= t0: continue
        part = f'{x0:.1f}' if abs(x1 - x0) < 0.5 else f'({x0:.1f}+({x1 - x0:.1f})*(t-{t0:.3f})/{t1 - t0:.3f})'
        expr = rf'if(lt(t\,{t1:.3f})\,{part}\,{expr})'
    return expr


# --------------------------------------------------------------------------- encoder (GPU NVENC with CPU fallback)

_ENC: dict[str, Any] = {'pref': 'auto', 'nvenc': None}


def set_encoder(pref: str) -> None:
    """'auto' — NVIDIA NVENC if it works, otherwise libx264; 'cpu' — always libx264."""
    _ENC['pref'] = 'cpu' if pref == 'cpu' else 'auto'


def nvenc_available() -> bool:
    if _ENC['nvenc'] is None:
        try:
            subprocess.run([ffmpeg_path(), '-v', 'error', '-f', 'lavfi', '-i', 'color=s=256x256:d=0.2',
                            '-c:v', 'h264_nvenc', '-f', 'null', '-'], check=True, capture_output=True, timeout=30, **NO_WINDOW)
            _ENC['nvenc'] = True
        except Exception:
            _ENC['nvenc'] = False
    return bool(_ENC['nvenc'])


def encoder_name() -> str:
    return 'NVENC (видеокарта)' if _ENC['pref'] != 'cpu' and nvenc_available() else 'x264 (процессор)'


def _vcodec(quality: int) -> tuple[list[str], bool]:
    if _ENC['pref'] != 'cpu' and nvenc_available():
        return ['-c:v', 'h264_nvenc', '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr', '-cq', str(quality),
                '-b:v', '0', '-pix_fmt', 'yuv420p'], True
    return ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(quality), '-pix_fmt', 'yuv420p'], False


def run_progress(cmd: list[str], duration: float, callback: Callable[[float], None] | None) -> None:
    """Run ffmpeg and report the share of the output already written (0..1)."""
    if not callback or duration <= 0:
        run(cmd); return
    cmd = cmd[:1] + ['-progress', 'pipe:1', '-nostats'] + cmd[1:]
    with tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='replace') as err:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True, encoding='utf-8', errors='replace', **NO_WINDOW)
        for line in p.stdout:
            if line.startswith('out_time_us='):
                try: callback(max(0.0, min(1.0, int(line.split('=')[1]) / 1e6 / duration)))
                except ValueError: pass
        p.wait()
        if p.returncode != 0:
            err.seek(0)
            raise RuntimeError(f'Ошибка FFmpeg (код {p.returncode}):\n{err.read()[-1500:]}')
    callback(1.0)


def _encode(head: list[str], tail: list[str], quality: int, duration: float = 0.0,
            progress: Callable[[float], None] | None = None) -> None:
    args, gpu = _vcodec(quality)
    try:
        run_progress(head + args + tail, duration, progress)
    except RuntimeError:
        if not gpu: raise
        _ENC['nvenc'] = False  # driver/VRAM problem: finish the job on the CPU
        run_progress(head + _vcodec(quality)[0] + tail, duration, progress)


# --------------------------------------------------------------------------- emphasis & hook

def _norm(word: str) -> str:
    return re.sub(r'[^\w]', '', word.lower().replace('ё', 'е'), flags=re.UNICODE)


def find_hook(hook: str, clip_words: list[dict]) -> tuple[int, int] | None:
    """Locate the model's hook phrase inside the clip words (tolerates small wording differences)."""
    target = [_norm(t) for t in (hook or '').split() if _norm(t)]
    if len(target) < 2 or not clip_words: return None
    norm = [_norm(w['word']) for w in clip_words]
    n = len(target); best, best_i = 0.0, None
    for i in range(0, max(1, len(norm) - n + 1)):
        window = norm[i:i + n]
        # Exact word = 1, same stem (Whisper vs model spelling of endings) = 0.6.
        score = sum(1.0 if a == b else (0.6 if len(a) > 4 and len(b) > 4 and a[:5] == b[:5] else 0.0)
                    for a, b in zip(window, target)) / n
        if score > best: best, best_i = score, i
    if best_i is None or best < 0.6: return None
    return best_i, min(len(clip_words) - 1, best_i + n - 1)


def word_loudness(source: str, start: float, duration: float, local_words: list[tuple[float, float]]) -> list[float]:
    """RMS loudness per word (dB), read straight from the source audio."""
    try:
        import numpy as np
        p = subprocess.run([ffmpeg_path(), '-v', 'error', '-ss', f'{start:.3f}', '-t', f'{duration:.3f}', '-i', source,
                            '-vn', '-ac', '1', '-ar', '8000', '-f', 's16le', '-'], capture_output=True, timeout=300, **NO_WINDOW)
        pcm = np.frombuffer(p.stdout, dtype=np.int16).astype('float32')
        if pcm.size == 0: return [0.0] * len(local_words)
        out = []
        for a, b in local_words:
            seg = pcm[max(0, int(a * 8000)):max(int(a * 8000) + 1, int(b * 8000))]
            out.append(float(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1)) if seg.size else 0.0)
        return out
    except Exception:
        return [0.0] * len(local_words)


def pick_punch_ins(local_words: list[tuple[float, float, str]], loudness: list[float], duration: float) -> list[float]:
    """Moments for a quick zoom-in: noticeably louder words and exclamations, spaced ≥ 8 s apart."""
    if not local_words: return []
    vals = [v for v in loudness if v > 0]
    mean = sum(vals) / len(vals) if vals else 0.0
    sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** .5 if vals else 0.0
    cands = []
    for (a, b, text), loud in zip(local_words, loudness):
        z = (loud - mean) / sd if sd > 0.5 and loud > 0 else 0.0
        score = z + (2.0 if text.strip().endswith('!') else 0) + (0.6 if text.strip().endswith('?') else 0)
        if score >= 1.8 and 2.0 < a < duration - 3.0: cands.append((score, a))
    chosen: list[float] = []
    for _, t in sorted(cands, reverse=True):
        if len(chosen) >= max(1, int(duration / 12)): break
        if all(abs(t - c) >= 8 for c in chosen): chosen.append(t)
    return sorted(chosen)


def _zoom_expression(punches: list[float], amount: float = 0.12) -> str:
    # Fast 0.2 s push-in, hold, 0.4 s release; ~1.8 s per punch.
    terms = [f'clip((it-{p:.3f})/0.2\\,0\\,1)*clip(({p + 1.8:.3f}-it)/0.4\\,0\\,1)' for p in punches]
    return f"1+{amount}*({'+'.join(terms)})"


# --------------------------------------------------------------------------- render

def _scaled_width(info: dict, zoom: float) -> int:
    """Width of the enlarged picture inside the 1080-wide frame (same formula as the scale filter)."""
    z = max(1.0, min(3.0, float(zoom)))
    s = min(OUT_W * z / max(1, info['width']), OUT_H / max(1, info['height']))
    return int(s * info['width'] / 2) * 2


def follow_expression(keyframes: list[tuple[float, float]], info: dict, zoom: float) -> str | None:
    """Gentle pan: x of the 1080-wide window over the enlarged picture, following the face center."""
    sw = _scaled_width(info, zoom)
    if sw <= OUT_W or not keyframes: return None
    k = sw / max(1, info['width'])
    return _crop_expression([(t, x * k) for t, x in keyframes], OUT_W, sw)


def _framing(head: str, info: dict, crop_x_expr: str | None, zoom: float, background: str,
             follow_x_expr: str | None = None) -> str:
    """Filter chain that turns the source picture into a 1080x1920 frame, ending in label [fr].

    crop_x_expr: speaker-tracking crop (x of the 9:16 window, may depend on t); None = fit with zoom.
    Shared by the real render and by the preview, so the preview shows exactly what you get.
    """
    if crop_x_expr is not None:
        crop_w = max(2, int(info['height'] * 9 / 16) // 2 * 2)
        return f"{head},crop={crop_w}:{info['height'] // 2 * 2}:'{crop_x_expr}':0,scale={OUT_W}:{OUT_H},setsar=1[fr]"
    # zoom > 1 enlarges a landscape picture: sides are cropped a little, the bars shrink.
    z = max(1.0, min(3.0, float(zoom)))
    x_part = f":'{follow_x_expr}':'(ih-oh)/2'" if follow_x_expr else ''
    fg = (f"scale=w='trunc(min({OUT_W * z:.1f}/iw\\,{OUT_H}/ih)*iw/2)*2':h=-2,"
          f"crop='min(iw\\,{OUT_W})':'min(ih\\,{OUT_H})'{x_part}")
    if background == 'blur':
        # Blurred, darkened copy of the same picture fills the bars (cheap: blurred at 1/4 size).
        return (f"{head},split=2[fgsrc][bgsrc];"
                f"[bgsrc]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
                f"gblur=sigma=10,eq=brightness=-0.12:saturation=1.1,scale={OUT_W}:{OUT_H},setsar=1[bg];"
                f"[fgsrc]{fg},setsar=1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[fr]")
    return f"{head},{fg},pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[fr]"


SAMPLE_CAPTION = ['Так', 'будут', 'выглядеть', 'субтитры', 'в', 'ролике.']


def render_preview_frame(source: str, t: float, out_png: str, words: list[dict] | None = None,
                         zoom: float = 1.3, background: str = 'blur', subtitle_style: dict | None = None,
                         crop_center_x: float | None = None, info: dict | None = None,
                         follow_center_x: float | None = None) -> str:
    """One finished-looking 1080x1920 frame at source time t (framing + background + captions).

    words: real transcript words (captions of that moment are shown, current word highlighted);
    without them a sample caption is drawn so the style can still be judged.
    """
    info = info or probe(source)
    t = max(0.0, min(float(t), max(0.0, info['duration'] - 0.05)))
    with tempfile.TemporaryDirectory(prefix='cloudy_prev_') as td:
        near = [w for w in (words or []) if float(w['end']) > t - 4 and float(w['start']) < t + 4]
        if near:
            # Put the moment t at 0: the caption chunk that is on screen at t is drawn on the frame.
            shifted = [{'start': float(w['start']) - t, 'end': float(w['end']) - t, 'word': w['word']} for w in near]
            on_screen = [w for w in shifted if w['start'] <= 0.05]
            if not on_screen or on_screen[-1]['end'] < -0.6:  # pause right now → show the next phrase
                nxt = [w for w in shifted if w['start'] > 0]
                if nxt:
                    d = nxt[0]['start'] - 0.01
                    shifted = [{**w, 'start': w['start'] - d, 'end': w['end'] - d} for w in shifted]
        else:
            shifted = [{'start': i * 0.3 - 0.4, 'end': i * 0.3 - 0.15, 'word': ' ' + w} for i, w in enumerate(SAMPLE_CAPTION)]
        ass = os.path.join(td, 'p.ass')
        write_ass(ass, shifted, 10.0, subtitle_style)
        expr = None
        if crop_center_x is not None and info['width'] / max(1, info['height']) > 9 / 16:
            crop_w = max(2, int(info['height'] * 9 / 16) // 2 * 2)
            expr = f'{max(0.0, min(float(crop_center_x) - crop_w / 2, info["width"] - crop_w)):.1f}'
        fexpr = follow_expression([(0.0, follow_center_x)], info, zoom) if follow_center_x is not None and expr is None else None
        graph = _framing('[0:v]setpts=PTS-STARTPTS', info, expr, zoom, background, fexpr)
        graph += f";[fr]ass='{_ffmpeg_filter_path(ass)}'[v]"
        run([ffmpeg_path(), '-y', '-ss', f'{t:.3f}', '-i', source, '-filter_complex', graph, '-map', '[v]',
             '-frames:v', '1', out_png])
    return out_png


def _render_base(source: str, out: str, clip_start: float, clip_dur: float, keep: list[tuple[float, float]],
                 crop_keyframes: list[tuple[float, float]] | None, info: dict, zoom: float = 1.0,
                 background: str = 'blur', punches: list[float] | None = None,
                 progress: Callable[[float], None] | None = None,
                 follow_keyframes: list[tuple[float, float]] | None = None) -> None:
    """One encode: cut the clip, drop long pauses, frame it as 9:16, normalise A/V format.

    Uses select/aselect on a single decoded stream (no split buffering). Audio is
    re-chunked into frame-sized packets so audio and video drop exactly the same
    time spans — lip sync cannot drift no matter how many pauses are removed.
    """
    lo, hi = 0.25 / FPS, 0.75 / FPS
    sel = '+'.join(f'between(t\\,{a - lo:.4f}\\,{b - hi:.4f})' for a, b in keep)
    head = f"[0:v]setpts=PTS-STARTPTS,fps={FPS},select='{sel}',setpts=N/{FPS}/TB"
    expr = None
    if crop_keyframes and info['width'] / max(1, info['height']) > 9 / 16:
        expr = _crop_expression(crop_keyframes, max(2, int(info['height'] * 9 / 16) // 2 * 2), info['width'])
    fexpr = follow_expression(follow_keyframes, info, zoom) if follow_keyframes and expr is None else None
    video = _framing(head, info, expr, zoom, background, fexpr)
    if punches:
        video += (f";[fr]zoompan=z='{_zoom_expression(punches)}':d=1:x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':"
                  f"s={OUT_W}x{OUT_H}:fps={FPS},format=yuv420p[v]")
    else:
        video += ';[fr]format=yuv420p[v]'
    audio = (f"[0:a]asetpts=PTS-STARTPTS,aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
             f"asetnsamples=n={SAMPLE_RATE // FPS}:p=0,aselect='{sel}',asetpts=N/SR/TB[a]")
    _encode([ffmpeg_path(), '-y', '-ss', f'{clip_start:.3f}', '-t', f'{clip_dur:.3f}', '-i', source,
             '-filter_complex', video + ';' + audio, '-map', '[v]', '-map', '[a]'],
            ['-r', str(FPS), '-c:a', 'aac', '-b:a', '256k', '-ar', str(SAMPLE_RATE), '-ac', '2', out], 16,
            sum(b - a for a, b in keep), progress)


def _ad_positions(base_dur: float, ad_dur: float, count: int, word_times: list[tuple[float, float]],
                  hook_len: float = 0.0) -> list[float]:
    """Ad break positions on the base timeline, moved into the nearest pause between words."""
    total = hook_len + base_dur + count * ad_dur
    out_targets = [total / 2 - ad_dur / 2] if count == 1 else [30.0, 90.0]
    targets = [t - hook_len - i * ad_dur for i, t in enumerate(out_targets)]
    gaps = [((a_end + b_start) / 2) for (_, a_end), (b_start, _) in zip(word_times, word_times[1:]) if b_start - a_end >= 0.12]
    result = []
    for target in targets:
        target = min(max(target, 10.0), base_dur - 5.0)
        near = [g for g in gaps if abs(g - target) <= 8 and 5 < g < base_dur - 3]
        pos = min(near, key=lambda g: abs(g - target)) if near else target
        pos = _snap(pos)
        if result and pos <= result[-1] + 1: pos = _snap(result[-1] + 1)
        result.append(min(pos, _snap(base_dur - 1 / FPS)))
    return result


def _assemble(base: str, banner: str, banner_info: dict, out: str, base_dur: float, positions: list[float],
              ad_dur: float, speed: float, ass_path: str, td: str, hook: tuple[float, float] | None = None,
              progress: Callable[[float], None] | None = None) -> dict:
    """Second (final) encode: [hook] + content pieces + frozen-frame ad breaks + captions, one concat."""
    bw, bh = max(1, banner_info['width']), max(1, banner_info['height'])
    scale = min(OUT_W / bw, (OUT_H * 0.9) / bh)
    sw, sh = max(2, int(bw * scale) // 2 * 2), max(2, int(bh * scale) // 2 * 2)
    args, graph, labels = [], [], []
    n_in = 0

    def add_input(*a):
        nonlocal n_in
        args.extend(a); n_in += 1
        return n_in - 1

    if hook:
        hs, hl = hook
        k = add_input('-ss', f'{hs:.4f}', '-t', f'{hl:.4f}', '-i', base)
        # Short fades so the jump from the hook to the real start does not click.
        graph.append(f'[{k}:v]setpts=PTS-STARTPTS,fps={FPS},fade=t=out:st={max(0.0, hl - 0.12):.3f}:d=0.12:color=white[hv];'
                     f'[{k}:a]asetpts=PTS-STARTPTS,afade=t=in:d=0.03,afade=t=out:st={max(0.0, hl - 0.08):.3f}:d=0.08[ha]')
        labels.append('[hv][ha]')
    cursor = 0.0
    for idx, pos in enumerate(positions + [base_dur]):
        if pos - cursor >= 1 / FPS:
            k = add_input('-ss', f'{cursor:.4f}', '-t', f'{pos - cursor:.4f}', '-i', base)
            graph.append(f'[{k}:v]setpts=PTS-STARTPTS,fps={FPS}[cv{idx}];[{k}:a]asetpts=PTS-STARTPTS[ca{idx}]')
            labels.append(f'[cv{idx}][ca{idx}]')
        cursor = pos
        if idx < len(positions):
            frame = os.path.join(td, f'freeze{idx}.png')
            run([ffmpeg_path(), '-y', '-ss', f'{min(pos, max(0.0, base_dur - 0.1)):.4f}', '-i', base, '-frames:v', '1', frame])
            f = add_input('-loop', '1', '-framerate', str(FPS), '-t', f'{ad_dur:.4f}', '-i', frame)
            b = add_input('-i', banner)
            graph.append(
                f'[{f}:v]scale={OUT_W}:{OUT_H},setsar=1,format=yuv420p[bg{idx}];'
                f'[{b}:v]setpts=(PTS-STARTPTS)/{speed:.4f},fps={FPS},chromakey=0x00ff00:0.20:0.06,'
                f'scale={sw}:{sh},format=yuva420p[kb{idx}];'
                f'[bg{idx}][kb{idx}]overlay=(W-w)/2:(H-h)/2:eof_action=pass,trim=duration={ad_dur:.4f},'
                f'setpts=PTS-STARTPTS,format=yuv420p[av{idx}]')
            if banner_info['has_audio']:
                graph.append(f'[{b}:a]asetpts=PTS-STARTPTS,atempo={speed:.4f},aresample={SAMPLE_RATE},'
                             f'aformat=sample_fmts=fltp:channel_layouts=stereo,apad,atrim=duration={ad_dur:.4f}[aa{idx}]')
            else:  # GIF or silent banner
                s = add_input('-f', 'lavfi', '-t', f'{ad_dur:.4f}', '-i', f'anullsrc=r={SAMPLE_RATE}:cl=stereo')
                graph.append(f'[{s}:a]aformat=sample_fmts=fltp:channel_layouts=stereo[aa{idx}]')
            labels.append(f'[av{idx}][aa{idx}]')
    graph.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=1[vc][ac]")
    graph.append(f"[vc]ass='{_ffmpeg_filter_path(ass_path)}',format=yuv420p[v]")
    _encode([ffmpeg_path(), '-y', *args, '-filter_complex', ';'.join(graph), '-map', '[v]', '-map', '[ac]'],
            ['-r', str(FPS), '-c:a', 'aac', '-b:a', '192k', '-ar', str(SAMPLE_RATE), '-ac', '2', '-movflags', '+faststart', out], 19,
            (hook[1] if hook else 0.0) + base_dur + len(positions) * ad_dur, progress)
    area = (sw * sh) / (OUT_W * OUT_H)
    return {'visible_area_ratio': area, 'scaled_width': sw, 'scaled_height': sh, 'preserved_aspect_ratio': True,
            'chroma_key_enabled': True, 'banner_audio_used': banner_info['has_audio'], 'source_audio_muted': True,
            'speed': speed, 'banner_starts_at_zero': True}


HOOK_MAX = 4.5


def render_clip(source: str, banner: str, clip: dict, words: list[dict], output: str, speed: float = 1.0,
                speaker_data=None, zoom: float = 1.0, options: dict | None = None):
    """options: background ('blur'|'black'), hook (bool), punch_ins (bool), subtitle_style (dict), srt (bool)."""
    opt = {'background': 'blur', 'hook': True, 'punch_ins': True, 'subtitle_style': None, 'srt': True,
           'progress': None, **(options or {})}
    report = opt['progress'] or (lambda f: None)
    start, end = float(clip['start']), float(clip['end'])
    info = probe(source)
    banner_info = probe(banner)
    speed = max(1.0, min(1.3, float(speed)))
    with tempfile.TemporaryDirectory(prefix='cloudy_') as td:
        keep = plan_keep_ranges(words, start, end)
        mapper, base_dur = make_mapper(keep)
        clip_words = [w for w in words if float(w['end']) > start and float(w['start']) < end]
        word_times = [(mapper(float(w['start']) - start), mapper(float(w['end']) - start)) for w in clip_words]

        sd = speaker_data or {}
        crop_kf = sd.get('keyframes') if sd.get('mode') != 'follow' else None
        follow_kf = sd.get('keyframes') if sd.get('mode') == 'follow' else None
        if crop_kf:
            crop_kf = [(mapper(float(t)), x) for t, x in crop_kf]
        if follow_kf:
            follow_kf = [(mapper(float(t)), x) for t, x in follow_kf]

        punches: list[float] = []
        if opt['punch_ins'] and clip_words:
            local = [(max(0.0, float(w['start']) - start), float(w['end']) - start) for w in clip_words]
            loud = word_loudness(source, start, end - start, local)
            picked = pick_punch_ins([(a, b, w['word']) for (a, b), w in zip(local, clip_words)], loud, end - start)
            punches = [mapper(t) for t in picked]

        base = os.path.join(td, 'base.mp4')
        report(0.02)
        # The first pass is the heavier one (decode + framing + blur), ~60% of the time.
        _render_base(source, base, start, end - start, keep, crop_kf, info, zoom, opt['background'], punches,
                     progress=lambda f: report(0.03 + 0.57 * f), follow_keyframes=follow_kf)
        base_dur = probe(base)['duration'] or base_dur

        hook_range, hook_words = None, []
        if opt['hook'] and clip.get('hook'):
            found = find_hook(clip['hook'], clip_words)
            if found:
                i0, i1 = found
                while i1 > i0 and word_times[i1][1] - word_times[i0][0] > HOOK_MAX: i1 -= 1
                hs = _snap(max(0.0, word_times[i0][0] - 0.1)); he = _snap(min(base_dur, word_times[i1][1] + 0.2))
                if hs >= 3.0 and he - hs >= 1.0:  # a hook already at the very start is pointless
                    hook_range = (hs, he - hs)
                    hook_words = [(w, a - hs, b - hs) for w, (a, b) in zip(clip_words[i0:i1 + 1], word_times[i0:i1 + 1])]
        hook_len = hook_range[1] if hook_range else 0.0

        ad_dur = _snap(banner_info['duration'] / speed)
        count = 1 if hook_len + base_dur + ad_dur < 120 else 2
        positions = _ad_positions(base_dur, ad_dur, count, word_times, hook_len)

        def to_final(t: float) -> float:
            return hook_len + t + ad_dur * sum(1 for p in positions if p <= t + 1e-6)

        final_words = [{'start': max(0.0, a), 'end': min(hook_len, b), 'word': w['word']} for w, a, b in hook_words]
        for w, (a, b) in zip(clip_words, word_times):
            if b - a <= 0: continue
            final_words.append({'start': to_final(a), 'end': to_final(a) + (b - a), 'word': w['word']})
        total = hook_len + base_dur + count * ad_dur
        ass = os.path.join(td, 'captions.ass')
        write_ass(ass, final_words, total, opt['subtitle_style'])
        if opt['srt']:
            write_srt(str(Path(output).with_suffix('.srt')), final_words, total)
        check = _assemble(base, banner, banner_info, output, base_dur, positions, ad_dur, speed, ass, td, hook_range,
                          progress=lambda f: report(0.6 + 0.4 * f))
        out_positions = [round(to_final(p) - ad_dur, 2) for p in positions]
        return {'duration': total, 'banner_count': count, 'banner_positions': out_positions,
                'banner_duration': ad_dur, 'banner_checks': [check] * count,
                'banner_area_ratio': check['visible_area_ratio'], 'banner_area_passed': check['visible_area_ratio'] >= 0.25,
                'aspect_ratio_preserved': True, 'banner_audio_replaces_source_audio': True,
                'chroma_key_removed': True, 'removed_pause_seconds': round((end - start) - sum(b - a for a, b in keep), 2),
                'pause_trim_enabled': True, 'letterbox_enabled': not bool(crop_kf),
                'speaker_tracking': bool(crop_kf), 'hook_seconds': round(hook_len, 2),
                'punch_ins': [round(to_final(p), 2) for p in punches], 'encoder': encoder_name(),
                'ad_windows': [(p, p + ad_dur) for p in out_positions],
                'speaker_tracking_info': speaker_data or {'enabled': False, 'reason': 'Не запускалось'}}


# --------------------------------------------------------------------------- quality scan

def scan_render_quality(path: str, ad_windows: list[tuple[float, float]] | None = None) -> dict[str, Any]:
    """Decode the finished clip once and flag prolonged black/frozen/silent sections.

    Frozen frames inside ad breaks are intentional and are not reported.
    """
    cmd = [ffmpeg_path(), '-hide_banner', '-v', 'info', '-i', path,
           '-vf', 'blackdetect=d=0.35:pix_th=0.10,freezedetect=n=-50dB:d=1.5',
           '-af', 'silencedetect=noise=-45dB:d=1.0', '-f', 'null', '-']
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', **NO_WINDOW)
    log = p.stderr or ''
    ads = ad_windows or []
    inside_ad = lambda t: any(a - 0.2 <= t <= b + 0.2 for a, b in ads)
    black = len(re.findall(r'black_start:', log))
    frozen = sum(1 for t in re.findall(r'freeze_start: ([\d.]+)', log) if not inside_ad(float(t)))
    silence = len(re.findall(r'silence_start:', log))
    return {'scan_completed': p.returncode == 0, 'black_segments': black,
            'frozen_segments': frozen, 'silence_segments': silence,
            'warnings': ([f'Обнаружено чёрных фрагментов: {black}'] if black else []) +
                        ([f'Обнаружено возможных зависаний кадра: {frozen}'] if frozen else []) +
                        ([f'Обнаружены участки тишины: {silence}'] if silence else [])}
