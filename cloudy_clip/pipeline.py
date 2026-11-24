from __future__ import annotations
import json, os, time, traceback
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot
from .media import (probe, transcribe, ai_select, ai_metadata, render_clip, safe_name, scan_render_quality,
                    set_encoder, analyze_scenes, HOOK_MAX)
from .speaker import analyze_active_speaker, soft_follow_keyframes

AD_LINE = 'Лучший VPN с обходом 👇 Ищи в Telegram: @cloudy\n#cloudyvpn'


def output_dir_for(root: str, source: str) -> str:
    """Each source video gets its own subfolder, so a batch never mixes clips."""
    return str(Path(root) / safe_name(Path(source).stem))


DATA_DIR = '.cloudy'
SERVICE_FILES = ('transcript_cache.json', 'transcript.txt', 'clips_manifest.json')


def data_dir_for(out_dir: str | Path) -> Path:
    """Hidden subfolder for service files, so the output folder holds only the clips."""
    d = Path(out_dir) / DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(d), 0x02)  # FILE_ATTRIBUTE_HIDDEN
        except Exception:
            pass
    for name in SERVICE_FILES + tuple(p.name for p in Path(out_dir).glob('ai_answer_part*.txt')):  # tidy older versions
        old = Path(out_dir) / name
        if old.exists():
            try: os.replace(old, d / name)
            except OSError: pass
    return d


def next_clip_number(out_dir: str | Path) -> int:
    """Continue numbering after clips from earlier runs instead of starting at Clip_01 again."""
    import re
    nums = [int(m.group(1)) for p in Path(out_dir).glob('Clip_*.mp4') if (m := re.match(r'Clip_(\d+)_', p.name))]
    return max(nums, default=0) + 1


def target_max_seconds(ad_duration: float, hook: bool) -> int:
    # Final clip = [hook] + speech + ad breaks ≤ 150 s (two breaks for clips ≥ 2:00).
    return int(150 - 2 * ad_duration - (HOOK_MAX if hook else 0))


class Eta:
    """Remaining-time estimate from a 0..1 fraction, smoothed so the number does not jump around."""
    def __init__(self):
        self.t0 = time.monotonic(); self.value = None

    def update(self, frac: float) -> float:
        elapsed = time.monotonic() - self.t0
        if frac < 0.02 or elapsed < 3: return -1.0
        est = elapsed * (1 - frac) / frac
        self.value = est if self.value is None else 0.7 * self.value + 0.3 * est
        return max(0.0, self.value)


