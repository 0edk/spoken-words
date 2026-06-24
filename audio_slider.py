from aqt.qt import *
import numpy as np

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

    # geometry

    def _to_pos(self, x: int) -> float:
        return max(0.0, min(1.0, x / max(self.width(), 1)))

    def _to_x(self, pos: float) -> int:
        return int(pos * self.width())

    def _nearest(self, pos: float) -> Endpoint | None:
        return min(self.endpoints, key=lambda e: abs(e.pos - pos), default=None)

    # painting

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        ty = int(h * self._TRACK_Y)
        eph = int(h * self._EP_H_FRAC)
        ept = (h - eph) // 2
        xs = [self._to_x(ep.pos) for ep in self.endpoints]
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

    # mouse

    def mousePressEvent(self, event) -> None:
        pos = self._to_pos(event.pos().x())
        if event.button() == Qt.MouseButton.LeftButton:
            ep = self._nearest(pos)
            if ep:
                self._drag_ep = ep
                self._prev_pos = ep.pos
                self._dragging = True
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
        # suppress platform menu; right-click handled above 
        event.accept()

    # internal

    def _sort(self) -> None:
        self.endpoints.sort(key=lambda e: e.pos)
        self.update()
        self.positions_updated.emit()
