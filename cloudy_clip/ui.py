from __future__ import annotations
import json, os, sys, time
from pathlib import Path
from PySide6.QtCore import QThread, Qt, QUrl, QTimer, QObject, Signal, Slot, QSize
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog, QProgressBar, QListWidget, QListWidgetItem, QMessageBox,
    QTabWidget, QFormLayout, QComboBox, QGroupBox, QTextEdit, QSplitter, QCheckBox, QSpinBox, QFontComboBox,
    QScrollArea, QFrame, QSystemTrayIcon, QStyle, QProgressDialog, QSlider, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSizePolicy)
from .pipeline import AnalyzeWorker, RenderWorker, output_dir_for, data_dir_for
from .media import (SPEAKER_ASPECTS, ffmpeg_available, probe, render_preview_frame, build_sentences, which, NO_WINDOW,
                    SUB_PRESETS, SUB_POSITIONS, ACTIVE_COLORS)
from .widgets import (Switch, NavStack, DropZone, SourceCard, Stepper, Segmented, ThumbWorker, svg_icon,
                      placeholder_thumb, rounded)
from .updater import (APP_VERSION, DEFAULT_OWNER, DEFAULT_REPO, check_release, download_and_stage, is_newer,
                      UpdateError)

STYLE = '''
QMainWindow { background:#0E1116; }
QWidget { color:#E8ECF2; font-family:'Inter','Segoe UI'; font-size:10pt; }
QLabel { background:transparent; }
QLabel#hero { font-size:20pt; font-weight:700; color:#FFFFFF; }
QLabel#h1 { font-size:18pt; font-weight:700; color:#FFFFFF; }
QLabel#h2 { font-size:12pt; font-weight:600; color:#FFFFFF; }
QLabel#muted { color:#93A0B4; }
QLabel#eta { color:#D7DDE7; }
QLabel#chip { background:#262D3A; color:#C3CBD8; border-radius:10px; padding:3px 10px; font-size:9pt; }
QLabel#chipok { background:#1C3A31; color:#7FE3C3; border-radius:10px; padding:3px 10px; font-size:9pt; }
QLabel#badge { background:#2A3140; color:#D7DDE7; border-radius:9px; padding:1px 8px; font-size:9pt; }
QFrame#sidebar { background:#12161D; border-right:1px solid #222935; }
QFrame#sidefoot { background:#161B23; border:1px solid #222935; border-radius:12px; }
QFrame#card, QGroupBox { background:#161B23; border:1px solid #222935; border-radius:14px; }
QGroupBox { margin-top:14px; padding:18px 16px 14px 16px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:14px; top:2px; padding:0 4px; color:#A9B8CE; }
QFrame#dropzone { background:#131820; border:2px dashed #313A4A; border-radius:16px; }
QFrame#dropzone:hover { border-color:#6E5CF0; }
QFrame#bottom { background:#12161D; border-top:1px solid #222935; }
QFrame#segmented { background:#0F1319; border-radius:10px; }
QPushButton#seg { background:transparent; border:0; border-radius:8px; color:#B4BFCF; padding:0 12px; }
QPushButton#seg:checked { background:#6E5CF0; color:#FFFFFF; font-weight:600; }
QPushButton#nav { text-align:left; padding:0 12px; border:0; border-radius:10px; background:transparent; color:#B4BFCF; font-weight:500; }
QPushButton#nav:hover { background:#1A202A; color:#FFFFFF; }
QPushButton#nav:checked { background:#1E2430; color:#FFFFFF; font-weight:600; }
QPushButton { background:#252C3A; border:0; border-radius:10px; padding:9px 16px; color:#FFFFFF; font-weight:600; }
QPushButton:hover { background:#2F3849; }
QPushButton#primary { background:#6E5CF0; } QPushButton#primary:hover { background:#7F6EF4; }
QPushButton#ghost { background:transparent; border:1px solid #2A3140; color:#D7DDE7; font-weight:500; }
QPushButton#ghost:hover { border-color:#3A4456; background:#151A22; }
QPushButton#link { background:transparent; color:#A99CFF; padding:6px 0; font-weight:500; text-align:left; }
QPushButton#icon { background:transparent; padding:0; border-radius:8px; }
QPushButton#icon:hover { background:#1E2430; }
QPushButton#soft { background:#252C3A; }
QPushButton:disabled, QPushButton#primary:disabled { background:#1C2433; color:#6C7789; }
QLineEdit, QComboBox, QTextEdit, QSpinBox, QFontComboBox { background:#0F1319; border:1px solid #2A3140; border-radius:9px; padding:7px 10px; color:#F4F6FB; }
QComboBox::drop-down { border:0; width:24px; }
QComboBox QAbstractItemView { background:#161B23; border:1px solid #2A3140; selection-background-color:#2C3A55; }
QListWidget { background:transparent; border:0; outline:0; }
QListWidget::item { border-radius:12px; padding:6px; color:#E8ECF2; }
QListWidget::item:selected { background:#1E2430; border:1px solid #6E5CF0; }
QListWidget::item:hover:!selected { background:#151A22; }
QListWidget::indicator { width:18px; height:18px; border:1.5px solid #8A97AB; border-radius:5px; background:#0F1319; }
QListWidget::indicator:checked { background:#6E5CF0; border-color:#6E5CF0; }
QProgressBar { background:#232A36; border:0; border-radius:4px; max-height:8px; min-height:8px; text-align:center; color:transparent; }
QProgressBar::chunk { background:#6E5CF0; border-radius:4px; }
QTabWidget::pane { border:0; }
QTabBar::tab { background:#0F1319; color:#B4BFCF; padding:8px 18px; border-radius:8px; margin:2px; }
QTabBar::tab:selected { background:#252C3A; color:#FFFFFF; }
QScrollArea { border:0; background:transparent; }
QScrollBar:vertical { background:transparent; width:10px; margin:2px; }
QScrollBar::handle:vertical { background:#2A3140; border-radius:4px; min-height:30px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; width:0; }
QScrollBar:horizontal { background:transparent; height:10px; margin:2px; }
QScrollBar::handle:horizontal { background:#2A3140; border-radius:4px; min-width:30px; }
QSlider::groove:horizontal { height:4px; background:#2A3140; border-radius:2px; }
QSlider::handle:horizontal { background:#FFFFFF; width:14px; height:14px; margin:-5px 0; border-radius:7px; }
QSlider::sub-page:horizontal { background:#6E5CF0; border-radius:2px; }
QTableWidget { background:#0F1319; border:1px solid #2A3140; border-radius:10px; gridline-color:#202734; color:#F4F6FB; selection-background-color:#2C3A55; }
QHeaderView::section { background:#161B23; color:#A9B8CE; border:0; padding:6px; font-weight:600; }
QTableCornerButton::section { background:#161B23; border:0; }
QToolTip { background:#1E2430; color:#E8ECF2; border:1px solid #2A3140; padding:6px; }
'''

ZOOM_ITEMS = ['100% — весь кадр', '115%', '130%', '150%', '175% — почти без полос']


class UpdateCheckWorker(QObject):
    found = Signal(object)
    failed = Signal(str)

    def __init__(self, owner: str, repo: str):
        super().__init__(); self.owner, self.repo = owner, repo

    @Slot()
    def run(self):
        try: self.found.emit(check_release(self.owner, self.repo))
        except Exception as e: self.failed.emit(str(e))


class UpdateDownloadWorker(QObject):
    progress = Signal(int, int)
    done = Signal()
    failed = Signal(str)

    def __init__(self, release: dict, install_dir: Path):
        super().__init__(); self.release, self.install_dir = release, install_dir

    @Slot()
    def run(self):
        try:
            download_and_stage(self.release, self.install_dir, progress=lambda d, t: self.progress.emit(d, t))
            self.done.emit()
        except Exception as e:
            self.failed.emit(str(e))


class PreviewWorker(QObject):
    done = Signal(str, str, int)    # png path, note, request id
    failed = Signal(str, int)

    def __init__(self, req: dict):
        super().__init__(); self.req = req

    @Slot()
    def run(self):
        r = self.req
        try:
            note = ''
            cx = fx = None
            if r.get('speaker'):
                from .speaker import analyze_active_speaker, soft_follow_keyframes
                a, b = max(0.0, r['t'] - 2.5), r['t'] + 2.5
                rel = r['t'] - a
                if r.get('crop_on', True):
                    kf = analyze_active_speaker(r['source'], a, b, r.get('words') or []).get('keyframes') or []
                    if kf:
                        cx = min(kf, key=lambda k: abs(k[0] - rel))[1]
                        note = 'кадр по говорящему' + (' (на весь экран)' if r.get('speaker_frame', 'full') == 'full' else '')
                if cx is None and r.get('follow_on', True):
                    kf = soft_follow_keyframes(r['source'], a, b, sample_fps=3).get('keyframes') or []
                    if kf:
                        fx = min(kf, key=lambda k: abs(k[0] - rel))[1]; note = 'мягкое слежение: кадр сдвинут к лицу'
                if cx is None and fx is None:
                    note = 'лицо не найдено — кадр по центру'
            out = os.path.join(r['dir'], f"preview_{r['id']}.png")
            render_preview_frame(r['source'], r['t'], out, words=r.get('words'), zoom=r['zoom'], background=r['background'],
                                 subtitle_style=r['style'], crop_center_x=cx, info=r.get('info'), follow_center_x=fx,
                                 crop_aspect=SPEAKER_ASPECTS.get(r.get('speaker_frame', 'full'), 9 / 16))
            self.done.emit(out, note, r['id'])
        except Exception as e:
            self.failed.emit(str(e)[:300], r['id'])


def _fmt_precise(t: float) -> str:
    t = max(0.0, t); return f'{int(t // 60)}:{t % 60:04.1f}'


def _parse_time(text: str) -> float | None:
    text = text.strip().replace(',', '.')
    try:
        if ':' in text:
            m, sec = text.rsplit(':', 1); return int(m) * 60 + float(sec)
        return float(text)
    except ValueError:
        return None


