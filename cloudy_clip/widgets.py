"""Building blocks of the 1.11 interface: icons, switch, sidebar navigation, drop zone, cards, stepper."""
from __future__ import annotations
import os, tempfile
from pathlib import Path
from PySide6.QtCore import QRect, Qt, QSize, QRectF, Signal, QObject, Slot, QByteArray, QPoint
from PySide6.QtGui import QPainter, QColor, QPixmap, QIcon, QPen, QFont
from PySide6.QtWidgets import (QWidget, QCheckBox, QPushButton, QLabel, QHBoxLayout, QVBoxLayout, QFrame,
                               QStackedWidget, QButtonGroup, QComboBox, QSizePolicy)

ACCENT = '#6E5CF0'
BG, PANEL, CARD, LINE = '#0E1116', '#12161D', '#161B23', '#222935'
TEXT, MUTED = '#E8ECF2', '#93A0B4'

ICONS = {
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'palette': '<circle cx="13.5" cy="6.5" r="2.5"/><path d="M3 21l6-6 4 4 8-8"/>',
    'grid': '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/>'
            '<rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    'phone': '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M10 9l5 3-5 3z"/>',
    'gear': '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    'cloud': '<path d="M17.5 19a4.5 4.5 0 0 0 0-9 6 6 0 0 0-11.6 1.5A3.75 3.75 0 0 0 6.5 19z"/>',
    'upload': '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/>',
    'film': '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 9l5 3-5 3z"/>',
    'x': '<path d="M18 6L6 18M6 6l12 12"/>',
    'check': '<path d="M5 12l5 5L20 7"/>',
    'folder': '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    'chevron': '<path d="M9 6l6 6-6 6"/>',
    'play': '<path d="M7 4l13 8-13 8z"/>',
    'copy': '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
    'sparkle': '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
}


def svg_icon(name: str, color: str = TEXT, size: int = 18, width: float = 2.0) -> QIcon:
    """Crisp stroke icon from the built-in set (no image files needed)."""
    from PySide6.QtSvg import QSvgRenderer
    body = ICONS.get(name, '')
    fill = color if name == 'play' else 'none'
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{fill}" stroke="{color}" '
           f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    icon = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale); pm.fill(Qt.transparent)
        p = QPainter(pm); QSvgRenderer(QByteArray(svg.encode())).render(p); p.end()
        pm.setDevicePixelRatio(scale); icon.addPixmap(pm)
    return icon


class Switch(QCheckBox):
    """A drop-in QCheckBox drawn as an iOS-style switch (same isChecked/toggled API)."""

    def __init__(self, text: str = '', parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor); self.setMinimumHeight(32)
        sp = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred); sp.setHeightForWidth(True); self.setSizePolicy(sp)

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(46 + 12 + fm.horizontalAdvance(self.text()), max(32, fm.height() + 8))

    def minimumSizeHint(self):
        # Long captions wrap onto several lines instead of forcing the page to scroll sideways.
        return QSize(46 + 12 + min(160, self.fontMetrics().horizontalAdvance(self.text())), 32)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        fm = self.fontMetrics()
        r = fm.boundingRect(QRect(0, 0, max(40, width - 54), 10000), Qt.TextWordWrap, self.text())
        return max(32, r.height() + 8)

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        h = 24; w = 42; y = (self.height() - h) / 2
        on = self.isChecked()
        track = QColor(ACCENT if on else '#2C3442')
        if not self.isEnabled(): track.setAlpha(110)
        p.setPen(Qt.NoPen); p.setBrush(track); p.drawRoundedRect(QRectF(0, y, w, h), h / 2, h / 2)
        p.setBrush(QColor('#FFFFFF')); knob = h - 6
        p.drawEllipse(QRectF((w - knob - 3) if on else 3, y + 3, knob, knob))
        if self.hasFocus():
            p.setPen(QPen(QColor('#A99CFF'), 1.5)); p.setBrush(Qt.NoBrush); p.drawRoundedRect(QRectF(-1, y - 1, w + 2, h + 2), h / 2 + 1, h / 2 + 1)
        p.setPen(QColor(TEXT if self.isEnabled() else MUTED))
        p.drawText(QRectF(w + 12, 0, self.width() - w - 12, self.height()), Qt.AlignVCenter | Qt.TextWordWrap, self.text())
        p.end()


