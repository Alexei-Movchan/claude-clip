"""The «AI-улучшение» page: install the engines, choose settings, compare a frame before/after."""
from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from . import enhance as E
from .media import Cancelled, probe, ffmpeg_path, NO_WINDOW
from .widgets import Segmented, Switch

MODE_NOTES = {
    0: 'Быстро — лёгкая модель realesr-animevideov3 (×2). Самая быстрая; на живом видео картинка чуть «рисованная».',
    1: 'Баланс — realesr-general-x4v3, модель для обычного видео. Чётче и чище без «пластика». Рекомендуется.',
    2: 'Максимум — realesrgan-x4plus. Самая сильная, но в несколько раз медленнее; лица иногда выглядят слишком гладкими.',
}
RES_NOTES = ('Оригинал — размер не меняется, AI только чистит и делает чётче.',
             '720p — для слабых видеокарт.',
             '1080p — хороший выбор для 720p-сериалов.',
             '1440p — заметно лучше в кадре «по говорящему», где из видео вырезается узкая полоса, но медленнее.')
MODE_KEYS = ('fast', 'balanced', 'best')
RES_KEYS = ('original', '720p', '1080p', '1440p')


class InstallWorker(QObject):
    progress = Signal(float, str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, component: str):
        super().__init__(); self.component = component; self._cancel = False

    def cancel(self): self._cancel = True

    @Slot()
    def run(self):
        try:
            E.install(self.component, lambda f, t: self.progress.emit(f, t), lambda: self._cancel)
            E.list_devices(self.component)
            self.done.emit(self.component)
        except Cancelled:
            self.failed.emit('Установка отменена.')
        except Exception as e:
            self.failed.emit(str(e)[:600])


class CompareWorker(QObject):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, source: str, t: float, opts: dict, workdir: str):
        super().__init__(); self.source, self.t, self.opts, self.dir = source, t, opts, workdir

    @Slot()
    def run(self):
        try:
            import subprocess
            src = os.path.join(self.dir, 'before_src.png')
            p = subprocess.run([ffmpeg_path(), '-v', 'error', '-y', '-ss', f'{self.t:.3f}', '-i', self.source, '-frames:v', '1', src],
                               capture_output=True, text=True, **NO_WINDOW)
            if p.returncode != 0 or not os.path.exists(src): raise RuntimeError('Не удалось взять кадр из видео.')
            after = os.path.join(self.dir, 'after.png')
            r = E.enhance_image(src, after, self.opts)
            before = os.path.join(self.dir, 'before.png')   # same size as «after», plain resize: a fair comparison
            w, h = r['out_size']
            subprocess.run([ffmpeg_path(), '-v', 'error', '-y', '-i', src, '-vf', f'scale={w}:{h}:flags=lanczos', before],
                           capture_output=True, **NO_WINDOW)
            r.update(before=before, after=after, fps=E._fps(probe(self.source)))
            self.done.emit(r)
        except Exception as e:
            self.failed.emit(str(e)[:600])