class CaptionEditor(QWidget):
    """Edit the subtitles of one moment before montage: fix text, add missing lines, delete wrong ones.

    Edits replace the transcript words inside the moment, so captions, hook search and pause cutting
    all use the corrected text. Word timings inside a line are spread by word length.
    """

    def __init__(self, window):
        super().__init__(); self.win = window; self.clip = None; self._filling = False; self._player = None
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0)
        hint = QLabel('Двойной щелчок по тексту — исправить. Время можно поправить в первых двух столбцах.')
        hint.setObjectName('muted'); hint.setWordWrap(True); v.addWidget(hint)
        self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(['Начало', 'Конец', 'Текст'])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 80); self.table.setColumnWidth(1, 80)
        self.table.verticalHeader().setVisible(False); self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection); self.table.setWordWrap(True)
        self.table.itemChanged.connect(self._on_changed); self.table.currentCellChanged.connect(self._on_row)
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        b = QPushButton('▶ Прослушать'); b.clicked.connect(self.listen); row.addWidget(b)
        b = QPushButton('+ Строка здесь'); b.setToolTip('Добавить строку в момент, на котором стоит ползунок превью'); b.clicked.connect(self.add_row); row.addWidget(b)
        b = QPushButton('Удалить строку'); b.clicked.connect(self.delete_row); row.addWidget(b)
        row.addStretch(); v.addLayout(row)
        self._apply_timer = QTimer(self); self._apply_timer.setSingleShot(True); self._apply_timer.timeout.connect(self.apply)

    def set_clip(self, clip: dict | None):
        self.clip = clip; self._filling = True
        self.table.setRowCount(0)
        if clip and self.win.analysis:
            words = [w for w in self.win.analysis['words'] if w['end'] > clip['start'] and w['start'] < clip['end']]
            for s in build_sentences(words, max_pause=0.6, max_words=12):
                self._append(s['start'], s['end'], s['text'])
        self._filling = False

    def _append(self, a: float, b: float, text: str, at: int | None = None):
        r = self.table.rowCount() if at is None else at
        self.table.insertRow(r)
        for col, val in enumerate((_fmt_precise(a), _fmt_precise(b), text)):
            self.table.setItem(r, col, QTableWidgetItem(val))
        return r

    def rows(self) -> list[tuple[float, float, str]]:
        out = []
        for r in range(self.table.rowCount()):
            a = _parse_time(self.table.item(r, 0).text()); b = _parse_time(self.table.item(r, 1).text())
            text = ' '.join(self.table.item(r, 2).text().split())
            if a is not None and b is not None and b > a and text: out.append((a, b, text))
        return sorted(out)

    def _on_changed(self, item):
        if self._filling: return
        if item.column() < 2 and _parse_time(item.text()) is None:
            item.setBackground(Qt.darkRed)
        else:
            item.setBackground(Qt.transparent)
        self._apply_timer.start(400)

    def _on_row(self, row, *_):
        if row < 0 or not self.clip or self._filling: return
        a = _parse_time(self.table.item(row, 0).text()) if self.table.item(row, 0) else None
        if a is not None:
            self.win.select_preview.set_source(self.win.analysis['source'], self.clip['start'], self.clip['end'],
                                               self.win.analysis['words'], at=min(self.clip['end'], a + 0.15))

    def add_row(self):
        if not self.clip: return
        t = self.win.select_preview.current_time() if self.win.select_preview.source else self.clip['start']
        pos = 0
        while pos < self.table.rowCount() and (_parse_time(self.table.item(pos, 0).text()) or 0) <= t: pos += 1
        self._filling = True; r = self._append(t, min(self.clip['end'], t + 2.0), 'новая фраза', at=pos); self._filling = False
        self.table.setCurrentCell(r, 2); self.table.editItem(self.table.item(r, 2))
        self._apply_timer.start(400)

    def delete_row(self):
        r = self.table.currentRow()
        if r >= 0: self.table.removeRow(r); self._apply_timer.start(10)

    def apply(self):
        """Replace the transcript words inside this moment with the edited lines."""
        if not self.clip or not self.win.analysis: return
        new_words = []
        for a, b, text in self.rows():
            tokens = text.split(); total = sum(len(t) + 1 for t in tokens); cur = a
            for tok in tokens:
                d = (b - a) * (len(tok) + 1) / total
                new_words.append({'start': round(cur, 3), 'end': round(cur + d * 0.92, 3), 'word': ' ' + tok}); cur += d
        words = self.win.analysis['words']
        keep = [w for w in words if w['end'] <= self.clip['start'] or w['start'] >= self.clip['end']]
        words[:] = sorted(keep + new_words, key=lambda w: w['start'])   # in place: preview and montage share this list
        self.clip['transcript'] = ' '.join(t for _, _, t in self.rows())
        self.win.captions_edited = True
        self.win.select_preview.request()

    def listen(self):
        r = self.table.currentRow()
        if r < 0 or not self.win.analysis:
            QMessageBox.information(self, 'Прослушать', 'Выберите строку в таблице.'); return
        a = _parse_time(self.table.item(r, 0).text()); b = _parse_time(self.table.item(r, 1).text())
        if a is None or b is None: return
        src = self.win.analysis['source']
        if self._player is not None:
            try: self._player.kill()
            except Exception: pass
        ffplay = which('ffplay')
        if ffplay:
            import subprocess
            self._player = subprocess.Popen([ffplay, '-nodisp', '-autoexit', '-loglevel', 'quiet', '-ss', f'{max(0.0, a - 0.2):.2f}',
                                             '-t', f'{b - a + 0.5:.2f}', src], **NO_WINDOW)
            return
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            if not hasattr(self, '_qt_player'):
                self._qt_player = QMediaPlayer(self); self._qt_out = QAudioOutput(self); self._qt_player.setAudioOutput(self._qt_out)
                self._qt_stop = QTimer(self); self._qt_stop.setSingleShot(True); self._qt_stop.timeout.connect(self._qt_player.stop)
            self._qt_player.setSource(QUrl.fromLocalFile(src)); self._qt_player.setPosition(int(max(0.0, a - 0.2) * 1000))
            self._qt_player.play(); self._qt_stop.start(int((b - a + 0.5) * 1000))
        except Exception:
            QMessageBox.information(self, 'Прослушать', 'Не найден ffplay (входит в FFmpeg) — прослушивание недоступно.')


