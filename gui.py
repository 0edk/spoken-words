from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QBoxLayout, QFileDialog, QHBoxLayout, QLineEdit,
    QPushButton, QSizePolicy, QWidget,
)

from .flashcard_topology import TopologyDialog

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
        self._last_drag_ep: Endpoint | None = None  # survives mouseRelease for dblclick undo
        self._right_click_ep: Endpoint | None = None
        self._prev_pos = 0.0
        self._dragging = False

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

    # ── mouse ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        pos = self._to_pos(event.pos().x())
        if event.button() == Qt.MouseButton.LeftButton:
            ep = self._nearest(pos)
            if ep:
                self._drag_ep      = ep
                self._prev_pos     = ep.pos
                self._last_drag_ep = None
                self._dragging     = True
                ep.pos = pos
                self._sort()
        elif event.button() == Qt.MouseButton.RightButton:
            ep = self._nearest(pos)
            if ep:
                self._right_click_ep = ep
                ep.inclusive = not ep.inclusive
                self.update()
                self.structure_changed.emit()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # The first press of this double-click already moved _last_drag_ep;
        # restore it before adding the new endpoint.
        if self._last_drag_ep is not None:
            self._last_drag_ep.pos = self._prev_pos
            self._last_drag_ep = None
        pos = self._to_pos(event.pos().x())
        self.endpoints.append(Endpoint(pos))
        self.endpoints.sort(key=lambda e: e.pos)
        self.update()
        self.structure_changed.emit()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and self._drag_ep is not None:
            self._drag_ep.pos = self._to_pos(event.pos().x())
            self._sort()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            ep = self._drag_ep
            self._drag_ep = None
            if ep is not None:
                self._last_drag_ep = ep   # preserve so dblclick can undo
                self.mouse_released.emit(self.endpoints.index(ep))
        elif event.button() == Qt.MouseButton.RightButton:
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


class ClipsViewDialog(TopologyDialog):
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

    def capture_fields(self) -> None:
        pass