class AiPage(QWidget):
    changed = Signal()

    def __init__(self, window):
        super().__init__()
        self.w = window
        self._threads: list = []
        self._install_worker = None
        self._tmp = tempfile.mkdtemp(prefix='cloudy_cmp_')
        self._cmp: dict | None = None
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(16)

        # ---- components
        comp = QGroupBox('Компоненты'); cf = QVBoxLayout(comp); cf.setSpacing(10)
        self.rows = {}
        for key in ('esrgan', 'rife'):
            row = QHBoxLayout(); row.setSpacing(10)
            text = QLabel(); text.setWordWrap(True); text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            btn = QPushButton(); btn.setObjectName('soft' if key == 'esrgan' else 'ghost')
            btn.clicked.connect(lambda _=False, k=key: self.install(k))
            row.addWidget(text, 1); row.addWidget(btn)
            cf.addLayout(row)
            self.rows[key] = (text, btn)
        self.bar = QProgressBar(); self.bar.setRange(0, 1000); self.bar.hide(); cf.addWidget(self.bar)
        brow = QHBoxLayout()
        self.bar_text = QLabel(''); self.bar_text.setObjectName('muted'); self.bar_text.hide(); brow.addWidget(self.bar_text, 1)
        self.cancel_install = QPushButton('Отменить'); self.cancel_install.setObjectName('ghost'); self.cancel_install.hide()
        self.cancel_install.clicked.connect(lambda: self._install_worker and self._install_worker.cancel()); brow.addWidget(self.cancel_install)
        cf.addLayout(brow)
        drow = QHBoxLayout()
        drow.addWidget(QLabel('Устройство'))
        self.device = QComboBox(); self.device.addItem('Авто', None); self.device.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        drow.addWidget(self.device, 1); cf.addLayout(drow)
        where = QLabel(f'Файлы AI лежат отдельно от программы: {E.ai_dir()}. Обновление программы их не трогает. '
                       'Скачиваются только по кнопке, из официальных релизов на GitHub, каждый файл проверяется по контрольной сумме.')
        where.setWordWrap(True); where.setObjectName('muted'); cf.addWidget(where)
        lay.addWidget(comp)

        # ---- settings
        box = QGroupBox('Настройки'); f = QFormLayout(box); f.setSpacing(10)
        self.on = Switch('AI-улучшение роликов'); f.addRow(self.on)
        on_note = QLabel('AI улучшает кусок исходного видео, из которого делается ролик, а субтитры, баннер и музыка '
                         'накладываются уже на улучшенную картинку. Выключено — всё работает как раньше.')
        on_note.setWordWrap(True); on_note.setObjectName('muted'); f.addRow(on_note)
        self.mode = QComboBox(self); self.mode.addItems(['Быстро', 'Баланс', 'Максимум']); self.mode.setCurrentIndex(1); self.mode.hide()
        f.addRow('Режим', Segmented(self.mode, ['Быстро', 'Баланс', 'Максимум']))
        self.mode_note = QLabel(MODE_NOTES[1]); self.mode_note.setWordWrap(True); self.mode_note.setObjectName('muted'); f.addRow(self.mode_note)
        self.res = QComboBox(self); self.res.addItems(['Оригинал', '720p', '1080p', '1440p']); self.res.setCurrentIndex(2); self.res.hide()
        f.addRow('Разрешение', Segmented(self.res, ['Оригинал', '720p', '1080p', '1440p']))
        self.res_note = QLabel(RES_NOTES[2]); self.res_note.setWordWrap(True); self.res_note.setObjectName('muted'); f.addRow(self.res_note)
        self.denoise = Switch('Убирать шум и артефакты сжатия'); self.denoise.setChecked(True); f.addRow(self.denoise)
        self.denoise_note = QLabel(''); self.denoise_note.setWordWrap(True); self.denoise_note.setObjectName('muted'); f.addRow(self.denoise_note)
        self.sharpen = Switch('Дополнительная резкость'); f.addRow(self.sharpen)
        sh = QLabel('Мягкий фильтр резкости FFmpeg (CAS), не нейросеть. Включайте, если после AI картинка кажется мягкой.')
        sh.setWordWrap(True); sh.setObjectName('muted'); f.addRow(sh)
        self.interp = Switch('Плавность 60 кадров/с (RIFE, экспериментально)'); f.addRow(self.interp)
        ip = QLabel('Дорисовывает промежуточные кадры: 30 → 60 кадров/с. На смене сцены кадр не дорисовывается. '
                    'В очень быстром действии возможны «размазанные» кадры. Требует компонент RIFE.')
        ip.setWordWrap(True); ip.setObjectName('muted'); f.addRow(ip)
        face = QLabel('Улучшение лиц не добавлено: бесплатная модель GFPGAN заметно меняет внешность и даёт «плавающие» лица на видео, '
                      'а CodeFormer запрещён для коммерческого использования. Real-ESRGAN делает лица чётче без перерисовки.')
        face.setWordWrap(True); face.setObjectName('muted'); f.addRow(face)
        lay.addWidget(box)

        # ---- compare
        cmp = QGroupBox('Сравнение до / после'); cv = QVBoxLayout(cmp); cv.setSpacing(10)
        top = QHBoxLayout()
        self.cmp_btn = QPushButton('Проверить на кадре из видео'); self.cmp_btn.setObjectName('soft'); self.cmp_btn.clicked.connect(self.compare)
        top.addWidget(self.cmp_btn)
        self.view = QComboBox(self); self.view.addItems(['До', 'После']); self.view.setCurrentIndex(1); self.view.hide()
        self.view_seg = Segmented(self.view, ['До', 'После']); self.view_seg.setEnabled(False); top.addWidget(self.view_seg); top.addStretch()
        cv.addLayout(top)
        self.cmp_info = QLabel('Берётся кадр из первого видео в проекте (место выбирается ползунком превью на вкладке «Оформление»). '
                               'Заодно замеряется скорость на вашей видеокарте.')
        self.cmp_info.setWordWrap(True); self.cmp_info.setObjectName('muted'); cv.addWidget(self.cmp_info)
        self.cmp_img = QLabel(); self.cmp_img.setAlignment(Qt.AlignCenter); self.cmp_img.setMinimumHeight(80)
        self.cmp_img.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred); cv.addWidget(self.cmp_img)
        lay.addWidget(cmp)
        lay.addStretch()

        self.mode.currentIndexChanged.connect(self._sync); self.res.currentIndexChanged.connect(self._sync)
        self.on.toggled.connect(self._sync); self.interp.toggled.connect(self._sync)
        self.view.currentIndexChanged.connect(self._show_cmp)
        self.refresh()

    # ------------------------------------------------------------------ state
    def refresh(self):
        for key, (text, btn) in self.rows.items():
            ok = E.installed(key)
            mb = E.DOWNLOAD_MB[key]
            text.setText(f"{'✓' if ok else '○'}  {E.COMPONENT_TITLES[key]} — "
                         + ('установлено' if ok else f'не установлено, загрузка ~{mb} МБ'))
            btn.setText('Переустановить' if ok else ('Установить AI' if key == 'esrgan' else 'Установить плавность'))
        cur = self.device.currentData()
        self.device.blockSignals(True); self.device.clear(); self.device.addItem('Авто — лучшая видеокарта', None)
        if E.installed('esrgan'):
            best = E.auto_device()
            for idx, name in E.list_devices():
                kind = E.device_kind(name)
                label = f'{name}' + (' — программно на процессоре, очень медленно' if kind == 'cpu' else '')
                self.device.addItem(label, idx)
            if best:
                self.device.setItemText(0, f'Авто — {best[1]}')
            elif not E.list_devices():
                self.device.setItemText(0, 'Видеокарта с Vulkan не найдена — обновите драйвер')
        i = self.device.findData(cur)
        self.device.setCurrentIndex(max(0, i)); self.device.blockSignals(False)
        self._sync()

    def _sync(self, *_):
        ok = E.installed('esrgan')
        self.on.setEnabled(ok)
        if not ok and self.on.isChecked(): self.on.setChecked(False)
        self.mode_note.setText(MODE_NOTES[max(0, self.mode.currentIndex())])
        self.res_note.setText(RES_NOTES[max(0, self.res.currentIndex())])
        balanced = self.mode.currentIndex() == 1
        self.denoise.setEnabled(balanced)
        self.denoise_note.setText('Если выключить, будет модель со слабым шумоподавлением: она сохраняет зерно и мелкую текстуру.' if balanced
                                  else 'В этом режиме модель всегда убирает шум и артефакты сжатия.')
        self.interp.setEnabled(E.installed('rife'))
        if not E.installed('rife') and self.interp.isChecked(): self.interp.setChecked(False)
        self.cmp_btn.setEnabled(ok)
        self.changed.emit()

    def options(self) -> dict:
        return {'on': self.on.isChecked(), 'mode': MODE_KEYS[max(0, self.mode.currentIndex())],
                'resolution': RES_KEYS[max(0, self.res.currentIndex())], 'denoise': self.denoise.isChecked(),
                'sharpen': self.sharpen.isChecked(), 'interpolate': self.interp.isChecked(), 'device': self.device.currentData()}

    def load(self, d: dict):
        if not isinstance(d, dict): return
        if d.get('mode') in MODE_KEYS: self.mode.setCurrentIndex(MODE_KEYS.index(d['mode']))
        if d.get('resolution') in RES_KEYS: self.res.setCurrentIndex(RES_KEYS.index(d['resolution']))
        self.denoise.setChecked(bool(d.get('denoise', True))); self.sharpen.setChecked(bool(d.get('sharpen', False)))
        if d.get('device') is not None:
            i = self.device.findData(d['device'])
            if i >= 0: self.device.setCurrentIndex(i)
        self.on.setChecked(bool(d.get('on')) and E.installed('esrgan'))
        self.interp.setChecked(bool(d.get('interpolate')) and E.installed('rife'))
        self._sync()

    def summary(self) -> str:
        o = self.options()
        if not o['on']: return ''
        return f"AI: {E.MODE_TITLES[o['mode']]}, {self.res.currentText()}" + (', 60 к/с' if o['interpolate'] else '')

    # ------------------------------------------------------------------ install
    def _start(self, worker, on_done, on_fail, progress=None):
        self._threads = [(t, w) for t, w in self._threads if t.isRunning()]
        th = QThread(); worker.moveToThread(th); th.started.connect(worker.run)
        q = Qt.QueuedConnection   # results touch widgets: always deliver them in the window thread
        if progress: worker.progress.connect(progress, q)
        worker.done.connect(on_done, q); worker.failed.connect(on_fail, q)
        worker.done.connect(th.quit); worker.failed.connect(th.quit)
        self._threads.append((th, worker)); th.start()

    def install(self, key: str):
        if self._install_worker is not None: return
        mb = E.DOWNLOAD_MB[key]
        if QMessageBox.question(self, 'Установка AI', f'Скачать {E.COMPONENT_TITLES[key]} (~{mb} МБ) с GitHub?\n\n'
                                f'Файлы будут сохранены в {E.ai_dir()}.') != QMessageBox.Yes:
            return
        self._install_worker = InstallWorker(key)
        for _t, b in self.rows.values(): b.setEnabled(False)
        self.bar.setValue(0); self.bar.show(); self.bar_text.setText('Подключение…'); self.bar_text.show(); self.cancel_install.show()
        self._start(self._install_worker, self._installed, self._install_failed, self._install_progress)

    @Slot(float, str)
    def _install_progress(self, f: float, text: str):
        # a bound slot of this widget: Qt delivers it in the window thread (a lambda would run in the download thread)
        self.bar.setValue(int(f * 1000)); self.bar_text.setText(text)

    def _install_end(self):
        self._install_worker = None
        for _t, b in self.rows.values(): b.setEnabled(True)
        self.bar.hide(); self.bar_text.hide(); self.cancel_install.hide()

    @Slot(str)
    def _installed(self, key: str):
        self._install_end(); self.refresh()
        if key == 'esrgan':
            if not E.list_devices():
                QMessageBox.warning(self, 'AI установлен', 'AI установлен, но не нашёл видеокарту с поддержкой Vulkan. '
                                    'Обновите драйвер видеокарты (NVIDIA, AMD или Intel) и перезапустите программу.')
            else:
                self.on.setChecked(True)
        elif key == 'rife':
            self.interp.setChecked(True)

    @Slot(str)
    def _install_failed(self, err: str):
        self._install_end(); self.refresh()
        QMessageBox.warning(self, 'Установка AI', err)

    # ------------------------------------------------------------------ compare
    def compare(self):
        src = self.w.sources[0] if getattr(self.w, 'sources', None) else ''
        if not src:
            QMessageBox.information(self, 'Сравнение', 'Сначала добавьте видео на вкладке «Проект».'); return
        pane = getattr(self.w, 'design_preview', None)
        t = pane.current_time() if pane is not None and pane.source == src else min(60.0, probe(src)['duration'] / 3)
        self.cmp_btn.setEnabled(False); self.cmp_btn.setText('AI обрабатывает кадр…')
        self.cmp_info.setText('Обработка кадра и замер скорости, обычно до минуты…')
        opts = self.options(); opts['on'] = True
        self._start(CompareWorker(src, t, opts, self._tmp), self._compared, self._compare_failed)

    @Slot(dict)
    def _compared(self, r: dict):
        self.cmp_btn.setEnabled(True); self.cmp_btn.setText('Проверить на кадре из видео')
        self._cmp = r; self.view_seg.setEnabled(True); self.view.setCurrentIndex(1); self._show_cmp()
        sw, sh = r['src_size']; ow, oh = r['out_size']
        per = r['per_frame']
        est = per * r.get('fps', 30) * 120 / 60   # a 2-minute clip; cut pauses are skipped, so usually a bit less
        notes = ('\n' + '; '.join(r['notes'])) if r.get('notes') else ''
        self.cmp_info.setText(f'До: {sw}×{sh}  →  После: {ow}×{oh} · модель {r["model"]} · {r["device"]}. '
                              f'Показан фрагмент из центра кадра в натуральную величину.\n'
                              f'Скорость: {per:.2f} с на кадр — ролик 2 минуты займёт примерно {est:.0f} мин AI-обработки.{notes}')

    @Slot(str)
    def _compare_failed(self, err: str):
        self.cmp_btn.setEnabled(E.installed('esrgan')); self.cmp_btn.setText('Проверить на кадре из видео')
        self.cmp_info.setText('Не получилось: ' + err)

    def _show_cmp(self, *_):
        if not self._cmp: return
        pm = QPixmap(self._cmp['after' if self.view.currentIndex() == 1 else 'before'])
        if pm.isNull(): return
        # a piece from the middle at 100 %: detail is invisible when the whole frame is shrunk to fit
        w = min(pm.width(), max(300, self.width() - 40), 960); h = min(pm.height(), 540)
        self.cmp_img.setPixmap(pm.copy((pm.width() - w) // 2, (pm.height() - h) // 2, w, h))
