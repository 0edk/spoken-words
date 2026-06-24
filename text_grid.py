from aqt.qt import *

from .audio_slider import Endpoint

class IntervalGridWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(80)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._endpoints: list[Endpoint] = []
        self._word_edits: list[QLineEdit] = []
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
        # N endpoints yield N+1 intervals; the last is always exclusive.
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
        """Reposition existing columns without rebuilding widgets.
        Called during drag."""
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
        row_h = h // 2
        bounds = [0] + [int(ep.pos * w) for ep in self._endpoints] + [w]
        for i, (we, te) in enumerate(zip(self._word_edits, self._trans_edits)):
            x0, x1 = bounds[i], bounds[i + 1]
            we.setGeometry(x0,     0, x1 - x0, row_h)
            te.setGeometry(x0, row_h, x1 - x0, row_h)
