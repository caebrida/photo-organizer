"""Painel direito: prévia, dados do arquivo selecionado e destino calculado.

Vídeos tocam aqui mesmo (Qt Multimedia). O player só é criado no primeiro play e solta o
arquivo ao trocar de seleção: um vídeo aberto não pode impedir o Mover.
"""

from __future__ import annotations

from PySide6.QtCore import QLocale, Qt, QUrl
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from photo_organizer.core.dates import DateSource
from photo_organizer.core.images import PREVIEW
from photo_organizer.core.planner import PlanItem, Skip
from photo_organizer.core.scanner import FileKind
from photo_organizer.ui import icons, theme
from photo_organizer.ui.rules_panel import section_title
from photo_organizer.ui.theme import breakable
from photo_organizer.ui.workers import ThumbnailService

PREVIEW_W, PREVIEW_H = 268, 180


class Inspector(QFrame):
    def __init__(self, service: ThumbnailService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Inspector")
        self.setFixedWidth(300)
        self._service = service
        self._item: PlanItem | None = None
        self.number_locale = QLocale()
        self.lang = "pt"
        service.thumbnailReady.connect(self._on_image)
        service.metadataReady.connect(self._on_meta)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(section_title(self.tr("Inspetor")))

        self.preview = QLabel()
        self.preview.setObjectName("Preview")
        self.preview.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_stack = QStackedWidget()
        self.preview_stack.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.preview_stack.addWidget(self.preview)
        layout.addWidget(self.preview_stack)

        self.video_bar = QWidget()
        bar = QHBoxLayout(self.video_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        self.play_button = QPushButton(icons.icon("play", theme.TEXT), "")
        self.play_button.setToolTip(self.tr("Reproduzir o vídeo"))
        self.play_button.setFixedWidth(36)
        self.play_button.clicked.connect(self.toggle_play)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setEnabled(False)
        self.seek.sliderMoved.connect(lambda ms: self._player and self._player.setPosition(ms))
        self.time_label = QLabel("0:00")
        self.time_label.setObjectName("Mono")
        bar.addWidget(self.play_button)
        bar.addWidget(self.seek, 1)
        bar.addWidget(self.time_label)
        layout.addWidget(self.video_bar)
        self._player = None  # QMediaPlayer, criado no primeiro play
        self._video_widget = None

        head = QHBoxLayout()
        self.name = QLabel()
        self.name.setObjectName("PillPath")
        self.name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.badge = QLabel()
        self.badge.setObjectName("Badge")
        head.addWidget(self.name, 1)
        head.addWidget(self.badge)
        layout.addLayout(head)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(7)
        self.values: dict[str, QLabel] = {}
        rows = [
            ("date", self.tr("Data de captura")),
            ("camera", self.tr("Câmera")),
            ("lens", self.tr("Lente")),
            ("exposure", self.tr("Exposição")),
            ("size", self.tr("Dimensões")),
            ("sidecar", self.tr("Sidecar")),
            ("tags", self.tr("Tags")),
        ]
        for r, (key, title) in enumerate(rows):
            label = QLabel(title)
            label.setObjectName("Muted")
            value = QLabel("–")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.grid.addWidget(label, r, 0, Qt.AlignmentFlag.AlignTop)
            self.grid.addWidget(value, r, 1)
            self.values[key] = value
        self.source_chip = QLabel()
        self.source_chip.setObjectName("SourceChip")
        self.grid.addWidget(self.source_chip, 0, 2, Qt.AlignmentFlag.AlignTop)
        self.grid.setColumnStretch(1, 1)
        layout.addLayout(self.grid)

        dest = QFrame()
        dest.setObjectName("DestBox")
        dest_layout = QVBoxLayout(dest)
        dest_layout.setContentsMargins(12, 10, 12, 10)
        dest_layout.setSpacing(4)
        self.dest_title = section_title(self.tr("Destino"))
        dest_layout.addWidget(self.dest_title)
        self.dest = QLabel()
        self.dest.setObjectName("DestPath")
        self.dest.setWordWrap(True)
        self.dest.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        dest_layout.addWidget(self.dest)
        layout.addWidget(dest)
        layout.addStretch()

        self.empty = QLabel(self.tr("Selecione um arquivo na grade para ver os detalhes."))
        self.empty.setObjectName("Muted")
        self.empty.setWordWrap(True)
        layout.insertWidget(1, self.empty)
        self.show_item(None)

    def show_item(self, item: PlanItem | None) -> None:
        self.stop_video()
        self._item = item
        widgets = [
            self.preview_stack,
            self.name,
            self.badge,
            self.dest.parentWidget(),
            self.source_chip,
        ]
        for w in widgets:
            w.setVisible(item is not None)
        for i in range(self.grid.count()):
            self.grid.itemAt(i).widget().setVisible(item is not None)
        self.empty.setVisible(item is None)
        self.video_bar.setVisible(item is not None and item.media.kind is FileKind.VIDEO)
        if item is None:
            return

        media = item.media
        self.name.setText(media.path.name)
        self.name.setToolTip(str(media.path))
        try:
            size_mb = media.path.stat().st_size / 1_000_000
        except OSError:
            size_mb = 0.0  # QLocale.toString(int, "f", 1) não existe
        kind = {FileKind.RAW: "RAW", FileKind.VIDEO: self.tr("Vídeo"), FileKind.JPEG: "JPEG"}
        mb = self.number_locale.toString(size_mb, "f", 1)
        self.badge.setText(f"{kind[media.kind]} · {mb} MB")

        when = item.date.value
        fmt = "%d/%m/%Y %H:%M:%S" if self.lang == "pt" else "%Y-%m-%d %H:%M:%S"
        self.values["date"].setText(when.strftime(fmt) if when else self.tr("sem data"))
        chip = {
            DateSource.EXIF: "EXIF",
            DateSource.XMP_SIDECAR: "XMP",
            DateSource.XMP_EMBEDDED: "XMP",
            DateSource.VIDEO: self.tr("VÍDEO"),
            DateSource.FILENAME: self.tr("NOME"),
        }.get(item.date.source)
        self.source_chip.setText(chip or "")
        self.source_chip.setVisible(chip is not None)
        for key in ("camera", "lens", "exposure", "size", "tags"):
            self.values[key].setText("…")
        self.values["sidecar"].setText(media.sidecar.name if media.sidecar else "–")
        if item.trash:
            title = self.tr("Fora: vai para a Lixeira ao mover")
        elif item.skip is Skip.EXCLUDED:
            title = self.tr("Fora: fica onde está")
        elif item.skip is Skip.KEPT:
            title = self.tr("Já está no destino")
        elif item.skip:
            title = self.tr("Fica onde está")
        elif item.replaces is not None:
            title = self.tr("Substitui a do destino")
        else:
            title = self.tr("Destino")
        self.dest_title.setText(title.upper())
        self.dest.setText(breakable(item.dest))
        tip = ""
        if item.duplicate:
            tip = self.tr("Duplicada potencial: vai para a pasta de validação.")
        elif item.replaces is not None:
            tip = self.tr("A foto que está lá vai para a Lixeira.")
        self.dest.setToolTip(tip)

        self.preview.setPixmap(QPixmap())
        self.preview.setText(
            self.tr("Vídeo · clique ▶ para assistir") if media.kind is FileKind.VIDEO else ""
        )
        if media.kind is not FileKind.VIDEO:
            self._service.request_thumbnail(media.path, media.kind, PREVIEW)
        self._service.request_metadata(media.path, media.kind, media.sidecar)

    # --- Vídeo ------------------------------------------------------------------------

    def toggle_play(self) -> None:
        if self._item is None or self._item.media.kind is not FileKind.VIDEO:
            return
        from PySide6.QtMultimedia import QMediaPlayer

        player = self._ensure_player()
        if player.playbackState() is QMediaPlayer.PlaybackState.PlayingState:
            player.pause()
            return
        if player.source().isEmpty():
            player.setSource(QUrl.fromLocalFile(str(self._item.media.path)))
        self.preview_stack.setCurrentWidget(self._video_widget)
        player.play()

    def stop_video(self) -> None:
        """Para e solta o arquivo (no Windows, um vídeo aberto não pode ser movido)."""
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())
        self.preview_stack.setCurrentWidget(self.preview)
        self.seek.setValue(0)
        self.seek.setEnabled(False)
        self.time_label.setText("0:00")
        self.play_button.setIcon(icons.icon("play", theme.TEXT))

    def _ensure_player(self):
        if self._player is None:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget

            self._video_widget = QVideoWidget()
            self.preview_stack.addWidget(self._video_widget)
            self._audio = QAudioOutput(self)
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._audio)
            self._player.setVideoOutput(self._video_widget)
            self._player.durationChanged.connect(self._on_duration)
            self._player.positionChanged.connect(self._on_position)
            self._player.playbackStateChanged.connect(self._on_playback)
            self._player.errorOccurred.connect(self._on_video_error)
        return self._player

    def _on_duration(self, ms: int) -> None:
        self.seek.setRange(0, ms)
        self.seek.setEnabled(ms > 0)

    def _on_position(self, ms: int) -> None:
        if not self.seek.isSliderDown():
            self.seek.setValue(ms)
        minutes, seconds = divmod(ms // 1000, 60)
        self.time_label.setText(f"{minutes}:{seconds:02d}")

    def _on_playback(self, state) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        playing = state is QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setIcon(icons.icon("pause" if playing else "play", theme.TEXT))

    def _on_video_error(self, _error, message: str) -> None:
        self.preview_stack.setCurrentWidget(self.preview)
        self.preview.setText(self.tr("Não foi possível reproduzir este vídeo.\n{m}").format(
            m=message))  # fmt: skip

    def _on_image(self, path: str, image: QImage, size: int) -> None:
        if size != PREVIEW or self._item is None or str(self._item.media.path) != path:
            return
        pm = QPixmap.fromImage(image)
        ratio = self.devicePixelRatioF()
        scaled = pm.scaled(
            int(PREVIEW_W * ratio),
            int(PREVIEW_H * ratio),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        self.preview.setPixmap(scaled)

    def _on_meta(self, path: str, meta: dict) -> None:
        if self._item is None or str(self._item.media.path) != path:
            return
        make = str(meta.get("EXIF:Make", "")).strip()
        model = str(meta.get("EXIF:Model", "")).strip()
        brand = make.split()[0].lower() if make else ""
        # "Canon" + "Canon EOS R5" vira "Canon EOS R5"; "SONY" + "ILCE-6700" fica junto.
        camera = model if brand and model.lower().startswith(brand) else f"{make} {model}".strip()
        self.values["camera"].setText(camera or "–")
        self.values["lens"].setText(
            str(meta.get("EXIF:LensModel") or meta.get("Composite:LensID") or "–")
        )
        self.values["exposure"].setText(self._exposure(meta) or "–")
        size = str(meta.get("Composite:ImageSize", "")).replace("x", " ").split()
        self.values["size"].setText(" × ".join(size) if len(size) == 2 else "–")
        self.values["tags"].setText(", ".join(meta.get("Tags", [])) or "–")

    def _exposure(self, meta: dict) -> str:
        parts = []
        t = meta.get("EXIF:ExposureTime")
        if isinstance(t, int | float) and t > 0:
            parts.append(f"1/{round(1 / t)} s" if t < 1 else f"{t:g} s")
        f = meta.get("EXIF:FNumber")
        if isinstance(f, int | float):
            parts.append(f"f/{f:g}")
        iso = meta.get("EXIF:ISO")
        if iso:
            parts.append(f"ISO {iso}")
        duration = meta.get("QuickTime:Duration")
        if isinstance(duration, int | float):
            minutes, seconds = divmod(round(duration), 60)
            parts.append(f"{minutes}:{seconds:02d}")
        return " · ".join(parts)