class NavStack(QStackedWidget):
    """Pages + a left sidebar. Keeps the old QTabWidget calls (addTab, setCurrentIndex, currentChanged)."""

    def __init__(self, items: list[tuple[str, str]]):
        super().__init__()
        self._items = items; self.buttons: list[QPushButton] = []; self.badges: dict[int, QLabel] = {}
        self.sidebar = QFrame(); self.sidebar.setObjectName('sidebar'); self.sidebar.setFixedWidth(232)
        v = QVBoxLayout(self.sidebar); v.setContentsMargins(16, 22, 16, 18); v.setSpacing(4)
        logo = QHBoxLayout(); logo.setSpacing(10)
        mark = QLabel(); mark.setFixedSize(36, 36); mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet(f'background:{ACCENT};border-radius:10px;'); mark.setPixmap(svg_icon('cloud', '#FFFFFF', 20).pixmap(20, 20))
        names = QVBoxLayout(); names.setSpacing(0)
        a = QLabel('Cloudy Clip'); a.setStyleSheet('font-weight:700;font-size:11pt;')
        b = QLabel('Studio'); b.setObjectName('muted')
        names.addWidget(a); names.addWidget(b); logo.addWidget(mark); logo.addLayout(names); logo.addStretch()
        v.addLayout(logo); v.addSpacing(22)
        self.group = QButtonGroup(self); self.group.setExclusive(True)
        for i, (title, icon) in enumerate(items):
            btn = QPushButton(title); btn.setObjectName('nav'); btn.setCheckable(True); btn.setCursor(Qt.PointingHandCursor)
            btn.setIcon(svg_icon(icon, '#B4BFCF')); btn.setIconSize(QSize(18, 18)); btn.setMinimumHeight(42)
            lay = QHBoxLayout(btn); lay.setContentsMargins(0, 0, 10, 0); lay.addStretch()
            badge = QLabel(''); badge.setObjectName('badge'); badge.hide(); lay.addWidget(badge)
            self.badges[i] = badge
            btn.clicked.connect(lambda _=False, i=i: self.setCurrentIndex(i))
            self.group.addButton(btn, i); self.buttons.append(btn); v.addWidget(btn)
        v.addStretch()
        self.footer = QFrame(); self.footer.setObjectName('sidefoot'); fv = QVBoxLayout(self.footer); fv.setContentsMargins(12, 10, 12, 10); fv.setSpacing(4)
        self.gpu_line = QLabel(''); self.gpu_line.setWordWrap(True); self.version_line = QLabel(''); self.version_line.setObjectName('muted')
        fv.addWidget(self.gpu_line); fv.addWidget(self.version_line); v.addWidget(self.footer)
        self.currentChanged.connect(self._sync)

    def addTab(self, widget: QWidget, _title: str = '') -> int:
        idx = self.addWidget(widget); self._sync(self.currentIndex()); return idx

    def _sync(self, index: int):
        for i, b in enumerate(self.buttons):
            b.setChecked(i == index); b.setIcon(svg_icon(self._items[i][1], '#FFFFFF' if i == index else '#B4BFCF'))

    def set_badge(self, index: int, text: str):
        b = self.badges.get(index)
        if b is None: return
        b.setText(text); b.setVisible(bool(text))