class AnalyzeWorker(QObject):
    """Stage 1: speech recognition + choosing moments. Emits the candidate clips."""
    progress = Signal(int, str)
    eta = Signal(float)         # seconds left in the current stage, -1 = unknown
    finished = Signal(object)   # dict: source, out_dir, words, transcript, clips
    failed = Signal(str)

    def __init__(self, source: str, banner: str, out_dir: str, settings: dict):
        super().__init__(); self.source = source; self.banner = banner; self.out_dir = out_dir; self.settings = settings
        self._cancel = False

    def cancel(self): self._cancel = True

    def _cached_transcript(self, model: str):
        """Re-running the same video skips Whisper (the slowest step)."""
        st = os.stat(self.source)
        # 'filter' changes when speech filtering changes: an old transcript is redone once (unless edited by hand).
        key = {'source': os.path.abspath(self.source), 'size': st.st_size, 'mtime': int(st.st_mtime), 'model': model, 'filter': 2}
        cache = data_dir_for(self.out_dir) / 'transcript_cache.json'
        if cache.exists():
            try:
                data = json.loads(cache.read_text(encoding='utf-8'))
                old = dict(data.get('key') or {}); old.pop('filter', None)
                same_video = old == {k: v for k, v in key.items() if k != 'filter'}
                if data.get('words') and (data.get('key') == key or (same_video and data.get('edited'))):
                    return key, data['words'], data.get('transcript', '')
            except Exception:
                pass
        return key, None, None

    @Slot()
    def run(self):
        try:
            Path(self.out_dir).mkdir(parents=True, exist_ok=True)
            self.progress.emit(3, 'Проверка исходных файлов')
            src_info = probe(self.source); banner_info = probe(self.banner)
            if not src_info['has_audio']: raise RuntimeError('В исходном видео не найдена аудиодорожка.')
            if banner_info['duration'] <= 0: raise RuntimeError('Не удалось определить длительность баннера.')
            model = self.settings.get('whisper_model', 'small')
            key, words, transcript = self._cached_transcript(model)
            if words:
                self.progress.emit(35, 'Расшифровка уже есть — Whisper пропущен')
            else:
                self.progress.emit(10, 'Распознавание русской речи (Whisper)')
                eta = Eta()

                def on_whisper(value):
                    if value == 0: eta.__init__()  # restarted on CPU after a GPU failure
                    self.progress.emit(10 + int(25 * value / 100), f'Распознавание речи: {value}%')
                    self.eta.emit(eta.update(value / 100))
                words, transcript = transcribe(self.source, model, self.settings.get('device', 'auto'),
                    progress_callback=on_whisper,
                    notice_callback=lambda msg: self.progress.emit(10, msg))
                if not words: raise RuntimeError('Речь не распознана. Проверьте звук исходного видео.')
                (data_dir_for(self.out_dir) / 'transcript_cache.json').write_text(
                    json.dumps({'key': key, 'words': words, 'transcript': transcript}, ensure_ascii=False), encoding='utf-8')
            (data_dir_for(self.out_dir) / 'transcript.txt').write_text(transcript, encoding='utf-8')
            if self._cancel: raise RuntimeError('Обработка остановлена')
            self.eta.emit(-1.0)
            scenes = None
            if self.settings.get('scene_analysis', True):
                self.progress.emit(35, 'Анализ сцен: смены кадров, движение, заставки')
                try:
                    scenes = analyze_scenes(self.source, str(data_dir_for(self.out_dir) / 'scenes.json'),
                                            progress=lambda f: self.progress.emit(35 + int(3 * f), f'Анализ сцен: {int(f * 100)}%'))
                except Exception as e:
                    self.progress.emit(38, f'Анализ сцен не удался ({str(e)[:80]}) — продолжаю без него')
                    scenes = None
                if self._cancel: raise RuntimeError('Обработка остановлена')
            self.progress.emit(38, 'Поиск лучших моментов (локальный AI)')
            ad_duration = banner_info['duration']
            target_max = target_max_seconds(ad_duration, self.settings.get('hook', True))
            if target_max < 95:
                raise RuntimeError(f'Баннер слишком длинный ({ad_duration:.1f} с): с двумя вставками ролик не уложится в 2:30. '
                                   'Нужен баннер покороче (до ~25 секунд).')
            clips = ai_select(words, transcript, base_url=self.settings.get('ollama_url', 'http://127.0.0.1:11434'),
                              model=self.settings.get('local_model', 'qwen3:4b'), target_min=90, target_max=target_max,
                              use_local_ai=True, notice_callback=lambda msg: self.progress.emit(40, msg),
                              cancel=lambda: self._cancel, fill=self.settings.get('fill_clips', True),
                              debug_dir=str(data_dir_for(self.out_dir)), scenes=scenes)
            if not clips: raise RuntimeError('Не удалось найти фрагменты нужной продолжительности. Попробуйте более длинное видео.')
            # Trim long silent openings/endings when enough speech remains.
            speech_clips = []
            for c in clips:
                inside = [w for w in words if float(w['end']) > float(c['start']) and float(w['start']) < float(c['end'])]
                if not inside: continue
                st = float(c['start']); en = float(c['end'])
                if inside[0]['start'] - st > 2.5: st = max(st, float(inside[0]['start']) - 0.35)
                if en - inside[-1]['end'] > 2.5: en = min(en, float(inside[-1]['end']) + 0.35)
                if en - st >= 90:
                    c['start'] = st; c['end'] = en; speech_clips.append(c)
            clips = sorted(speech_clips or clips, key=lambda c: c.get('score', 0), reverse=True)
            self.progress.emit(50, f'Найдено моментов: {len(clips)}')
            self.finished.emit({'source': self.source, 'out_dir': self.out_dir, 'words': words,
                                'transcript': transcript, 'clips': clips, 'scenes': scenes})
        except Exception as e:
            self.failed.emit(f'{e}\n\nПодробности:\n{traceback.format_exc()}')


