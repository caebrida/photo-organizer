"""Cena e conteúdo: SigLIP 2 (Google, Apache-2.0), comparação imagem × texto (zero-shot).

Só a parte de imagem roda aqui (ONNX no cv2.dnn). As frases de vocabulary.py foram
transformadas em embeddings uma única vez, por scripts/fetch_models.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from photo_organizer.tagging import vocabulary as v

IMAGE_MODEL = "siglip2_image.onnx"
TEXT_EMBEDDINGS = "siglip2_text.npy"
TEXT_META = "siglip2_text.json"
SIZE = 224


class VocabularyMismatchError(RuntimeError):
    """As embeddings de texto foram geradas para outra lista de tags."""


@dataclass(frozen=True, slots=True)
class SceneResult:
    logits: dict[str, float]  # frase (vocabulary.phrase) -> logit do SigLIP


class SceneClassifier:
    def __init__(self, models: Path) -> None:
        meta = json.loads((models / TEXT_META).read_text(encoding="utf-8"))
        if meta["prompts"] != v.prompts():
            raise VocabularyMismatchError(
                "A lista de tags mudou desde que os modelos foram gerados. "
                "Rode scripts/fetch_models.py de novo."
            )
        self.prompts: list[str] = meta["prompts"]
        self.scale, self.bias = float(meta["scale"]), float(meta["bias"])
        self.text = np.load(models / TEXT_EMBEDDINGS).astype(np.float32)
        # O motor novo do OpenCV 5 não monta a atenção do SigLIP; o clássico sim.
        self.net = cv2.dnn.readNetFromONNX(str(models / IMAGE_MODEL), engine=cv2.dnn.ENGINE_CLASSIC)

    def classify(self, bgr: np.ndarray) -> SceneResult:
        small = cv2.resize(bgr, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
        # RGB e (x - 127,5) / 127,5, como o pré-processamento do SigLIP.
        blob = cv2.dnn.blobFromImage(small, 1 / 127.5, (SIZE, SIZE), (127.5,) * 3, swapRB=True)
        self.net.setInput(blob)
        embedding = self.net.forward().reshape(-1)
        logits = self.text @ embedding * self.scale + self.bias
        return SceneResult(dict(zip(self.prompts, logits.tolist(), strict=True)))
