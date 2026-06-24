import os
import shutil
import subprocess
import tempfile
import threading

from aqt.utils import show_warning
import numpy as np
from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QBoxLayout, QFileDialog, QHBoxLayout, QLineEdit, QPushButton,
)

from .flashcard_topology import TopologyDialog
from .models import roundup
from .audio_slider import SliderWidget
from .text_grid import IntervalGridWidget

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
        # audio with QMediaPlayer, available inside Anki's bundled Qt6
        self._player    = QMediaPlayer()
        self._audio_out = QAudioOutput()
        self._player.setAudioOutput(self._audio_out)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._check_stop)
        self._duration_ms = 0
        self._stop_at_ms  = 0

    # file

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

    # slider affects grid

    def _on_structure_changed(self) -> None:
        self._grid.set_structure(self._slider.endpoints)

    def _on_positions_updated(self) -> None:
        self._grid.set_positions(self._slider.endpoints)

    # slider triggers audio

    def _on_release(self, idx: int) -> None:
        if not self._duration_ms:
            return
        eps = self._slider.endpoints
        start_ms = int((eps[idx - 1].pos if idx > 0 else 0.0) * self._duration_ms)
        end_ms = int(eps[idx].pos * self._duration_ms)
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
        # releases the GStreamer pipeline
        self._player.setSource(QUrl())
        super().closeEvent(event)