class DropZone(QFrame):
    clicked = Signal()

    def __init__(self):
        super().__init__(); self.setObjectName('dropzone'); self.setCursor(Qt.PointingHandCursor)
        v = QVBoxLayout(self); v.setContentsMargins(24, 28, 24, 28); v.setSpacing(10); v.setAlignment(Qt.AlignCenter)
        ic = QLabel(); ic.setFixedSize(52, 52); ic.setAlignment(Qt.AlignCenter); ic.setStyleSheet('background:#1E2430;border-radius:14px;')
        ic.setPixmap(svg_icon('upload', '#A99CFF', 26).pixmap(26, 26))
        t = QLabel('Перетащите видео сюда'); t.setStyleSheet('font-size:13pt;font-weight:600;'); t.setAlignment(Qt.AlignCenter)
        s = QLabel('MP4, MOV, MKV, AVI, WEBM · можно несколько — обработаются по очереди'); s.setObjectName('muted'); s.setAlignment(Qt.AlignCenter); s.setWordWrap(True)
        self.button = QPushButton('Выбрать файлы'); self.button.setObjectName('soft'); self.button.clicked.connect(self.clicked)
        for w in (ic, t, s): v.addWidget(w, 0, Qt.AlignHCenter)
        v.addWidget(self.button, 0, Qt.AlignHCenter)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self.clicked.emit()
        super().mousePressEvent(e)


class SourceCard(QFrame):
    removed = Signal(str)

    def __init__(self, path: str, info: str, status: str = 'Готово к обработке', ok: bool = True):
        super().__init__(); self.path = path; self.setObjectName('card')
        h = QHBoxLayout(self); h.setContentsMargins(12, 10, 12, 10); h.setSpacing(14)
        thumb = QLabel(); thumb.setFixedSize(96, 54); thumb.setAlignment(Qt.AlignCenter); thumb.setStyleSheet('background:#232A36;border-radius:8px;')
        thumb.setPixmap(svg_icon('film', '#7D899C', 22).pixmap(22, 22)); self.thumb = thumb
        text = QVBoxLayout(); text.setSpacing(3)
        name = QLabel(Path(path).name); name.setStyleSheet('font-weight:600;')
        sub = QLabel(info); sub.setObjectName('muted')
        text.addWidget(name); text.addWidget(sub)
        self.chip = QLabel(status); self.chip.setObjectName('chipok' if ok else 'chip')
        x = QPushButton(); x.setObjectName('icon'); x.setIcon(svg_icon('x', MUTED)); x.setFixedSize(34, 34); x.setToolTip('Убрать из очереди')
        x.setAccessibleName('Убрать из очереди'); x.clicked.connect(lambda: self.removed.emit(self.path))
        h.addWidget(thumb); h.addLayout(text, 1); h.addWidget(self.chip); h.addWidget(x)


class Stepper(QWidget):
    """Распознавание → Моменты → Монтаж with the current step highlighted."""
    STEPS = ('Распознавание', 'Моменты', 'Монтаж')

    def __init__(self):
        super().__init__(); h = QHBoxLayout(self); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(8)
        self.dots, self.labels = [], []
        for i, name in enumerate(self.STEPS):
            dot = QLabel(str(i + 1)); dot.setFixedSize(22, 22); dot.setAlignment(Qt.AlignCenter)
            lab = QLabel(name); self.dots.append(dot); self.labels.append(lab)
            h.addWidget(dot); h.addWidget(lab)
            if i < len(self.STEPS) - 1:
                line = QFrame(); line.setFixedSize(22, 1); line.setStyleSheet('background:#313A4A;'); h.addWidget(line)
        self.set_step(-1)

    def set_step(self, current: int):
        for i, (d, l) in enumerate(zip(self.dots, self.labels)):
            if current < 0:
                d.setText(str(i + 1)); d.setStyleSheet('border:1px solid #3A4456;border-radius:11px;color:#93A0B4;font-size:8pt;')
                l.setStyleSheet('color:#93A0B4;')
            elif i < current:
                d.setText('✓'); d.setStyleSheet('background:#1C3A31;border-radius:11px;color:#7FE3C3;font-weight:700;font-size:8pt;')
                l.setStyleSheet('color:#7FE3C3;')
            elif i == current:
                d.setText(str(i + 1)); d.setStyleSheet(f'background:{ACCENT};border-radius:11px;color:#FFFFFF;font-weight:700;font-size:8pt;')
                l.setStyleSheet('color:#FFFFFF;font-weight:600;')
            else:
                d.setText(str(i + 1)); d.setStyleSheet('border:1px solid #3A4456;border-radius:11px;color:#93A0B4;font-size:8pt;')
                l.setStyleSheet('color:#93A0B4;')