class RenderWorker(QObject):
    """Stage 2: metadata, speaker tracking, montage and checks for the chosen clips."""
    progress = Signal(int, str)
    eta = Signal(float)
    finished = Signal(list, str)
    failed = Signal(str)

    def __init__(self, source: str, banner: str, out_dir: str, settings: dict, clips: list[dict], words: list[dict],
                 scenes: dict | None = None):
        super().__init__(); self.source = source; self.banner = banner; self.out_dir = out_dir
        self.settings = settings; self.clips = clips; self.words = words; self.scenes = scenes
        self._cancel = False

    def cancel(self): self._cancel = True

    @Slot()
    def run(self):
        try:
            set_encoder(self.settings.get('encoder', 'auto'))
            Path(self.out_dir).mkdir(parents=True, exist_ok=True)
            words, clips = self.words, self.clips
            url = self.settings.get('ollama_url', 'http://127.0.0.1:11434'); model = self.settings.get('local_model', 'qwen3:4b')
            options = {'background': self.settings.get('background', 'blur'), 'hook': self.settings.get('hook', True),
                       'punch_ins': self.settings.get('punch_ins', True), 'srt': self.settings.get('srt', True),
                       'subtitle_style': self.settings.get('subtitle_style'), 'scenes': self.scenes}
            results = []
            n = len(clips)
            first_no = next_clip_number(self.out_dir)
            eta = Eta()
            for i, clip in enumerate(clips, 1):
                if self._cancel: break
                pct = lambda frac: 50 + int(48 * (i - 1 + frac) / max(1, n))
                stage = {'text': ''}

                def step(frac: float, text: str | None = None, i=i):
                    """frac = progress inside this clip (0..1); emits bar position + remaining time."""
                    if text: stage['text'] = text
                    overall = (i - 1 + frac) / max(1, n)
                    self.progress.emit(50 + int(48 * overall), stage['text'])
                    self.eta.emit(eta.update(overall))
                transcript = clip.get('transcript') or ' '.join(
                    w['word'] for w in words if w['start'] >= clip['start'] and w['end'] <= clip['end'])
                meta = None
                if self.settings.get('ai_descriptions', True):
                    step(0.0, f'Название и описание {i}/{n}')
                    meta = ai_metadata(transcript, url, model)
                if meta:
                    clip['title'] = meta['title'] or clip.get('title', '')
                    if not clip.get('hook') and meta.get('hook'): clip['hook'] = meta['hook']
                title = safe_name(clip.get('title') or f'Clip_{i:02}')
                out = Path(self.out_dir, f'Clip_{first_no + i - 1:02}_{title}.mp4')
                crop_on = self.settings.get('speaker_crop', True)
                follow_on = self.settings.get('soft_follow', True) and float(self.settings.get('zoom', 1.3)) > 1.0
                speaker_data = {'keyframes': [], 'enabled': False, 'reason': 'Весь кадр с фоном, по центру'}
                if crop_on:
                    step(0.03, f'Анализ говорящего {i}/{n}')
                    try:
                        speaker_data = analyze_active_speaker(self.source, float(clip['start']), float(clip['end']), words,
                                                              progress=lambda f: step(0.03 + (0.1 if follow_on else 0.2) * f))
                    except Exception as speaker_error:
                        speaker_data = {'keyframes': [], 'enabled': False, 'reason': f'Резервное кадрирование: {str(speaker_error)[:120]}'}
                if follow_on and not speaker_data.get('keyframes'):
                    # No confident full-screen crop: gently pan the enlarged picture after the face instead.
                    step(0.13 if crop_on else 0.03, f'Слежение за лицом {i}/{n}')
                    try:
                        follow = soft_follow_keyframes(self.source, float(clip['start']), float(clip['end']),
                                                       progress=lambda f: step((0.13 if crop_on else 0.03) + (0.1 if crop_on else 0.2) * f))
                        if follow.get('keyframes'): speaker_data = follow
                        else: speaker_data['reason'] = follow.get('reason', speaker_data['reason'])
                    except Exception:
                        pass
                step(0.23, f"Монтаж {i}/{n}: {clip.get('title') or title}")
                banner_data = render_clip(self.source, self.banner, clip, words, str(out), 1.0, speaker_data=speaker_data,
                                          zoom=float(self.settings.get('zoom', 1.3)),
                                          options={**options, 'progress': lambda f: step(0.23 + 0.72 * f)})
                rendered = probe(str(out))
                step(0.95, f'Финальная проверка {i}/{n}')
                quality_scan = scan_render_quality(str(out), banner_data.get('ad_windows'))
                checks = {
                    'duration_90_150': 89.9 <= rendered['duration'] <= 150.1,
                    'vertical_9_16': rendered['width'] == 1080 and rendered['height'] == 1920,
                    'audio_present': rendered['has_audio'],
                    'banner_count_expected': banner_data['banner_count'] == (1 if rendered['duration'] < 120 else 2),
                    'banner_area_25_percent': banner_data.get('banner_area_passed', False),
                    'banner_aspect_ratio_preserved': banner_data.get('aspect_ratio_preserved', False),
                    'pause_trim_enabled': banner_data.get('pause_trim_enabled', False),
                    'framing_mode_valid': bool(banner_data.get('letterbox_enabled') or banner_data.get('speaker_tracking')),
                    'banner_audio_replaces_source': banner_data.get('banner_audio_replaces_source_audio', False),
                    'chroma_key_removed': banner_data.get('chroma_key_removed', False),
                }
                if meta:
                    parts = [meta['title'], meta['description'], ' '.join(meta['hashtags'])]
                else:
                    parts = [clip.get('title') or '', clip.get('hook') or 'Интересный момент из видео.']
                description = '\n\n'.join(p for p in parts if p) + '\n\n' + AD_LINE
                desc = out.with_suffix('.txt')
                if self.settings.get('save_txt', False): desc.write_text(description, encoding='utf-8')
                srt = out.with_suffix('.srt')
                report = {'file': str(out), 'description': description,
                          'description_file': str(desc) if desc.exists() else '', 'srt_file': str(srt) if srt.exists() else '',
                          'title': clip.get('title', ''), 'start': clip['start'], 'end': clip['end'], 'score': clip.get('score', 0),
                          'reason': clip.get('reason', ''), 'hook': clip.get('hook', ''), 'speaker_tracking': speaker_data,
                          'banner': banner_data, 'quality_scan': quality_scan, 'quality_checks': checks,
                          'quality_passed': all(checks.values()) and quality_scan.get('scan_completed', False),
                          'quality_warnings': (['При сохранении пропорций этот баннер физически занимает менее 25% площади кадра; '
                                                'требуется согласование рекламодателя или другой исходный макет.']
                                               if not banner_data.get('banner_area_passed', False) else []) + quality_scan.get('warnings', [])}
                results.append(report)
                step(1.0, f'Готово {i}/{n}')
            manifest = data_dir_for(self.out_dir) / 'clips_manifest.json'
            old = []
            if manifest.exists():
                try: old = [r for r in json.loads(manifest.read_text(encoding='utf-8')) if r.get('file') not in {x['file'] for x in results}]
                except Exception: old = []
            manifest.write_text(json.dumps(old + results, ensure_ascii=False, indent=2), encoding='utf-8')
            msg = 'Обработка завершена' if not self._cancel else 'Обработка остановлена'
            self.progress.emit(100, msg)
            self.finished.emit(results, msg)
        except Exception as e:
            self.failed.emit(f'{e}\n\nПодробности:\n{traceback.format_exc()}')
