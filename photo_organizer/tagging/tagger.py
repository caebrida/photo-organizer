"""Junta conteúdo e cena (SigLIP), pessoas (YOLOX), condições e estação nas tags de uma foto."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from photo_organizer.core.metadata import resources_dir
from photo_organizer.tagging import vocabulary as v
from photo_organizer.tagging.conditions import conditions, content_tags, season
from photo_organizer.tagging.objects import ObjectDetector
from photo_organizer.tagging.scene import IMAGE_MODEL, TEXT_EMBEDDINGS, TEXT_META, SceneClassifier

MODEL_FILES = ("yolox_s.onnx", IMAGE_MODEL, TEXT_EMBEDDINGS, TEXT_META)


class ModelsNotFoundError(RuntimeError):
    """Os modelos não estão em photo_organizer/resources/models."""


def models_dir() -> Path:
    return resources_dir() / "models"


class Tagger:
    def __init__(self, lang: str = "pt", hemisphere: str = "south", models: Path | None = None):
        models = models or models_dir()
        missing = [f for f in MODEL_FILES if not (models / f).is_file()]
        if missing:
            raise ModelsNotFoundError(
                f"Modelos ausentes em {models}: {', '.join(missing)}. Rode scripts/fetch_models.py."
            )
        self.lang, self.hemisphere = lang, hemisphere
        self.objects = ObjectDetector(models / "yolox_s.onnx")
        self.scene = SceneClassifier(models)

    def tags(self, bgr: np.ndarray, when: datetime | None) -> list[str]:
        scene = self.scene.classify(bgr)
        labels = content_tags(scene)

        people = sum(
            d.cls == v.PERSON and d.area >= v.OBJECT_MIN_AREA
            for d in self.objects.detect(bgr, v.OBJECT_SCORE)
        )
        if people:
            labels.append(v.PERSON_LABEL)
        if people >= v.GROUP_MIN:
            labels.append(v.GROUP)

        labels += conditions(scene)
        if when is not None:
            labels.append(season(when, self.hemisphere))
        return list(dict.fromkeys(v.text(label, self.lang) for label in labels))