class Segmented(QFrame):
    """Two-or-more option pill switch bound to a (hidden) QComboBox, so settings code stays the same."""

    def __init__(self, combo: QComboBox, labels: list[str]):
        super().__init__(); self.setObjectName('segmented'); self.combo = combo
        h = QHBoxLayout(self); h.setContentsMargins(4, 4, 4, 4); h.setSpacing(4)
        self.group = QButtonGroup(self); self.group.setExclusive(True)
        for i, text in enumerate(labels):
            b = QPushButton(text); b.setObjectName('seg'); b.setCheckable(True); b.setCursor(Qt.PointingHandCursor); b.setMinimumHeight(36)
            self.group.addButton(b, i); h.addWidget(b, 1)
        self.group.idClicked.connect(combo.setCurrentIndex)
        combo.currentIndexChanged.connect(self._sync); self._sync(combo.currentIndex())

    def _sync(self, i: int):
        b = self.group.button(i)
        if b: b.setChecked(True)


def placeholder_thumb(w: int = 150, h: int = 266, text: str = '') -> QPixmap:
    pm = QPixmap(w, h); pm.fill(QColor('#1E2430'))
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    icon = svg_icon('film', '#5E6A7E', 34).pixmap(34, 34); p.drawPixmap((w - 34) // 2, (h - 34) // 2 - (10 if text else 0), icon)
    if text:
        p.setPen(QColor(MUTED)); f = QFont(); f.setPointSize(8); p.setFont(f)
        p.drawText(QRectF(6, h / 2 + 14, w - 12, 30), Qt.AlignCenter, text)
    p.end(); return pm


def rounded(pm: QPixmap, w: int = 150, h: int = 266, radius: int = 10, badge: str = '') -> QPixmap:
    """Scale/crop to w×h with rounded corners and an optional duration badge."""
    src = pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(w, h); out.fill(Qt.transparent)
    p = QPainter(out); p.setRenderHint(QPainter.Antialiasing)
    from PySide6.QtGui import QPainterPath
    path = QPainterPath(); path.addRoundedRect(QRectF(0, 0, w, h), radius, radius); p.setClipPath(path)
    p.drawPixmap(-(src.width() - w) // 2, -(src.height() - h) // 2, src)
    if badge:
        f = QFont(); f.setPointSize(8); f.setBold(True); p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(badge) + 12
        p.setPen(Qt.NoPen); p.setBrush(QColor(10, 12, 16, 200)); p.drawRoundedRect(QRectF(w - tw - 6, h - 26, tw, 20), 6, 6)
        p.setPen(QColor('#FFFFFF')); p.drawText(QRectF(w - tw - 6, h - 26, tw, 20), Qt.AlignCenter, badge)
    p.end(); return out


class ThumbWorker(QObject):
    """Makes thumbnails in the background. jobs: dicts with key, kind ('clip'|'frame'), source, t, and preview settings."""
    ready = Signal(str, str)     # key, png path
    done = Signal()

    def __init__(self, jobs: list[dict]):
        super().__init__(); self.jobs = jobs; self._stop = False
        self.dir = tempfile.mkdtemp(prefix='cloudy_thumbs_')

    def stop(self): self._stop = True

    @Slot()
    def run(self):
        from .media import render_preview_frame, run, ffmpeg_path
        for n, j in enumerate(self.jobs):
            if self._stop: break
            out = os.path.join(self.dir, f'thumb_{n}.png')
            try:
                if j['kind'] == 'clip':
                    render_preview_frame(j['source'], j['t'], out, words=j.get('words'), zoom=j.get('zoom', 1.3),
                                         background=j.get('background', 'blur'), subtitle_style=j.get('style'), info=j.get('info'))
                else:
                    run([ffmpeg_path(), '-y', '-ss', f"{j['t']:.2f}", '-i', j['source'], '-frames:v', '1', '-vf', 'scale=300:-2', out])
                self.ready.emit(j['key'], out)
            except Exception:
                pass
        self.done.emit()
