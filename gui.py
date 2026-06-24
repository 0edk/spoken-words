import os
import shutil
import subprocess
import tempfile
import threading

from aqt.utils import show_warning
import numpy as np
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QColor, QPainter, QPen, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QBoxLayout, QFileDialog, QHBoxLayout, QLineEdit,
    QPushButton, QSizePolicy, QWidget,
)

from .flashcard_topology import TopologyDialog
from .models import roundup

_LIME = QColor(0, 255, 0)
_RED  = QColor(220, 0, 0)
_DARK = QColor(40, 40, 40)


class Endpoint:
    __slots__ = ("pos", "inclusive")

    def __init__(self, pos: float, inclusive: bool = True) -> None:
        self.pos = pos
        self.inclusive = inclusive


class SliderWidget(QWidget):
    structure_changed = pyqtSignal()   # endpoint added, or mode toggled
    positions_updated = pyqtSignal()   # position-only change (drag)
    mouse_released    = pyqtSignal(int)  # index of endpoint just moved/toggled

    _TRACK_H   = 6
    _TRACK_Y   = 0.40
    _EP_W      = 4
    _EP_H_FRAC = 0.75

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(200, 60)
        self.setFixedHeight(60)
        self.endpoints: list[Endpoint] = []
        self._drag_ep: Endpoint | None = None
        self._right_click_ep: Endpoint | None = None
        self._prev_pos = 0.0
        self._dragging = False
        self._wf_pixmap: QPixmap | None = None

    # ── geometry ─────────────────────────────────────────────────────

    def _to_pos(self, x: int) -> float:
        return max(0.0, min(1.0, x / max(self.width(), 1)))

    def _to_x(self, pos: float) -> int:
        return int(pos * self.width())

    def _nearest(self, pos: float) -> Endpoint | None:
        return min(self.endpoints, key=lambda e: abs(e.pos - pos), default=None)

    # ── painting ──────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        ty  = int(h * self._TRACK_Y)
        eph = int(h * self._EP_H_FRAC)
        ept = (h - eph) // 2
        xs     = [self._to_x(ep.pos) for ep in self.endpoints]
        bounds = [0] + xs + [w]
        if self._wf_pixmap is not None:
            p.drawPixmap(0, 0, self._wf_pixmap)
        for i in range(len(bounds) - 1):
            # Interval i is governed by endpoints[i] (rightmost governs);
            # interval past the last endpoint is always exclusive (red).
            right_ep = self.endpoints[i] if i < len(self.endpoints) else None
            color = _LIME if (right_ep and right_ep.inclusive) else _RED
            p.fillRect(
                bounds[i], ty, bounds[i + 1] - bounds[i], self._TRACK_H, color
            )
        for x in xs:
            p.fillRect(x - self._EP_W // 2, ept, self._EP_W, eph, _DARK)
        p.end()

    def set_waveform(
        self, centroids: np.ndarray, volumes: np.ndarray
    ) -> None:
        self._wf_pixmap = self._render_waveform(centroids, volumes)
        self.update()

    def _render_waveform(
        self, centroids: np.ndarray, volumes: np.ndarray
    ) -> QPixmap:
        w, h = max(self.width(), 1), max(self.height(), 1)
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(centroids)
        pen = QPen()
        pen.setWidthF(1.5)
        for i in range(n - 1):
            alpha = int(volumes[i] * 210 + 45)
            pen.setColor(QColor(60, 120, 220, alpha))
            p.setPen(pen)
            p.drawLine(
                int(i       / n * w), int((1.0 - centroids[i])     * h),
                int((i + 1) / n * w), int((1.0 - centroids[i + 1]) * h),
            )
        p.end()
        return pm

    # ── mouse ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        pos = self._to_pos(event.pos().x())
        if event.button() == Qt.MouseButton.LeftButton:
            ep = self._nearest(pos)
            if ep:
                self._drag_ep      = ep
                self._prev_pos     = ep.pos
                self._dragging     = True
                ep.pos = pos
                self._sort()
        elif event.button() == Qt.MouseButton.MiddleButton:
            pos = self._to_pos(event.pos().x())
            self.endpoints.append(Endpoint(pos))
            self.endpoints.sort(key=lambda e: e.pos)
            self._right_click_ep = self._nearest(pos)
            self.update()
            self.structure_changed.emit()
        elif event.button() == Qt.MouseButton.RightButton:
            ep = self._nearest(pos)
            if ep:
                self._right_click_ep = ep
                ep.inclusive = not ep.inclusive
                self.update()
                self.structure_changed.emit()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and self._drag_ep is not None:
            self._drag_ep.pos = self._to_pos(event.pos().x())
            self._sort()

    def mouseReleaseEvent(self, event) -> None:
        match event.button():
            case Qt.MouseButton.LeftButton if self._dragging:
                self._dragging = False
                ep = self._drag_ep
                self._drag_ep = None
                if ep is not None:
                    self.mouse_released.emit(self.endpoints.index(ep))
            case Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton:
                ep = self._right_click_ep
                self._right_click_ep = None
                if ep is not None:
                    self.mouse_released.emit(self.endpoints.index(ep))

    def contextMenuEvent(self, event) -> None:
        event.accept()   # suppress platform menu; right-click handled above

    # ── internal ──────────────────────────────────────────────────────

    def _sort(self) -> None:
        self.endpoints.sort(key=lambda e: e.pos)
        self.update()
        self.positions_updated.emit()


class IntervalGridWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._endpoints:   list[Endpoint]  = []
        self._word_edits:  list[QLineEdit] = []
        self._trans_edits: list[QLineEdit] = []

    def set_structure(self, endpoints: list[Endpoint]) -> None:
        """Rebuild columns when endpoint count or mode changes."""
        old_w = [e.text() for e in self._word_edits]
        old_t = [e.text() for e in self._trans_edits]
        for e in self._word_edits + self._trans_edits:
            e.deleteLater()
        self._word_edits.clear()
        self._trans_edits.clear()
        self._endpoints = list(endpoints)
        # N endpoints → N+1 intervals; the last is always exclusive.
        for i in range(len(endpoints) + 1):
            active = i < len(endpoints) and endpoints[i].inclusive
            for lst, old in ((self._word_edits, old_w), (self._trans_edits, old_t)):
                ed = QLineEdit(self)
                ed.setEnabled(active)
                ed.setText(old[i] if i < len(old) else "")
                ed.show()
                lst.append(ed)
        self._reposition()

    def set_positions(self, endpoints: list[Endpoint]) -> None:
        """Reposition existing columns without rebuilding widgets (called during drag)."""
        self._endpoints = list(endpoints)
        self._reposition()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition()

    def _reposition(self) -> None:
        if not self._word_edits:
            return
        w, h = self.width(), self.height()
        if not w or not h:
            return
        row_h  = h // 2
        bounds = [0] + [int(ep.pos * w) for ep in self._endpoints] + [w]
        for i, (we, te) in enumerate(zip(self._word_edits, self._trans_edits)):
            x0, x1 = bounds[i], bounds[i + 1]
            we.setGeometry(x0,     0, x1 - x0, row_h)
            te.setGeometry(x0, row_h, x1 - x0, row_h)

def _compute_waveform(path: str) -> tuple[np.ndarray, np.ndarray]:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    SR = 8000
    raw = subprocess.run(
        [ffmpeg, "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    samples = np.frombuffer(raw, dtype=np.float32)
    N = 512
    hop = N // 2
    idx = np.arange(0, len(samples) - N, hop)
    if len(idx) > 600: # cap for paint perf
        idx = idx[np.linspace(0, len(idx) - 1, 600, dtype=int)]
    freqs = np.fft.rfftfreq(N, d=1.0 / SR)
    centroids = np.empty(len(idx), np.float32)
    volumes = np.empty(len(idx), np.float32)
    for i, s in enumerate(idx):
        frame = samples[s : s + N]
        volumes[i] = float(np.sqrt(np.mean(frame ** 2)))
        mag = np.abs(np.fft.rfft(frame))
        tot = float(mag.sum())
        centroids[i] = float((freqs * mag).sum() / tot) if tot > 1e-9 else 0.0
    cmin, cmax = centroids.min(), centroids.max()
    centroids[:] = (centroids - cmin) / (cmax - cmin) if cmax > cmin else 0.0
    vmax = volumes.max()
    volumes[:] = volumes / vmax if vmax > 0.0 else 0.0
    return centroids, volumes

class ClipsViewDialog(TopologyDialog):
    _waveform_ready = pyqtSignal(object, object)

    def build_interface(self, layout: QBoxLayout) -> None:
        # file picker
        row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("Select an audio file…")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self._path_edit)
        row.addWidget(browse)
        layout.addLayout(row)
        # slider
        self._slider = SliderWidget()
        self._slider.structure_changed.connect(self._on_structure_changed)
        self._slider.positions_updated.connect(self._on_positions_updated)
        self._slider.mouse_released.connect(self._on_release)
        layout.addWidget(self._slider)
        self._waveform_ready.connect(self._on_waveform_ready)
        # grid
        self._grid = IntervalGridWidget()
        layout.addWidget(self._grid)
        # audio — QMediaPlayer is available inside Anki's bundled Qt6
        self._player    = QMediaPlayer()
        self._audio_out = QAudioOutput()
        self._player.setAudioOutput(self._audio_out)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._check_stop)
        self._duration_ms = 0
        self._stop_at_ms  = 0

    # ── file ──────────────────────────────────────────────────────────

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio File", "",
            "Audio Files (*.mp3 *.wav *.ogg *.flac *.m4a);;All Files (*)",
        )
        if path:
            self._path_edit.setText(path)
            self._player.setSource(QUrl.fromLocalFile(path))
            threading.Thread(
                target=self._load_waveform_bg, args=(path,), daemon=True
            ).start()

    def _on_duration_changed(self, dur: int) -> None:
        if dur > 0:
            self._duration_ms = dur

    # ── slider → grid ──────────────────────────────────────────────────

    def _on_structure_changed(self) -> None:
        self._grid.set_structure(self._slider.endpoints)

    def _on_positions_updated(self) -> None:
        self._grid.set_positions(self._slider.endpoints)

    # ── slider → audio ─────────────────────────────────────────────────

    def _on_release(self, idx: int) -> None:
        if not self._duration_ms:
            return
        eps      = self._slider.endpoints
        start_ms = int((eps[idx - 1].pos if idx > 0 else 0.0) * self._duration_ms)
        end_ms   = int(eps[idx].pos * self._duration_ms)
        self._stop_at_ms = end_ms
        self._player.setPosition(start_ms)
        self._player.play()

    def _check_stop(self, pos_ms: int) -> None:
        if self._stop_at_ms and pos_ms >= self._stop_at_ms:
            self._player.pause()
            self._stop_at_ms = 0

    def _load_waveform_bg(self, path: str) -> None:
        self._waveform_ready.emit(*_compute_waveform(path))

    def _on_waveform_ready(self, centroids, volumes) -> None:
        self._slider.set_waveform(centroids, volumes)

    def capture_fields(self) -> None:
        src_path = self._path_edit.text()
        if not src_path:
            return
        eps = self._slider.endpoints
        dur = self._duration_ms
        bounds_ms = [0] + [int(ep.pos * dur) for ep in eps] + [dur]
        inclusive_intervals = sum(1 for ep in eps if ep.inclusive)
        order = roundup(inclusive_intervals, False)
        fname, dot_ext = os.path.splitext(os.path.basename(src_path))
        ext = dot_ext.lstrip(".")
        clip_idx = 0
        tmp_dir = tempfile.mkdtemp()
        for i, ep in enumerate(eps):
            if not ep.inclusive:
                continue
            clip_idx += 1
            word = self._grid._word_edits[i].text()
            trans = self._grid._trans_edits[i].text()
            clip_name = f"{fname}_{clip_idx}_{word}.{ext}"
            actual_name = self._save_clip(
                src_path, bounds_ms[i], bounds_ms[i + 1], clip_name, tmp_dir
            )
            self.fields[f"Clip {clip_idx}"] = f"[sound:{actual_name}]"
            self.fields[f"Word {clip_idx}"] = word
            self.fields[f"Translation {clip_idx}"] = trans
        shutil.rmtree(tmp_dir, ignore_errors=True)
        for i in range(inclusive_intervals + 1, order + 1):
            self.fields[f"Clip {i}"] = ""
            self.fields[f"Word {i}"] = ""
            self.fields[f"Translation {i}"] = ""

    def _save_clip(
        self, src: str, start_ms: int, end_ms: int,
        clip_name: str, tmp_dir: str
    ) -> str:
        col = self.mw.col
        # basename drives add_file's stored name
        tmp_path = os.path.join(tmp_dir, clip_name)
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        subprocess.run(
            [ffmpeg, "-y", "-i", src,
             "-ss", f"{start_ms / 1000:.3f}",
             "-to", f"{end_ms / 1000:.3f}",
             "-c", "copy", tmp_path],
            check=True,
            capture_output=True,
        )
        try:
            return col.media.add_file(tmp_path)
        except Exception:
            dst = os.path.join(os.path.expanduser(
                "~/.local/share/Anki2/User 1/collection.media"
            ), clip_name)
            show_warning(
                f"Couldn't add media file; using naive default: {dst}\n"
            )
            shutil.copy(tmp_path, dst)
            return clip_name

    def closeEvent(self, event: QCloseEvent | None) -> None:
        self._player.stop()
        self._player.setSource(QUrl())   # releases the GStreamer pipeline
        super().closeEvent(event)
