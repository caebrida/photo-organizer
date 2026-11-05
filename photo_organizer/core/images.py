"""Decodificação de imagens para miniaturas, prévias e tags.

RAW nunca é decodificado: usa-se o JPEG embutido (miniatura, prévia ou JpgFromRaw),
extraído pelo ExifTool.
"""

from __future__ import annotations

import base64
from pathlib import Path

import cv2
import numpy as np

from photo_organizer.core.metadata import MetadataReader
from photo_organizer.core.scanner import FileKind

THUMB = 256  # lado maior da miniatura da grade
PREVIEW = 640  # lado maior da prévia do inspetor (e da imagem analisada pelas tags)

_ROTATIONS = {3: cv2.ROTATE_180, 6: cv2.ROTATE_90_CLOCKWISE, 8: cv2.ROTATE_90_COUNTERCLOCKWISE}


def load_image(
    path: Path, kind: FileKind, size: int, reader: MetadataReader | None
) -> np.ndarray | None:
    """Imagem BGR com o lado maior ≥ ``size`` (aprox.), ou ``None`` (vídeo, ilegível)."""
    if kind is FileKind.VIDEO:
        return None
    if kind is FileKind.RAW:
        assert reader is not None
        return raw_preview(path, size, reader)
    return decode(path.read_bytes(), size)


def decode(data: bytes, size: int) -> np.ndarray | None:
    # Decodificar em resolução reduzida é muito mais rápido para JPEGs grandes.
    if len(data) > 4_000_000 and size <= THUMB:
        flag = cv2.IMREAD_REDUCED_COLOR_8
    elif len(data) > 600_000:
        flag = cv2.IMREAD_REDUCED_COLOR_4 if size <= THUMB else cv2.IMREAD_REDUCED_COLOR_2
    else:
        flag = cv2.IMREAD_COLOR
    img = cv2.imdecode(np.frombuffer(data, np.uint8), flag)
    return img if img is not None and img.size else None


def raw_preview(path: Path, size: int, reader: MetadataReader) -> np.ndarray | None:
    order = ["ThumbnailImage", "PreviewImage", "JpgFromRaw"]
    if size > THUMB:
        order = ["PreviewImage", "JpgFromRaw", "ThumbnailImage"]
    for tag in order:
        [meta] = reader.read([path], [tag, "EXIF:Orientation"], ["-b"]) or [{}]
        value = next((v for k, v in meta.items() if k.endswith(f":{tag}")), None)
        if isinstance(value, str) and value.startswith("base64:"):
            img = decode(base64.b64decode(value[7:]), size)
            if img is not None:
                rotation = _ROTATIONS.get(meta.get("EXIF:Orientation"))
                return cv2.rotate(img, rotation) if rotation is not None else img
    return None