class PreviewPane(QWidget):
    """A 9:16 frame of how the clip will look, rendered by the same filters as the real montage."""

    def __init__(self, window, speaker_option: bool = True, hint: str = ''):
        super().__init__(); self.win = window
        self.source = ''; self.start = 0.0; self.end = 0.0; self.words = None; self.info = None
        self._req_id = 0; self._busy = False; self._pending = False; self._threads = []
        import tempfile
        self._dir = tempfile.mkdtemp(prefix='cloudy_preview_')
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0)
        title = QLabel('Превью кадра'); title.setStyleSheet('font-weight:600'); v.addWidget(title)
        self.image = QLabel(hint or 'Добавьте видео, чтобы увидеть превью'); self.image.setAlignment(Qt.AlignCenter)
        self.image.setFixedSize(252, 448); self.image.setWordWrap(True)
        self.image.setStyleSheet('background:#0B0E13;border:1px solid #2A3140;border-radius:14px;color:#7F8A9C;padding:12px;')
        v.addWidget(self.image, 0, Qt.AlignHCenter)
        self.slider = QSlider(Qt.Horizontal); self.slider.setEnabled(False); self.slider.setFixedWidth(252)
        self.slider.valueChanged.connect(self._on_slider); v.addWidget(self.slider)
        self.time_label = QLabel(''); self.time_label.setObjectName('muted'); self.time_label.setAlignment(Qt.AlignCenter); v.addWidget(self.time_label)
        self.speaker = Switch('По говорящему'); self.speaker.setToolTip('Показать, куда программа повернёт кадр, если найдёт лицо. Считается несколько секунд.')
        self.speaker.toggled.connect(lambda _: self.request())
        self.speaker.toggled.connect(lambda on: self.win.sync_preview_speaker(on, self))
        if speaker_option: v.addWidget(self.speaker)
        self.note = QLabel(''); self.note.setObjectName('muted'); self.note.setWordWrap(True); self.note.setFixedWidth(252); v.addWidget(self.note)
        v.addStretch()
        self._debounce = QTimer(self); self._debounce.setSingleShot(True); self._debounce.timeout.connect(self._start)

    def set_source(self, source: str | None, start: float = 0.0, end: float | None = None, words=None, at: float | None = None):
        if not source:
            self.source = ''; self.slider.setEnabled(False); self.time_label.setText('')
            self.image.setPixmap(QPixmap()); self.image.setText('Добавьте видео на вкладке «Новый проект», чтобы увидеть превью')
            return
        try:
            if source != self.source or self.info is None: self.info = probe(source)
        except Exception as e:
            self.image.setText(f'Не удалось открыть видео:\n{e}'); return
        self.source, self.words = source, words
        self.start = max(0.0, float(start)); self.end = float(end) if end else self.info['duration']
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(1, int((self.end - self.start) * 10)))
        pos = (at if at is not None else self.start + min(10.0, (self.end - self.start) / 3)) - self.start
        self.slider.setValue(int(max(0.0, pos) * 10)); self.slider.blockSignals(False); self.slider.setEnabled(True)
        self.request()

    def current_time(self) -> float:
        return self.start + self.slider.value() / 10

    def _on_slider(self, _):
        self.time_label.setText(_fmt(self.current_time())); self.request(delay=250)

    def request(self, delay: int = 350):
        if not self.source: return
        self.time_label.setText(_fmt(self.current_time()))
        self._debounce.start(delay)

    def _start(self):
        if self._busy:  # one render at a time; remember that the settings changed meanwhile
            self._pending = True; return
        self._busy = True; self._pending = False; self._req_id += 1
        st = self.win.preview_settings()
        req = {'id': self._req_id, 'source': self.source, 't': self.current_time(), 'words': self.words,
               'info': self.info, 'dir': self._dir,
               'speaker': self.speaker.isChecked() and (self.win.speaker_crop.isChecked() or self.win.soft_follow.isChecked()),
               'crop_on': self.win.speaker_crop.isChecked(), 'follow_on': self.win.soft_follow.isChecked(), **st}
        self.note.setText('Обновляю…')
        self._threads = [(t, w) for t, w in self._threads if t.isRunning()]
        worker = PreviewWorker(req); thread = QThread(); worker.moveToThread(thread)
        thread.started.connect(worker.run); worker.done.connect(self._on_done); worker.failed.connect(self._on_failed)
        worker.done.connect(thread.quit); worker.failed.connect(thread.quit)
        self._threads.append((thread, worker)); thread.start()

    def _finish(self):
        self._busy = False
        if self._pending: self._start()

    def _on_done(self, path: str, note: str, rid: int):
        pm = QPixmap(path)
        if not pm.isNull():
            self.image.setPixmap(pm.scaled(self.image.width() - 4, self.image.height() - 4, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if not note and (self.win.speaker_crop.isChecked() or self.win.soft_follow.isChecked()):
            note = ('Кадр по центру. В ролике кадр подстроится под лицо, если программа его найдёт — '
                    'включите «По говорящему», чтобы увидеть.')
        self.note.setText(note); self._finish()

    def _on_failed(self, err: str, rid: int):
        self.note.setText('Не удалось построить превью: ' + err); self._finish()


def apply_theme(app):
    """Dark palette for everything the stylesheet does not paint (scroll areas, viewports, popups)."""
    from PySide6.QtGui import QPalette, QColor
    pal = QPalette()
    for role, color in ((QPalette.Window, '#0E1116'), (QPalette.Base, '#0F1319'), (QPalette.AlternateBase, '#161B23'),
                        (QPalette.Text, '#E8ECF2'), (QPalette.WindowText, '#E8ECF2'), (QPalette.Button, '#252C3A'),
                        (QPalette.ButtonText, '#FFFFFF'), (QPalette.Highlight, '#6E5CF0'), (QPalette.HighlightedText, '#FFFFFF'),
                        (QPalette.ToolTipBase, '#1E2430'), (QPalette.ToolTipText, '#E8ECF2'), (QPalette.PlaceholderText, '#6C7789')):
        pal.setColor(role, QColor(color))
    app.setPalette(pal); app.setStyleSheet(STYLE)
    f = QFont('Inter', 10)
    if not f.exactMatch(): f = QFont('Segoe UI', 10)
    app.setFont(f)


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    return base / relative


VIDEO_EXT = ('.mp4', '.mov', '.mkv', '.avi', '.webm')


def _human(sec: float) -> str:
    sec = int(max(0, round(sec)))
    if sec < 60: return f'{sec} с'
    if sec < 3600: return f'{sec // 60} мин {sec % 60:02} с'
    return f'{sec // 3600} ч {sec % 3600 // 60:02} мин'


def _keep_awake(on: bool) -> None:
    """Stop Windows from sleeping during long processing (the screen may still turn off)."""
    if os.name != 'nt': return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def _fmt(t: float) -> str:
    t = int(round(t)); return f'{t // 3600}:{t % 3600 // 60:02}:{t % 60:02}' if t >= 3600 else f'{t // 60}:{t % 60:02}'


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle('Cloudy Clip Studio'); self.resize(1180, 820)
        bundled_banner = resource_path('assets/cloudy_banner.mp4')
        self.banner = str(bundled_banner) if bundled_banner.exists() else ''
        self.sources: list[str] = []
        self.results: list[dict] = []
        self.queue: list[str] = []; self.current_source = ''; self.current_out = ''; self.run_settings: dict = {}
        self.analysis: dict | None = None
        self._threads: list = []; self.worker = None; self._cancelled = False
        self.setAcceptDrops(True)
        icon = resource_path('assets/icon.ico')
        self.setWindowIcon(QIcon(str(icon)) if icon.exists() else self.style().standardIcon(QStyle.SP_MediaPlay))
        self.auto_update = True; self.skip_version = ''; self.shortcut_offered = False; self._update_manual = False
        self.resize(1320, 860)
        root = QWidget(); self.setCentralWidget(root); outer = QHBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        self.tabs = NavStack([('Проект', 'plus'), ('Оформление', 'palette'), ('Моменты', 'grid'), ('Результаты', 'phone'), ('Настройки', 'gear')])
        outer.addWidget(self.tabs.sidebar)
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0); rv.setSpacing(0)
        rv.addWidget(self.tabs, 1); outer.addWidget(right, 1)
        self._thumb_threads: list = []
        self._build_project_tab(); self._build_design_tab(); self._build_select_tab(); self._build_results_tab(); self._build_settings_tab()
        rv.addWidget(self._build_bottom_bar())
        self._refresh_sidebar_status()
        self._loading = True
        self.load_settings()
        self._loading = False
        self._res_thumbs: dict[str, QPixmap] = {}
        self._load_session()
        self._wire_autosave()
        self.tray = QSystemTrayIcon(self.windowIcon(), self) if QSystemTrayIcon.isSystemTrayAvailable() else None
        self._t_start = None; self._eta = -1.0; self._eta_at = 0.0
        self.clock = QTimer(self); self.clock.timeout.connect(self._tick); self.clock.start(1000)
        QTimer.singleShot(1500, self._offer_shortcut)
        if self.auto_update: QTimer.singleShot(3000, lambda: self.check_for_updates(manual=False))

    def _refresh_sidebar_status(self):
        txt = self._gpu_status()
        ready = txt.startswith('✓')
        self.tabs.gpu_line.setText(('●  RTX готова' if ready else '●  Видеокарта не настроена') if 'NVIDIA' in txt else '●  Процессор')
        self.tabs.gpu_line.setStyleSheet(f"color:{'#7FE3C3' if ready else '#E8C77F'};")
        self.tabs.gpu_line.setToolTip(txt)
        self.tabs.version_line.setText(f'Версия {APP_VERSION}')

    @staticmethod
    def _page(title: str, subtitle: str = '', action: QWidget | None = None):
        """Page shell: centred column (max 1040 px) with a header."""
        page = QWidget(); outer = QHBoxLayout(page); outer.setContentsMargins(40, 32, 40, 24)
        outer.setSizeConstraint(QHBoxLayout.SetMinimumSize)   # scroll instead of squeezing cards into each other
        col = QWidget(); col.setMaximumWidth(1040); lay = QVBoxLayout(col); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(18)
        head = QHBoxLayout(); texts = QVBoxLayout(); texts.setSpacing(4)
        t = QLabel(title); t.setObjectName('h1'); texts.addWidget(t)
        if subtitle:
            st = QLabel(subtitle); st.setObjectName('muted'); st.setWordWrap(True); texts.addWidget(st)
        head.addLayout(texts, 1)
        if action is not None: head.addWidget(action, 0, Qt.AlignBottom)
        lay.addLayout(head)
        outer.addStretch(); outer.addWidget(col, 100); outer.addStretch()
        return page, lay

    @staticmethod
    def _gpu_status() -> str:
        try:
            from .gpu import cuda_device_count, gpu_libs_installed
            n, libs = cuda_device_count(), gpu_libs_installed()
        except Exception:
            n, libs = 0, False
        if n and libs: return '✓ Видеокарта NVIDIA готова: распознавание речи пойдёт на ней (быстро).'
        if n: return ('⚠ Видеокарта NVIDIA есть, но библиотеки для неё не установлены — распознавание идёт на процессоре (медленно). '
                      'Закройте программу и запустите enable_gpu.bat.')
        return 'Видеокарта NVIDIA не найдена — распознавание на процессоре.'

    @staticmethod
    def _scroll(widget: QWidget) -> QScrollArea:
        """Tabs scroll instead of squeezing fields when the window is shorter than the content."""
        area = QScrollArea(); area.setWidgetResizable(True); area.setFrameShape(QFrame.NoFrame); area.setWidget(widget)
        return area

    def _build_bottom_bar(self) -> QWidget:
        bar = QFrame(); bar.setObjectName('bottom'); h = QHBoxLayout(bar); h.setContentsMargins(40, 14, 40, 14); h.setSpacing(20)
        self.stepper = Stepper(); h.addWidget(self.stepper)
        mid = QVBoxLayout(); mid.setSpacing(6)
        self.progress = QProgressBar(); self.progress.setValue(0); self.progress.setTextVisible(False)
        info = QHBoxLayout(); info.setSpacing(12)
        self.progress_label = QLabel('Перетащите видео в окно или нажмите «Выбрать файлы».'); self.progress_label.setObjectName('muted')
        self.queue_label = QLabel(''); self.queue_label.setObjectName('muted')
        self.eta_label = QLabel(''); self.eta_label.setObjectName('eta')
        for lab in (self.progress_label, self.queue_label, self.eta_label):
            lab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred); lab.setMinimumWidth(40)   # long texts never widen the window
        info.addWidget(self.progress_label, 5); info.addWidget(self.queue_label, 2); info.addWidget(self.eta_label, 3)
        mid.addWidget(self.progress); mid.addLayout(info); h.addLayout(mid, 1)
        self.cancel_btn = QPushButton('Отменить'); self.cancel_btn.setObjectName('ghost'); self.cancel_btn.setEnabled(False)
        self.cancel_btn.setMinimumHeight(44); self.cancel_btn.clicked.connect(self.cancel_processing)
        self.start_btn = QPushButton('  Начать обработку'); self.start_btn.setObjectName('primary'); self.start_btn.setMinimumHeight(44)
        self.start_btn.setIcon(svg_icon('play', '#FFFFFF', 14)); self.start_btn.clicked.connect(self.start_processing)
        h.addWidget(self.cancel_btn); h.addWidget(self.start_btn)
        self.status = self.progress_label
        return bar

    # ------------------------------------------------------------------ tabs
    def _build_project_tab(self):
        open_btn = QPushButton('Открыть папку с роликами'); open_btn.setObjectName('ghost'); open_btn.clicked.connect(self.open_folder)
        page, lay = self._page('Новый проект', 'Длинное видео → серия вертикальных роликов с субтитрами', open_btn)
        self.drop = DropZone(); self.drop.setMinimumHeight(210); self.drop.clicked.connect(self.pick_sources); lay.addWidget(self.drop)
        self.src_list = QListWidget(); self.src_list.setSpacing(4); self.src_list.setSelectionMode(QListWidget.NoSelection)
        self.src_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.src_list.hide(); lay.addWidget(self.src_list)

        cards = QHBoxLayout(); cards.setSpacing(16)
        left = QFrame(); left.setObjectName('card'); lv = QVBoxLayout(left); lv.setContentsMargins(20, 18, 20, 18); lv.setSpacing(12)
        t = QLabel('Сколько роликов'); t.setObjectName('h2'); lv.addWidget(t)
        self.fill_clips = QComboBox(); self.fill_clips.addItems(['Как можно больше — нейросеть + добор из остального видео', 'Только лучшие — что выбрала нейросеть'])
        self.fill_clips.hide(); lv.addWidget(self.fill_clips)
        lv.addWidget(Segmented(self.fill_clips, ['Как можно больше', 'Только лучшие']))
        self.fill_note = QLabel(''); self.fill_note.setObjectName('muted'); self.fill_note.setWordWrap(True); lv.addWidget(self.fill_note)
        self.fill_clips.currentIndexChanged.connect(lambda i: self.fill_note.setText(
            'Моменты от нейросети + добор из остального видео' if i == 0 else 'Только то, что выбрала нейросеть'))
        self.fill_note.setText('Моменты от нейросети + добор из остального видео'); lv.addStretch()
        right = QFrame(); right.setObjectName('card'); rv = QVBoxLayout(right); rv.setContentsMargins(20, 14, 20, 14); rv.setSpacing(4)
        self.manual_pick = Switch('Выбрать моменты вручную перед монтажом'); self.manual_pick.setChecked(True); rv.addWidget(self.manual_pick)
        self.ai_desc = Switch('Название, описание и хэштеги через AI'); self.ai_desc.setChecked(True); rv.addWidget(self.ai_desc)
        self.use_banner = QCheckBox(right); self.use_banner.setChecked(True); self.use_banner.hide()  # set by the banner buttons
        self.more_btn = QPushButton('Дополнительно: модель, устройство, кодирование, папки  ›'); self.more_btn.setObjectName('link')
        self.more_btn.setCheckable(True); rv.addWidget(self.more_btn); rv.addStretch()
        left.setMinimumHeight(150); right.setMinimumHeight(150)
        cards.addWidget(left, 1); cards.addWidget(right, 1); lay.addLayout(cards)

        self.more = QFrame(); self.more.setObjectName('card'); of = QFormLayout(self.more); of.setContentsMargins(20, 18, 20, 18); of.setSpacing(10)
        self.whisper = QComboBox(); self.whisper.addItems(['small', 'medium', 'large-v3-turbo', 'large-v3']); self.whisper.setCurrentText('large-v3-turbo'); of.addRow('Модель распознавания', self.whisper)
        model_note = QLabel('large-v3-turbo — лучший баланс. large-v3 точнее совсем чуть-чуть, но в несколько раз медленнее. '
                            'small — самая быстрая, текст немного хуже.'); model_note.setWordWrap(True); model_note.setObjectName('muted'); of.addRow(model_note)
        self.device = QComboBox(); self.device.addItems(['auto', 'cuda', 'cpu']); of.addRow('Устройство распознавания', self.device)
        self.gpu_label = QLabel(self._gpu_status()); self.gpu_label.setWordWrap(True); self.gpu_label.setObjectName('muted'); of.addRow(self.gpu_label)
        self.encoder = QComboBox(); self.encoder.addItems(['Авто — видеокарта NVIDIA, если есть', 'Только процессор']); of.addRow('Кодирование видео', self.encoder)
        self.out_edit = QLineEdit(str(Path.home() / 'Videos' / 'CloudyClipStudio')); orow = QHBoxLayout(); orow.addWidget(self.out_edit, 1)
        ob = QPushButton('Выбрать'); ob.setObjectName('ghost'); ob.clicked.connect(self.pick_output); orow.addWidget(ob); of.addRow('Папка для роликов', orow)
        self.banner_edit = QLineEdit(self.banner); self.banner_edit.setReadOnly(True); br = QHBoxLayout(); br.addWidget(self.banner_edit, 1)
        bb = QPushButton('Выбрать'); bb.setObjectName('ghost'); bb.clicked.connect(self.pick_banner); br.addWidget(bb)
        bx = QPushButton('Без баннера'); bx.setObjectName('ghost'); bx.setToolTip('Делать ролики без рекламной вставки. Вернуть — кнопка «Выбрать».')
        bx.clicked.connect(lambda: self.use_banner.setChecked(False)); br.addWidget(bx); of.addRow('Рекламный баннер', br)
        self.use_banner.toggled.connect(self._sync_banner_field); self._sync_banner_field()
        self.more.setMinimumHeight(360); self.more.hide(); lay.addWidget(self.more)
        self.more_btn.toggled.connect(lambda on: (self.more.setVisible(on), self.more_btn.setText(
            'Дополнительно: модель, устройство, кодирование, папки  ' + ('⌄' if on else '›'))))
        lay.addStretch()
        self.tabs.addTab(self._scroll(page), 'Новый проект')

    def _build_design_tab(self):
        tab, lay = self._page('Оформление', 'Как будут выглядеть ролики. Справа — кадр из вашего видео с текущими настройками.')
        frame = QGroupBox('Картинка'); ff = QFormLayout(frame)
        self.background = QComboBox(); self.background.addItems(['Размытое видео', 'Чёрные полосы']); ff.addRow('Фон вместо полос', self.background)
        self.zoom = QComboBox(); self.zoom.addItems(ZOOM_ITEMS); self.zoom.setCurrentText('130%'); ff.addRow('Размер видео', self.zoom)
        n = QLabel('Для горизонтального видео: чем крупнее, тем меньше фон, но сильнее обрезаются края. '
                   'Если программа уверенно нашла говорящего, кадр строится вокруг него (форма — ниже).'); n.setWordWrap(True); n.setObjectName('muted'); ff.addRow(n)
        self.hook = Switch('Хук: самая цепляющая фраза ролика в первые секунды'); self.hook.setChecked(True); ff.addRow(self.hook)
        self.punch = Switch('Приближения на громких и эмоциональных моментах'); self.punch.setChecked(True); ff.addRow(self.punch)
        self.speaker_crop = Switch('Кадрирование по говорящему: если найдено лицо, кадр обрезается вокруг него и следует за ним')
        self.speaker_crop.setChecked(True); ff.addRow(self.speaker_crop)
        self.speaker_frame = QComboBox(frame); self.speaker_frame.addItems(['На весь экран', '4:5', 'Квадрат'])
        self.speaker_frame.setCurrentIndex(2); self.speaker_frame.hide()  # square with background above and below, as in TikTok edits
        self.speaker_frame_seg = Segmented(self.speaker_frame, ['На весь экран', '4:5 · небольшие отступы', 'Квадрат'])
        ff.addRow('Кадр по говорящему', self.speaker_frame_seg)
        self.speaker_crop.toggled.connect(self.speaker_frame_seg.setEnabled)
        self.soft_follow = Switch('Мягкое слежение за лицом: увеличенное видео плавно сдвигается за лицом, чтобы его не обрезало')
        self.soft_follow.setChecked(True); ff.addRow(self.soft_follow)
        self.scene_analysis = Switch('Анализ сцен: ролики заканчиваются на смене сцены или конце разговора, паузы с действием остаются, заставки вырезаются')
        self.scene_analysis.setChecked(True); ff.addRow(self.scene_analysis)
        lay.addWidget(frame)
        subs = QGroupBox('Субтитры'); sf = QFormLayout(subs)
        self.sub_preset = QComboBox(); self.sub_preset.addItems(list(SUB_PRESETS)); self.sub_preset.currentTextChanged.connect(self.apply_preset); sf.addRow('Стиль', self.sub_preset)
        self.sub_font = QFontComboBox(); sf.addRow('Шрифт', self.sub_font)
        self.sub_size = QSpinBox(); self.sub_size.setRange(30, 130); sf.addRow('Размер', self.sub_size)
        self.sub_pos = QComboBox(); self.sub_pos.addItems(list(SUB_POSITIONS)); sf.addRow('Положение', self.sub_pos)
        self.sub_color = QComboBox(); self.sub_color.addItems(list(ACTIVE_COLORS)); sf.addRow('Цвет текущего слова', self.sub_color)
        self.sub_upper = Switch('ЗАГЛАВНЫМИ БУКВАМИ'); sf.addRow(self.sub_upper)
        self.sub_nopunct = Switch('Без знаков препинания (вопросительный знак остаётся)'); self.sub_nopunct.setChecked(True); sf.addRow(self.sub_nopunct)
        self.srt = Switch('Сохранять субтитры отдельным файлом .srt (для загрузки на площадку)'); self.srt.setChecked(True); sf.addRow(self.srt)
        self.save_txt = Switch('Сохранять описание ролика отдельным файлом .txt рядом с роликом'); self.save_txt.setChecked(False); sf.addRow(self.save_txt)
        lay.addWidget(subs)
        music = QGroupBox('Музыка'); mf = QFormLayout(music)
        self.music_files: list[str] = []
        self.music_on = Switch('Добавлять фоновую музыку в каждый ролик'); mf.addRow(self.music_on)
        row = QHBoxLayout(); row.setSpacing(8)
        self.music_label = QLabel('Музыка не выбрана'); self.music_label.setObjectName('muted'); self.music_label.setWordWrap(True)
        self.music_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred); row.addWidget(self.music_label, 1)
        b = QPushButton('Выбрать…'); b.setObjectName('soft'); b.clicked.connect(self.pick_music); row.addWidget(b)
        b = QPushButton('Убрать'); b.setObjectName('ghost'); b.clicked.connect(self.clear_music); row.addWidget(b)
        mf.addRow('Треки', row)
        vrow = QHBoxLayout()
        self.music_volume = QSlider(Qt.Horizontal); self.music_volume.setRange(0, 100); self.music_volume.setValue(30)
        self.music_volume_label = QLabel('30%'); self.music_volume_label.setMinimumWidth(42)
        self.music_volume.valueChanged.connect(lambda v: self.music_volume_label.setText(f'{v}%'))
        vrow.addWidget(self.music_volume, 1); vrow.addWidget(self.music_volume_label)
        mf.addRow('Громкость музыки', vrow)
        n = QLabel('Музыка играет под звуком видео. Во время рекламного баннера она плавно затихает до нуля, '
                   'потом возвращается. Короткий трек повторяется по кругу. Если треков несколько, ролики получают их по очереди.')
        n.setWordWrap(True); n.setObjectName('muted'); mf.addRow(n)
        lay.addWidget(music); lay.addStretch()
        self.apply_preset(self.sub_preset.currentText())
        page = QWidget(); h = QHBoxLayout(page); h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self._scroll(tab), 1)
        self.design_preview = PreviewPane(self, speaker_option=True)
        side = QWidget(); sv = QVBoxLayout(side); sv.setContentsMargins(6, 0, 6, 0); sv.addWidget(self.design_preview)
        side_area = self._scroll(side); side_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); side_area.setFixedWidth(290)
        h.addWidget(side_area)
        for sig in (self.background.currentIndexChanged, self.zoom.currentIndexChanged, self.sub_preset.currentIndexChanged,
                    self.sub_font.currentFontChanged, self.sub_size.valueChanged, self.sub_pos.currentIndexChanged,
                    self.sub_color.currentIndexChanged, self.sub_upper.toggled, self.sub_nopunct.toggled, self.speaker_crop.toggled,
                    self.soft_follow.toggled, self.speaker_frame.currentIndexChanged):
            sig.connect(lambda *_: self.design_preview.request())
        self.tabs.addTab(page, 'Оформление')
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _build_select_tab(self):
        tab = QWidget(); lay = QVBoxLayout(tab); lay.setContentsMargins(32, 26, 32, 16); lay.setSpacing(14)
        head = QHBoxLayout(); texts = QVBoxLayout(); texts.setSpacing(4)
        t = QLabel('Моменты'); t.setObjectName('h1'); texts.addWidget(t)
        self.select_title = QLabel('Здесь появятся найденные моменты, если включён ручной выбор.'); self.select_title.setObjectName('muted'); texts.addWidget(self.select_title)
        head.addLayout(texts, 1)
        b = QPushButton('Выбрать все'); b.setObjectName('ghost'); b.clicked.connect(lambda: self._check_all(True)); head.addWidget(b, 0, Qt.AlignBottom)
        b = QPushButton('Снять все'); b.setObjectName('ghost'); b.clicked.connect(lambda: self._check_all(False)); head.addWidget(b, 0, Qt.AlignBottom)
        lay.addLayout(head)
        split = QSplitter(Qt.Horizontal); split.setHandleWidth(10)
        self.cand_list = QListWidget(); self.cand_list.setViewMode(QListWidget.IconMode); self.cand_list.setResizeMode(QListWidget.Adjust)
        self.cand_list.setMovement(QListWidget.Static); self.cand_list.setIconSize(QSize(150, 266)); self.cand_list.setGridSize(QSize(176, 350))
        self.cand_list.setWordWrap(True); self.cand_list.setSpacing(6); self.cand_list.setUniformItemSizes(True)
        self.cand_list.currentRowChanged.connect(self.show_candidate); self.cand_list.itemDoubleClicked.connect(self._toggle_item)
        self.cand_list.itemChanged.connect(lambda *_: (self._update_pick_count(), self._save_session_later()))
        self.cand_list.setMinimumWidth(190); split.addWidget(self.cand_list)
        right = QFrame(); right.setObjectName('card'); rh = QHBoxLayout(right); rh.setContentsMargins(14, 14, 14, 14); rh.setSpacing(12)
        self.select_preview = PreviewPane(self, speaker_option=True, hint='Выберите момент слева')
        pw = QWidget(); pv = QVBoxLayout(pw); pv.setContentsMargins(0, 0, 0, 0); pv.addWidget(self.select_preview)
        pw_area = self._scroll(pw); pw_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); pw_area.setFixedWidth(278)
        rh.addWidget(pw_area)
        self.cand_detail = QTextEdit(); self.cand_detail.setReadOnly(True)
        self.caption_editor = CaptionEditor(self)
        self.detail_tabs = QTabWidget(); self.detail_tabs.addTab(self.cand_detail, 'Описание'); self.detail_tabs.addTab(self.caption_editor, 'Субтитры')
        self.detail_tabs.setMinimumWidth(220); rh.addWidget(self.detail_tabs, 1)
        split.addWidget(right); split.setStretchFactor(0, 3); split.setStretchFactor(1, 4); split.setSizes([520, 700])
        lay.addWidget(split, 1)
        row = QHBoxLayout()
        self.pick_count = QLabel(''); self.pick_count.setObjectName('muted'); row.addWidget(self.pick_count); row.addStretch()
        self.skip_btn = QPushButton('Пропустить видео'); self.skip_btn.setObjectName('ghost'); self.skip_btn.setMinimumHeight(42); self.skip_btn.clicked.connect(self.skip_video); row.addWidget(self.skip_btn)
        self.render_btn = QPushButton('Смонтировать выбранные'); self.render_btn.setObjectName('primary'); self.render_btn.setMinimumHeight(42); self.render_btn.clicked.connect(self.render_selected); row.addWidget(self.render_btn)
        lay.addLayout(row); self._set_select_enabled(False)
        self.tabs.addTab(tab, 'Выбор моментов')

    def _build_results_tab(self):
        tab = QWidget(); lay = QVBoxLayout(tab); lay.setContentsMargins(32, 26, 32, 16); lay.setSpacing(14)
        head = QHBoxLayout(); texts = QVBoxLayout(); texts.setSpacing(4)
        t = QLabel('Результаты'); t.setObjectName('h1'); texts.addWidget(t)
        self.results_title = QLabel('Готовые ролики появятся здесь.'); self.results_title.setObjectName('muted'); texts.addWidget(self.results_title)
        head.addLayout(texts, 1)
        b = QPushButton('Очистить список'); b.setObjectName('ghost'); b.setToolTip('Убирает ролики из списка. Сами файлы остаются в папке.')
        b.clicked.connect(self.clear_results); head.addWidget(b, 0, Qt.AlignBottom)
        b = QPushButton('Открыть папку'); b.setObjectName('ghost'); b.clicked.connect(self.open_folder); head.addWidget(b, 0, Qt.AlignBottom)
        lay.addLayout(head)
        split = QSplitter(Qt.Horizontal); split.setHandleWidth(10)
        self.list = QListWidget(); self.list.setViewMode(QListWidget.IconMode); self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static); self.list.setIconSize(QSize(150, 266)); self.list.setGridSize(QSize(176, 350))
        self.list.setWordWrap(True); self.list.setSpacing(6); self.list.setUniformItemSizes(True)
        self.list.currentRowChanged.connect(self.show_result); self.list.itemDoubleClicked.connect(lambda _item: self.open_selected())
        split.addWidget(self.list)
        right = QFrame(); right.setObjectName('card'); rv = QVBoxLayout(right); rv.setContentsMargins(18, 16, 18, 16); rv.setSpacing(10)
        self.preview_title = QLabel('Выберите ролик'); self.preview_title.setObjectName('h2'); self.preview_title.setWordWrap(True); rv.addWidget(self.preview_title)
        row = QHBoxLayout(); row.setSpacing(8)
        for text, fn, icon, kind in (('Открыть', self.open_selected, 'play', 'primary'), ('Копировать описание', self.open_description, 'copy', 'soft'),
                                     ('.srt', self.open_srt, None, 'ghost'), ('Папка', self.open_folder, 'folder', 'ghost')):
            b = QPushButton(text); b.setObjectName(kind); b.clicked.connect(fn)
            if icon: b.setIcon(svg_icon(icon, '#FFFFFF' if kind != 'ghost' else '#D7DDE7', 14))
            row.addWidget(b)
        row.addStretch(); rv.addLayout(row)
        self.detail = QTextEdit(); self.detail.setReadOnly(True); rv.addWidget(self.detail, 1)
        split.addWidget(right); split.setStretchFactor(0, 3); split.setStretchFactor(1, 2); split.setSizes([700, 460])
        lay.addWidget(split, 1)
        self.tabs.addTab(tab, 'Результаты')

    def _build_settings_tab(self):
        tab, lay = self._page('Настройки', 'Все настройки сохраняются автоматически.')
        box = QGroupBox('Бесплатный локальный AI — без платных API'); form = QFormLayout(box)
        self.local_model = QComboBox(); self.local_model.setEditable(True); self.local_model.addItems(['qwen3:4b', 'qwen3:8b', 'qwen2.5:7b']); form.addRow('Локальная модель', self.local_model)
        self.ollama_url = QLineEdit('http://127.0.0.1:11434'); form.addRow('Адрес локального Ollama', self.ollama_url)
        lay.addWidget(box)
        info = QLabel('Рекомендация для RTX 4060 Laptop с 8 ГБ VRAM: qwen3:4b. Если Ollama недоступен, приложение переключается на встроенный офлайн-подбор, а описания делаются по шаблону.'); info.setWordWrap(True); info.setObjectName('muted'); lay.addWidget(info)
        updates = QGroupBox('Обновления'); uf = QFormLayout(updates)
        self.auto_update_box = Switch('Проверять обновления при запуске'); self.auto_update_box.setChecked(True); uf.addRow(self.auto_update_box)
        update_btn = QPushButton('Проверить обновления сейчас'); update_btn.clicked.connect(lambda: self.check_for_updates(manual=True)); uf.addRow(update_btn)
        self.github_owner = QLineEdit(DEFAULT_OWNER); self.github_repo = QLineEdit(DEFAULT_REPO)
        uf.addRow('GitHub owner', self.github_owner); uf.addRow('GitHub repository', self.github_repo)
        note = QLabel(f'Текущая версия: {APP_VERSION}. Обновление заменяет только файлы программы: настройки, библиотеки и готовые ролики сохраняются.')
        note.setWordWrap(True); note.setObjectName('muted'); uf.addRow(note)
        lay.addWidget(updates)
        if os.name == 'nt':
            sc = QGroupBox('Ярлык'); sl = QVBoxLayout(sc)
            b = QPushButton('Создать ярлык на рабочем столе и в меню «Пуск»'); b.clicked.connect(lambda: self.make_shortcut(ask=False)); sl.addWidget(b)
            lay.addWidget(sc)
        lay.addStretch(); self.tabs.addTab(self._scroll(tab), 'Настройки')

    # ------------------------------------------------------------------ settings
    def apply_preset(self, name: str):
        p = SUB_PRESETS.get(name)
        if not p: return
        self.sub_font.setCurrentFont(QFont(p['font'])); self.sub_size.setValue(int(p['size']))
        self.sub_pos.setCurrentText(p['position']); self.sub_upper.setChecked(bool(p['upper']))
        color = next((k for k, v in ACTIVE_COLORS.items() if v == p['active']), None)
        if color: self.sub_color.setCurrentText(color)

    def subtitle_style(self) -> dict:
        return {'preset': self.sub_preset.currentText(), 'font': self.sub_font.currentFont().family(), 'size': self.sub_size.value(),
                'position': self.sub_pos.currentText(), 'active': ACTIVE_COLORS[self.sub_color.currentText()], 'upper': self.sub_upper.isChecked(),
                'no_punct': self.sub_nopunct.isChecked()}

    def sync_preview_speaker(self, on: bool, origin):
        for pane in (getattr(self, 'design_preview', None), getattr(self, 'select_preview', None)):
            if pane is not None and pane is not origin and pane.speaker.isChecked() != on:
                pane.speaker.blockSignals(True); pane.speaker.setChecked(on); pane.speaker.blockSignals(False)

    def preview_settings(self) -> dict:
        return {'zoom': int(self.zoom.currentText().split('%')[0]) / 100,
                'background': 'black' if self.background.currentIndex() == 1 else 'blur',
                'style': self.subtitle_style(), 'speaker_frame': self.speaker_frame_key()}

    def speaker_frame_key(self) -> str:
        return ('full', '4:5', '1:1')[max(0, self.speaker_frame.currentIndex())]

    def _on_tab_changed(self, index: int):
        if index == 1: self._sync_design_preview()

    def _sync_design_preview(self):
        """Preview the first video in the list; use its saved transcript for real captions if there is one."""
        src = self.sources[0] if self.sources else ''
        if not src:
            self.design_preview.set_source(None); return
        if src == self.design_preview.source: self.design_preview.request(); return
        words = None
        try:
            out = Path(output_dir_for(self.out_edit.text().strip(), src))
            cache = next((p for p in (out / '.cloudy' / 'transcript_cache.json', out / 'transcript_cache.json') if p.exists()), out / 'x')
            if cache.exists(): words = json.loads(cache.read_text(encoding='utf-8')).get('words')
        except Exception:
            words = None
        self.design_preview.set_source(src, words=words)

    def collect_settings(self) -> dict:
        return {'whisper_model': self.whisper.currentText(), 'device': self.device.currentText(),
                'encoder': 'cpu' if self.encoder.currentIndex() == 1 else 'auto',
                'ollama_url': self.ollama_url.text().strip(), 'local_model': self.local_model.currentText().strip(),
                'zoom': int(self.zoom.currentText().split('%')[0]) / 100,
                'background': 'black' if self.background.currentIndex() == 1 else 'blur',
                'hook': self.hook.isChecked(), 'punch_ins': self.punch.isChecked(), 'srt': self.srt.isChecked(),
                'speaker_crop': self.speaker_crop.isChecked(), 'soft_follow': self.soft_follow.isChecked(),
                'scene_analysis': self.scene_analysis.isChecked(), 'speaker_frame': self.speaker_frame_key(),
                'fill_clips': self.fill_clips.currentIndex() == 0, 'save_txt': self.save_txt.isChecked(),
                'ai_descriptions': self.ai_desc.isChecked(), 'manual_pick': self.manual_pick.isChecked(),
                'subtitle_style': self.subtitle_style(),
                'music_files': list(self.music_files) if self.music_on.isChecked() else [],
                'music_volume': self.music_volume.value() / 100}

    def load_settings(self):
        p = Path.home() / '.cloudy_clip_studio.json'
        if not p.exists(): return
        try:
            d = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            return
        self.local_model.setCurrentText(d.get('local_model', 'qwen3:4b'))
        self.ollama_url.setText(d.get('ollama_url', 'http://127.0.0.1:11434'))
        self.github_owner.setText(d.get('github_owner') or DEFAULT_OWNER); self.github_repo.setText(d.get('github_repo') or DEFAULT_REPO)
        self.auto_update = d.get('auto_update', True); self.auto_update_box.setChecked(self.auto_update)
        self.skip_version = d.get('skip_version', ''); self.shortcut_offered = d.get('shortcut_offered', False)
        ui = d.get('ui', {})
        for key, widget in (('whisper', self.whisper), ('device', self.device), ('zoom', self.zoom)):
            if ui.get(key): widget.setCurrentText(ui[key])
        for key, widget in (('encoder', self.encoder), ('background', self.background), ('fill_clips', self.fill_clips),
                            ('speaker_frame', self.speaker_frame)):
            if isinstance(ui.get(key), int): widget.setCurrentIndex(ui[key])
        for key, widget in (('manual_pick', self.manual_pick), ('ai_desc', self.ai_desc), ('hook', self.hook),
                            ('punch', self.punch), ('srt', self.srt), ('speaker_crop', self.speaker_crop),
                            ('soft_follow', self.soft_follow), ('save_txt', self.save_txt), ('scene_analysis', self.scene_analysis)):
            if key in ui: widget.setChecked(bool(ui[key]))
        st = ui.get('subtitles') or {}
        if st.get('preset') in SUB_PRESETS: self.sub_preset.setCurrentText(st['preset'])
        if st.get('font'): self.sub_font.setCurrentFont(QFont(st['font']))
        if st.get('size'): self.sub_size.setValue(int(st['size']))
        if st.get('position') in SUB_POSITIONS: self.sub_pos.setCurrentText(st['position'])
        color = next((k for k, v in ACTIVE_COLORS.items() if v == st.get('active')), None)
        if color: self.sub_color.setCurrentText(color)
        if 'upper' in st: self.sub_upper.setChecked(bool(st['upper']))
        if 'no_punct' in st: self.sub_nopunct.setChecked(bool(st['no_punct']))
        if ui.get('out_dir'): self.out_edit.setText(ui['out_dir'])
        self.music_on.setChecked(bool(ui.get('music_on', False)))
        if isinstance(ui.get('music_volume'), int): self.music_volume.setValue(ui['music_volume'])
        self._set_music([f for f in ui.get('music_files') or [] if Path(f).exists()])
        if ui.get('banner') and Path(ui['banner']).exists():
            self.banner = ui['banner']
        if 'use_banner' in ui: self.use_banner.setChecked(bool(ui['use_banner']))
        self._sync_banner_field()
        if 'preview_speaker' in ui:
            for pane in (self.design_preview, self.select_preview):
                pane.speaker.blockSignals(True); pane.speaker.setChecked(bool(ui['preview_speaker'])); pane.speaker.blockSignals(False)

    def _wire_autosave(self):
        """Save ~0.6 s after any setting changes, so nothing is lost if the app is closed or crashes."""
        self._autosave = QTimer(self); self._autosave.setSingleShot(True)
        self._autosave.timeout.connect(lambda: self.save_settings(quiet=True))
        kick = lambda *_: None if self._loading else self._autosave.start(600)
        skip = {self.banner_edit}
        for w in self.findChildren(QFontComboBox): w.currentFontChanged.connect(kick)
        for w in self.findChildren(QComboBox):
            if not isinstance(w, QFontComboBox):
                w.currentIndexChanged.connect(kick)
                if w.isEditable(): w.currentTextChanged.connect(kick)
        for w in self.findChildren(QCheckBox): w.toggled.connect(kick)
        for w in self.findChildren(QSpinBox): w.valueChanged.connect(kick)
        self.music_volume.valueChanged.connect(kick)
        for w in self.findChildren(QLineEdit):
            if w not in skip and not w.isReadOnly() and not isinstance(w.parent(), (QComboBox, QSpinBox)):
                w.textChanged.connect(kick)

    def closeEvent(self, event):
        try: self.save_settings(quiet=True)
        except Exception: pass
        super().closeEvent(event)

    def save_settings(self, notify: bool = False, quiet: bool = False):
        d = {'use_local_ai': True, 'local_model': self.local_model.currentText().strip(), 'ollama_url': self.ollama_url.text().strip(),
             'github_owner': self.github_owner.text().strip(), 'github_repo': self.github_repo.text().strip(),
             'auto_update': self.auto_update_box.isChecked(), 'skip_version': self.skip_version,
             'shortcut_offered': self.shortcut_offered,
             'ui': {'whisper': self.whisper.currentText(), 'device': self.device.currentText(), 'zoom': self.zoom.currentText(),
                    'encoder': self.encoder.currentIndex(), 'background': self.background.currentIndex(),
                    'speaker_frame': self.speaker_frame.currentIndex(),
                    'fill_clips': self.fill_clips.currentIndex(), 'save_txt': self.save_txt.isChecked(),
                    'manual_pick': self.manual_pick.isChecked(), 'ai_desc': self.ai_desc.isChecked(), 'hook': self.hook.isChecked(),
                    'punch': self.punch.isChecked(), 'srt': self.srt.isChecked(), 'subtitles': self.subtitle_style(),
                    'speaker_crop': self.speaker_crop.isChecked(), 'soft_follow': self.soft_follow.isChecked(),
                    'scene_analysis': self.scene_analysis.isChecked(),
                    'preview_speaker': self.design_preview.speaker.isChecked(),
                    'out_dir': self.out_edit.text().strip(), 'banner': self.banner, 'use_banner': self.use_banner.isChecked(),
                    'music_on': self.music_on.isChecked(), 'music_files': self.music_files,
                    'music_volume': self.music_volume.value()}}
        # Write to a temp file and swap: a crash mid-write can never leave a broken settings file.
        target = Path.home() / '.cloudy_clip_studio.json'; tmp = target.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8'); os.replace(tmp, target)
        if notify: QMessageBox.information(self, 'Настройки', 'Сохранено. Облачные AI API отключены.')

    def check_for_updates(self, manual: bool = True):
        if getattr(self, '_update_thread', None) and self._update_thread.isRunning(): return
        self._update_manual = manual
        worker = UpdateCheckWorker(self.github_owner.text().strip(), self.github_repo.text().strip())
        thread = QThread(); worker.moveToThread(thread)
        thread.started.connect(worker.run); worker.found.connect(self._on_release); worker.failed.connect(self._on_release_error)
        worker.found.connect(thread.quit); worker.failed.connect(thread.quit)
        self._update_thread, self._update_worker = thread, worker
        thread.start()

    def _on_release_error(self, err: str):
        if self._update_manual: QMessageBox.warning(self, 'Обновления', err)

    def _on_release(self, release: dict):
        tag = release.get('tag', '')
        if not is_newer(tag):
            if self._update_manual: QMessageBox.information(self, 'Обновления', f'У вас последняя версия ({APP_VERSION}).')
            return
        if not self._update_manual and tag == self.skip_version: return
        box = QMessageBox(self); box.setWindowTitle('Доступно обновление'); box.setIcon(QMessageBox.Information)
        box.setText(f'Доступна версия {tag} (у вас {APP_VERSION}).')
        notes = release.get('body', '').strip()
        box.setInformativeText((notes[:1500] + ('…' if len(notes) > 1500 else '')) if notes else 'Обновить сейчас?')
        now = box.addButton('Обновить', QMessageBox.AcceptRole); box.addButton('Позже', QMessageBox.RejectRole)
        skip = box.addButton('Пропустить эту версию', QMessageBox.DestructiveRole)
        box.exec()
        if box.clickedButton() == skip:
            self.skip_version = tag; self.save_settings(); return
        if box.clickedButton() != now: return
        if self.cancel_btn.isEnabled():
            QMessageBox.information(self, 'Обновление', 'Сейчас идёт обработка. Обновление можно установить после неё: Настройки → «Проверить обновления сейчас».')
            return
        self._download_update(release)

    def _download_update(self, release: dict):
        self.save_settings()
        dlg = QProgressDialog('Скачиваю обновление…', None, 0, 100, self); dlg.setWindowTitle('Обновление')
        dlg.setWindowModality(Qt.WindowModal); dlg.setMinimumDuration(0); dlg.setAutoClose(False); dlg.setValue(0)
        self._update_dialog = dlg
        worker = UpdateDownloadWorker(release, Path(__file__).resolve().parents[1])
        thread = QThread(); worker.moveToThread(thread)
        thread.started.connect(worker.run); worker.progress.connect(self._on_update_progress)
        worker.done.connect(self._on_update_ready); worker.failed.connect(self._on_update_failed)
        worker.done.connect(thread.quit); worker.failed.connect(thread.quit)
        self._update_thread, self._update_worker = thread, worker
        thread.start()

    def _on_update_progress(self, done: int, total: int):
        if total: self._update_dialog.setValue(int(done * 100 / total))
        self._update_dialog.setLabelText(f'Скачиваю обновление… {done / 1e6:.1f} из {total / 1e6:.1f} МБ' if total else 'Скачиваю обновление…')

    def _on_update_failed(self, err: str):
        self._update_dialog.close(); QMessageBox.warning(self, 'Обновление не удалось', err)

    def _on_update_ready(self):
        self._update_dialog.close()
        # The helper waits for this process to exit, swaps the files and starts the new version.
        QApplication.quit()

    def _offer_shortcut(self):
        if os.name != 'nt' or self.shortcut_offered: return
        try:
            from .shortcuts import shortcut_exists
            if shortcut_exists(): return
        except Exception:
            return
        self.shortcut_offered = True; self.save_settings()
        if QMessageBox.question(self, 'Ярлык', 'Создать ярлык Cloudy Clip Studio на рабочем столе и в меню «Пуск»?\n'
                                'Программа будет запускаться без чёрного окна.') == QMessageBox.Yes:
            self.make_shortcut(ask=False)

    def make_shortcut(self, ask: bool = False):
        try:
            from .shortcuts import create_shortcuts
            made = create_shortcuts()
            QMessageBox.information(self, 'Ярлык', 'Готово:\n' + '\n'.join(str(p) for p in made))
        except Exception as e:
            QMessageBox.warning(self, 'Ярлык', f'Не удалось создать ярлык: {e}')

    # ------------------------------------------------------------------ files
    def add_sources(self, paths):
        added = 0
        for p in paths:
            if p.lower().endswith(VIDEO_EXT) and p not in self.sources:
                self.sources.append(p); self._add_source_card(p); added += 1
        if added and not self.cancel_btn.isEnabled():
            self.status.setText(f'Видео в списке: {len(self.sources)}. Нажмите «Начать обработку».')
        if added: self._sources_changed()
        return added

    def pick_sources(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Выберите видео', '', 'Видео (*.mp4 *.mov *.mkv *.avi *.webm)')
        self.add_sources(paths)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(VIDEO_EXT) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        if self.add_sources([u.toLocalFile() for u in e.mimeData().urls()]):
            self.tabs.setCurrentIndex(0)

    def _add_source_card(self, path: str):
        info, ok = '', True
        try:
            pr = probe(path); info = f"{_fmt(pr['duration'])} · {pr['width']}×{pr['height']}"
            out = Path(output_dir_for(self.out_edit.text().strip(), path))
            if (out / '.cloudy' / 'transcript_cache.json').exists(): info += ' · расшифровка сохранена'
            if pr['duration'] < 90: info += ' · короче 90 с'; ok = False
        except Exception:
            info, ok = 'не удалось прочитать файл', False
        card = SourceCard(path, info, 'Готово к обработке' if ok else 'Слишком короткое', ok)
        card.removed.connect(self._remove_source_path)
        item = QListWidgetItem(); item.setSizeHint(QSize(100, 78)); item.setData(Qt.UserRole, path)
        self.src_list.addItem(item); self.src_list.setItemWidget(item, card)
        self._fit_source_list()

    def _fit_source_list(self):
        n = self.src_list.count()
        self.src_list.setVisible(n > 0); self.src_list.setFixedHeight(min(n, 4) * 82 + 4)

    def _remove_source_path(self, path: str):
        for i in range(self.src_list.count()):
            if self.src_list.item(i).data(Qt.UserRole) == path:
                self.src_list.takeItem(i); break
        if path in self.sources: self.sources.remove(path)
        self._fit_source_list(); self._sources_changed()

    def _sources_changed(self):
        if self.tabs.currentIndex() == 1: self._sync_design_preview()

    def remove_source(self):
        row = self.src_list.currentRow()
        if row >= 0: self.sources.pop(row); self.src_list.takeItem(row)
        self._fit_source_list(); self._sources_changed()

    def clear_sources(self):
        self.sources.clear(); self.src_list.clear()
        self._fit_source_list(); self._sources_changed()

    def pick_banner(self):
        p, _ = QFileDialog.getOpenFileName(self, 'Выберите анимационный баннер', '', 'Видео/GIF (*.mp4 *.mov *.webm *.gif *.mkv)')
        if p:
            self.banner = p; self.use_banner.setChecked(True); self._sync_banner_field(); self.save_settings(quiet=True)

    def _sync_banner_field(self, *_):
        on = self.use_banner.isChecked()
        self.banner_edit.setText(self.banner if on else 'Без баннера — ролики без рекламной вставки')
        if not self._loading_flag(): self.save_settings(quiet=True)
        self.banner_edit.setEnabled(on)

    def _loading_flag(self) -> bool:
        return getattr(self, '_loading', True) or not hasattr(self, 'local_model')

    def active_banner(self) -> str:
        return self.banner if self.use_banner.isChecked() else ''

    def _set_music(self, files: list[str]):
        self.music_files = files
        if not files: self.music_label.setText('Музыка не выбрана')
        elif len(files) == 1: self.music_label.setText(Path(files[0]).name)
        else: self.music_label.setText(f'{len(files)} трека(ов): ' + ', '.join(Path(f).name for f in files[:3]) + ('…' if len(files) > 3 else ''))
        self.music_label.setToolTip('\n'.join(files))

    def pick_music(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Выберите музыку', str(Path(self.music_files[0]).parent) if self.music_files else '',
                                                'Музыка (*.mp3 *.wav *.m4a *.aac *.ogg *.flac *.opus *.wma);;Все файлы (*)')
        if not files: return
        good, bad = [], []
        for f in files:
            try: (good if probe(f)['has_audio'] else bad).append(f)
            except Exception: bad.append(f)
        if bad: QMessageBox.warning(self, 'Музыка', 'В этих файлах не найден звук:\n' + '\n'.join(Path(b).name for b in bad))
        if good:
            self._set_music(good); self.music_on.setChecked(True); self.save_settings(quiet=True)

    def clear_music(self):
        self._set_music([]); self.music_on.setChecked(False); self.save_settings(quiet=True)

    def pick_output(self):
        p = QFileDialog.getExistingDirectory(self, 'Папка для результатов', self.out_edit.text())
        if p: self.out_edit.setText(p)

    # ------------------------------------------------------------------ processing flow
    def start_processing(self):
        if not self.sources:
            QMessageBox.warning(self, 'Не хватает файлов', 'Добавьте хотя бы одно видео.'); return
        if self.use_banner.isChecked() and not (self.banner and Path(self.banner).exists()):
            QMessageBox.warning(self, 'Нет баннера', 'Выберите файл баннера в «Дополнительно» или нажмите там «Без баннера».'); return
        if not ffmpeg_available():
            QMessageBox.critical(self, 'Не найден FFmpeg', 'Установите FFmpeg и добавьте ffmpeg.exe и ffprobe.exe в PATH. Инструкция есть в README.'); return
        bad = []
        try:
            if self.active_banner() and probe(self.banner)['duration'] <= 0: raise RuntimeError('Не удалось прочитать длительность баннера.')
            for s in self.sources:
                if probe(s)['duration'] < 90: bad.append(Path(s).name)
        except Exception as e:
            QMessageBox.critical(self, 'Проверка файлов', str(e)); return
        if bad:
            QMessageBox.critical(self, 'Слишком короткие видео', 'Эти видео короче 90 секунд:\n' + '\n'.join(bad)); return
        self._render_only = False
        self._begin_run(list(self.sources))
        self._next_video()

    def _running(self) -> bool:
        btn = getattr(self, 'cancel_btn', None)
        return bool(btn and btn.isEnabled())

    def _begin_run(self, queue: list[str]):
        self.save_settings()
        self.run_settings = self.collect_settings()
        self.queue = queue; self.total_videos = max(1, len(queue)); self._cancelled = False
        self.run_results: list[dict] = []
        self.stepper.set_step(0)
        self.start_btn.setEnabled(False); self.cancel_btn.setEnabled(True)
        self._t_start = time.monotonic(); self._eta = -1.0
        _keep_awake(True)

    def _run(self, worker, on_finished, on_failed):
        # Keep Python references to threads/workers until they finish (GC would delete them mid-run).
        self._threads = [(t, w) for t, w in self._threads if t.isRunning()]
        thread = QThread(); worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.on_progress); worker.eta.connect(self.on_eta)
        worker.finished.connect(on_finished); worker.failed.connect(on_failed)
        worker.finished.connect(thread.quit); worker.failed.connect(thread.quit)
        self._threads.append((thread, worker)); self.worker = worker
        thread.start()

    def _next_video(self):
        if self._cancelled or not self.queue:
            self._finish_all(); return
        self.current_source = self.queue.pop(0)
        done = self.total_videos - len(self.queue)
        self.current_out = output_dir_for(self.out_edit.text().strip(), self.current_source)
        self.queue_label.setText(f'Видео {done} из {self.total_videos}: {Path(self.current_source).name}' if self.total_videos > 1
                                 else Path(self.current_source).name)
        self._eta = -1.0
        self.progress.setValue(0)
        self._run(AnalyzeWorker(self.current_source, self.active_banner(), self.current_out, self.run_settings), self.on_analyzed, self.on_failed)

    def on_analyzed(self, payload: dict):
        self.analysis = payload
        if self._cancelled: self._finish_all(); return
        if self.run_settings.get('manual_pick', True):
            self._fill_candidates(payload)
            self._save_session()
            self.tabs.setCurrentIndex(2); self._eta = -1.0
            self.status.setText('Отметьте моменты и нажмите «Смонтировать выбранные».')
            self._notify('Моменты найдены', f"{Path(payload['source']).name}: выберите, что монтировать.")
        else:
            self._start_render(payload['clips'])

    def _start_render(self, clips: list[dict]):
        if not clips: self._next_video(); return
        clips = sorted(clips, key=lambda c: float(c['start']))  # Clip_01, Clip_02… follow the episode in order
        p = self.analysis
        self._run(RenderWorker(p['source'], self.active_banner(), p['out_dir'], self.run_settings, clips, p['words'], p.get('scenes')),
                  self.on_rendered, self.on_failed)

    def on_rendered(self, results: list, msg: str):
        self.run_results.extend(results)
        fresh = {r['file'] for r in results}
        self.results = [r for r in self.results if r['file'] not in fresh] + list(results)
        for r in results: self._res_thumbs.pop(r['file'], None)
        self._refresh_results(select=results[0]['file'] if results else None)
        self._save_session()
        self._next_video()

    @staticmethod
    def _result_key(r: dict):
        # Grouped by source video, then in story order inside it.
        return (str(Path(r['file']).parent).lower(), float(r.get('start', 0)), r['file'])

    def _refresh_results(self, select: str | None = None):
        current = self._selected()
        keep = select or (current['file'] if current else None)
        self.results.sort(key=self._result_key)
        self.list.blockSignals(True); self.list.clear()
        jobs = []
        for r in self.results:
            title = r.get('title') or Path(r['file']).stem
            item = QListWidgetItem(f"{title}\n{Path(r['file']).parent.name} · {_fmt(r['start'])}–{_fmt(r['end'])}")
            pm = self._res_thumbs.get(r['file'])
            item.setIcon(QIcon(rounded(pm if pm is not None else placeholder_thumb(), badge=_fmt(r['banner']['duration']))))
            item.setToolTip(Path(r['file']).name)
            self.list.addItem(item)
            if pm is None:
                jobs.append({'key': 'res:' + r['file'], 'kind': 'frame', 'source': r['file'], 't': min(4.0, r['banner']['duration'] / 3)})
        self.list.blockSignals(False)
        self._start_thumbs(jobs)
        n = len(self.results)
        self.tabs.set_badge(3, str(n) if n else '')
        self.results_title.setText(f'Готово роликов: {n} · по порядку в серии · двойной щелчок — открыть' if n
                                   else 'Готовые ролики появятся здесь.')
        row = next((i for i, r in enumerate(self.results) if r['file'] == keep), 0 if n else -1)
        if row >= 0: self.list.setCurrentRow(row)
        else: self.preview_title.setText('Выберите ролик'); self.detail.clear()

    def clear_results(self):
        if not self.results: return
        if QMessageBox.question(self, 'Очистить список', 'Убрать все ролики из списка?\nСами файлы останутся в папке.') != QMessageBox.Yes:
            return
        self.results = []; self._res_thumbs.clear(); self._refresh_results(); self._save_session()

    def on_failed(self, error: str):
        name = Path(self.current_source).name if self.current_source else ''
        if self._cancelled: self._finish_all(); return
        QMessageBox.critical(self, 'Ошибка обработки', f'{name}\n\n{error}')
        self._next_video()

    def _finish_all(self):
        self.start_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        self._set_select_enabled(self.cand_list.count() > 0)  # saved moments can be montaged again later
        made = getattr(self, 'run_results', [])
        self.queue_label.setText(''); self.stepper.set_step(3 if not self._cancelled and made else -1)
        msg = 'Обработка остановлена' if self._cancelled else 'Обработка завершена'
        took = f' за {_human(time.monotonic() - self._t_start)}' if self._t_start else ''
        self.status.setText(f'{msg}{took}. Создано роликов: {len(made)}')
        self._t_start = None; self._eta = -1.0; self.eta_label.setText(''); self.setWindowTitle('Cloudy Clip Studio')
        _keep_awake(False)
        if not self._cancelled:
            self._notify('Готово', f'Создано роликов: {len(made)}{took}')
        self._save_session()
        if made:
            self.tabs.setCurrentIndex(3)
            row = next((i for i, r in enumerate(self.results) if r['file'] == made[0]['file']), 0)
            self.list.setCurrentRow(row)
        elif not self._cancelled and not getattr(self, '_render_only', False):
            QMessageBox.warning(self, 'Нет результатов', 'Не удалось создать нарезки. Проверьте длину видео и звук.')

    def cancel_processing(self):
        self._cancelled = True; self.queue.clear()
        if self.worker: self.worker.cancel()
        if self.render_btn.isEnabled() and not isinstance(self.worker, RenderWorker):  # waiting on the selection screen
            self._finish_all()
        self.status.setText('Запрошена остановка. Текущий ролик будет завершён.')

    def on_progress(self, p, msg):
        self.progress.setValue(p)
        self.stepper.set_step(0 if p < 38 else 1 if p <= 50 else 2)
        if msg: self.progress_label.setText(msg)
        self.setWindowTitle(f'{p}% — Cloudy Clip Studio')  # visible on the taskbar while minimised

    def on_eta(self, seconds: float):
        self._eta = seconds; self._eta_at = time.monotonic(); self._tick()

    def _tick(self):
        if self._t_start is None: return
        elapsed = _human(time.monotonic() - self._t_start)
        waiting = self.render_btn.isEnabled()
        if waiting:
            self.eta_label.setText(f'ждёт вашего выбора • прошло {elapsed}')
        elif self._eta >= 0:
            left = max(0.0, self._eta - (time.monotonic() - self._eta_at))
            more = f' (+ ещё видео: {len(self.queue)})' if self.queue else ''
            self.eta_label.setText(f'Осталось ≈ {_human(left)}{more} • прошло {elapsed}')
        else:
            self.eta_label.setText(f'Оцениваю время… • прошло {elapsed}')

    def _notify(self, title: str, text: str):
        QApplication.alert(self)  # flashes the taskbar button
        QApplication.beep()
        if self.tray:
            self.tray.show(); self.tray.showMessage(f'Cloudy Clip Studio — {title}', text, QSystemTrayIcon.Information, 8000)

    # ------------------------------------------------------------------ selection screen
    def _set_select_enabled(self, on: bool):
        self.render_btn.setEnabled(on); self.skip_btn.setEnabled(on)
        self.skip_btn.setText('Пропустить видео' if self._running() else 'Убрать моменты')

    def _fill_candidates(self, payload: dict, checked: list[bool] | None = None):
        self.cand_list.blockSignals(True)
        self.cand_list.clear()
        clips = sorted(payload['clips'], key=lambda c: c['start'])
        payload['clips'] = clips
        self.select_title.setText(f"{Path(payload['source']).name} · найдено моментов: {len(clips)}")
        jobs = []
        st = self.preview_settings()
        for n, c in enumerate(clips):
            title = c.get('title') or ('Добор' if str(c.get('reason', '')).startswith('Добор') else 'Без названия')
            dur = c['end'] - c['start']
            score = 'добор' if str(c.get('reason', '')).startswith('Добор') else f"{c.get('score', 0):.0f}/100"
            item = QListWidgetItem(f"{title}\n{_fmt(c['start'])} · {score}")
            item.setIcon(QIcon(rounded(placeholder_thumb(), badge=_fmt(dur))))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if checked is None or n >= len(checked) or checked[n] else Qt.Unchecked)
            item.setToolTip(c.get('reason') or '')
            self.cand_list.addItem(item)
            jobs.append({'key': f'cand:{n}', 'kind': 'clip', 'source': payload['source'], 't': c['start'] + min(8.0, dur / 3),
                         'words': payload['words'], 'zoom': st['zoom'], 'background': st['background'], 'style': st['style']})
        self.cand_list.blockSignals(False)
        self._start_thumbs(jobs)
        self.tabs.set_badge(2, str(len(clips)))
        self._set_select_enabled(True); self._update_pick_count()
        if clips: self.cand_list.setCurrentRow(0)

    def _update_pick_count(self):
        n = sum(1 for i in range(self.cand_list.count()) if self.cand_list.item(i).checkState() == Qt.Checked)
        total = self.cand_list.count()
        self.pick_count.setText(f'Отмечено {n} из {total}' if total else '')
        self.render_btn.setText(f'Смонтировать {n} ' + ('ролик' if n % 10 == 1 and n % 100 != 11 else 'ролика' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'роликов')
                                if total else 'Смонтировать выбранные')

    def _start_thumbs(self, jobs: list[dict]):
        if not jobs: return
        self._thumb_threads = [(t, w) for t, w in self._thumb_threads if t.isRunning()]
        worker = ThumbWorker(jobs); thread = QThread(); worker.moveToThread(thread)
        thread.started.connect(worker.run); worker.ready.connect(self._on_thumb); worker.done.connect(thread.quit)
        self._thumb_threads.append((thread, worker)); thread.start()

    def _on_thumb(self, key: str, path: str):
        kind, _, ref = key.partition(':')
        pm = QPixmap(path)
        if pm.isNull(): return
        if kind == 'cand':
            i = int(ref)
            if i >= self.cand_list.count(): return
            c = self.analysis['clips'][i] if self.analysis and i < len(self.analysis['clips']) else None
            self.cand_list.item(i).setIcon(QIcon(rounded(pm, badge=_fmt(c['end'] - c['start']) if c else '')))
        else:
            self._res_thumbs[ref] = pm
            i = next((n for n, r in enumerate(self.results) if r['file'] == ref), -1)
            if 0 <= i < self.list.count():
                self.list.item(i).setIcon(QIcon(rounded(pm, badge=_fmt(self.results[i]['banner']['duration']))))

    def show_candidate(self, row: int):
        if not self.analysis or row < 0 or row >= len(self.analysis['clips']): return
        c = self.analysis['clips'][row]
        self.select_preview.set_source(self.analysis['source'], c['start'], c['end'], self.analysis['words'])
        self.cand_detail.setPlainText(f"Отрезок исходника: {_fmt(c['start'])}–{_fmt(c['end'])}\nОценка: {c.get('score', 0):.0f}/100\n"
                                      f"Почему: {c.get('reason') or '—'}\nХук: {c.get('hook') or '—'}\n\nТекст:\n{c.get('transcript', '')}")
        self.caption_editor.set_clip(c)

    def _toggle_item(self, item):
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    def _check_all(self, on: bool):
        for i in range(self.cand_list.count()):
            self.cand_list.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def render_selected(self):
        if not self.analysis: return
        chosen = [c for i, c in enumerate(self.analysis['clips']) if self.cand_list.item(i).checkState() == Qt.Checked]
        if not chosen:
            QMessageBox.information(self, 'Ничего не выбрано', 'Отметьте хотя бы один момент или нажмите «Пропустить это видео».'); return
        self.caption_editor.apply() if self.caption_editor._apply_timer.isActive() else None
        self._save_edited_captions()
        self._render_only = not self._running()
        if self._render_only:  # moments restored after a restart: start a run just for them
            self._begin_run([])
            self.current_source = self.analysis['source']
            self.queue_label.setText(Path(self.current_source).name)
        self._set_select_enabled(False); self.tabs.setCurrentIndex(0)
        self._start_render(chosen)

    def _save_edited_captions(self):
        """Keep subtitle edits in the transcript cache, so re-processing this video keeps them."""
        if not getattr(self, 'captions_edited', False) or not self.analysis: return
        cache = data_dir_for(self.analysis['out_dir']) / 'transcript_cache.json'
        try:
            data = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
            data['words'] = self.analysis['words']; data['edited'] = True
            cache.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass
        self.captions_edited = False

    def skip_video(self):
        self._save_edited_captions()
        idle = not self._running()
        self._set_select_enabled(False); self.cand_list.clear(); self.tabs.set_badge(2, '')
        self.analysis = None; self.select_title.setText('Здесь появятся найденные моменты, если включён ручной выбор.')
        self.cand_detail.clear(); self.caption_editor.set_clip(None)
        self._save_session()
        if idle: return
        self.tabs.setCurrentIndex(0)
        self._next_video()

    # ------------------------------------------------------------------ session (moments + results survive a restart)
    SESSION = Path.home() / '.cloudy_clip_session.json'

    def _save_session_later(self):
        if not hasattr(self, '_session_timer'):
            self._session_timer = QTimer(self); self._session_timer.setSingleShot(True); self._session_timer.timeout.connect(self._save_session)
        self._session_timer.start(800)

    def _save_session(self):
        try:
            results = []
            for r in self.results:
                r = dict(r); sp = r.get('speaker_tracking') or {}
                r['speaker_tracking'] = {k: v for k, v in sp.items() if k != 'keyframes'}  # big and not needed later
                results.append(r)
            moments = None
            if self.analysis and self.cand_list.count():
                moments = {'source': self.analysis['source'], 'out_dir': self.analysis['out_dir'], 'clips': self.analysis['clips'],
                           'checked': [self.cand_list.item(i).checkState() == Qt.Checked for i in range(self.cand_list.count())]}
            tmp = self.SESSION.with_suffix('.json.tmp')
            tmp.write_text(json.dumps({'results': results, 'moments': moments}, ensure_ascii=False), encoding='utf-8')
            os.replace(tmp, self.SESSION)
        except Exception:
            pass

    def _load_session(self):
        try:
            data = json.loads(self.SESSION.read_text(encoding='utf-8')) if self.SESSION.exists() else {}
        except Exception:
            data = {}
        self.results = [r for r in data.get('results') or [] if r.get('file') and Path(r['file']).exists()]
        self._refresh_results()
        m = data.get('moments')
        if not m or not Path(m.get('source', '')).exists(): return
        try:
            cache = Path(m['out_dir']) / '.cloudy' / 'transcript_cache.json'
            words = json.loads(cache.read_text(encoding='utf-8')).get('words') or []
            scenes_file = Path(m['out_dir']) / '.cloudy' / 'scenes.json'
            scenes = json.loads(scenes_file.read_text(encoding='utf-8')) if scenes_file.exists() else None
        except Exception:
            return
        if not words: return
        self.analysis = {'source': m['source'], 'out_dir': m['out_dir'], 'words': words, 'transcript': '',
                         'clips': m['clips'], 'scenes': scenes}
        self._fill_candidates(self.analysis, m.get('checked'))

    # ------------------------------------------------------------------ results
    def show_result(self, row):
        if row < 0 or row >= len(self.results): return
        r = self.results[row]
        self.preview_title.setText(r.get('title') or Path(r['file']).name)
        speaker = r.get('speaker_tracking', {}); scan = r.get('quality_scan', {}); b = r['banner']
        warnings = r.get('quality_warnings', [])
        desc = r.get('description') or (Path(r['description_file']).read_text(encoding='utf-8')
                                        if r.get('description_file') and Path(r['description_file']).exists() else '')
        self.detail.setPlainText(
            f"Файл: {r['file']}\nИсходный отрезок: {_fmt(r['start'])}–{_fmt(r['end'])}\nДлительность: {b['duration']:.1f} с\n"
            f"Оценка: {r['score']:.0f}/100\nПочему выбран: {r['reason'] or '—'}\n"
            f"Хук в начале: {str(b.get('hook_seconds', 0)) + ' с' if b.get('hook_seconds') else 'нет'} ({r.get('hook') or '—'})\n"
            f"Приближения: {len(b.get('punch_ins', []))}\n"
            f"Баннеров: {(str(b['banner_count']) + ' (на ' + str(b['banner_positions']) + ' с)') if b['banner_count'] else 'без баннера'}\n"
            f"Кадрирование: {speaker.get('reason', 'не запускалось')}\nМузыка: {b.get('music') or 'нет'}\nКодирование: {b.get('encoder', '—')}\n"
            f"Проверка качества: {'выполнена' if scan.get('scan_completed') else 'не завершена'}\n"
            f"Предупреждения: {', '.join(warnings) or 'нет'}\n\nОписание:\n{desc}")

    def _selected(self):
        row = self.list.currentRow()
        return self.results[row] if 0 <= row < len(self.results) else None

    def open_selected(self):
        r = self._selected()
        if r: QDesktopServices.openUrl(QUrl.fromLocalFile(r['file']))

    def open_description(self):
        r = self._selected()
        if not r: return
        text = r.get('description') or (Path(r['description_file']).read_text(encoding='utf-8') if r.get('description_file') else '')
        QApplication.clipboard().setText(text)
        self.status.setText('Описание скопировано — вставьте его на площадку (Ctrl+V).')

    def open_srt(self):
        r = self._selected()
        if r and r.get('srt_file'): QDesktopServices.openUrl(QUrl.fromLocalFile(r['srt_file']))

    def open_folder(self):
        r = self._selected()
        folder = str(Path(r['file']).parent) if r else self.out_edit.text().strip()
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


def main():
    app = QApplication([]); apply_theme(app); w = MainWindow()
    screen = app.primaryScreen().availableGeometry()
    if screen.height() < 900 or screen.width() < 1300: w.showMaximized()  # laptop screens
    else: w.show()
    app.exec()
