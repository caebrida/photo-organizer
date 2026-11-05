"""Detector de objetos: YOLOX-s (COCO, 80 classes) do OpenCV Model Zoo via cv2.dnn.

Pré e pós-processamento como em opencv_zoo/models/object_detection_yolox: imagem BGR
0–255 sem normalizar, letterbox 640×640 com cinza 114.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

SIZE = 640
STRIDES = (8, 16, 32)
NMS = 0.5


@dataclass(frozen=True, slots=True)
class Detection:
    cls: int
    score: float
    area: float  # fração da foto ocupada pela caixa


class ObjectDetector:
    def __init__(self, model: Path) -> None:
        self.net = cv2.dnn.readNetFromONNX(str(model))
        grids, strides = [], []
        for s in STRIDES:
            n = SIZE // s
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
            strides.append(np.full((n * n, 1), s))
        self.grids = np.concatenate(grids).astype(np.float32)
        self.strides = np.concatenate(strides).astype(np.float32)

    def detect(self, bgr: np.ndarray, min_score: float) -> list[Detection]:
        h, w = bgr.shape[:2]
        ratio = min(SIZE / h, SIZE / w)
        rh, rw = max(1, int(h * ratio)), max(1, int(w * ratio))  # 3000×2 não vira 0 px
        blob = np.full((SIZE, SIZE, 3), 114, np.float32)
        blob[:rh, :rw] = cv2.resize(bgr, (rw, rh), interpolation=cv2.INTER_LINEAR)
        self.net.setInput(blob.transpose(2, 0, 1)[None].copy())
        dets = self.net.forward()[0]

        scores = dets[:, 4:5] * dets[:, 5:]
        best, cls = scores.max(axis=1), scores.argmax(axis=1)
        keep = best >= min_score
        if not keep.any():
            return []
        centers = (dets[keep, :2] + self.grids[keep]) * self.strides[keep]
        sizes = np.exp(dets[keep, 2:4]) * self.strides[keep]
        boxes = np.concatenate([centers - sizes / 2, sizes], axis=1) / ratio  # x, y, w, h
        best, cls = best[keep], cls[keep]
        idx = cv2.dnn.NMSBoxesBatched(boxes.tolist(), best.tolist(), cls.tolist(), min_score, NMS)
        return [
            Detection(int(cls[i]), float(best[i]), float(boxes[i, 2] * boxes[i, 3] / (w * h)))
            for i in np.asarray(idx).reshape(-1)
        ]
