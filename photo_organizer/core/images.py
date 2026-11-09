"""Decodificação de imagens para miniaturas, prévias e tags.

RAW nunca é decodificado: usa-se o JPEG embutido (miniatura, prévia ou JpgFromRaw),
extraído pelo ExifTool. HEIC (iPhone) é decodificado pelo libheif (pacote pi-heif), que
já aplica a rotação gravada no arquivo.
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
    if is_heic(path):
        return heic_image(path, size)
    return decode(path.read_bytes(), size)


def is_heic(path: Path) -> bool:
    return path.suffix.lower() == ".heic"


def heic_image(path: Path, size: int = 0) -> np.ndarray | None:
    """HEIC em BGR, reduzida para o lado maior ≈ ``size`` (0 = tamanho original)."""
    import pi_heif  # só carrega a DLL do libheif quando aparece um HEIC

    try:
        # shortcut: decodifica a foto inteira (~12 MP) mesmo para miniatura; a miniatura
        # embutida no HEIC seria mais rápida, se a grade ficar lenta com milhares de HEIC.
        heif = pi_heif.open_heif(path.read_bytes(), convert_hdr_to_8bit=True)
        rgb = np.asarray(heif)
    except (OSError, ValueError, RuntimeError):  # corrompido ou sem imagem
        return None
    img = cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGR if heif.mode == "RGBA" else cv2.COLOR_RGB2BGR)
    h, w = img.shape[:2]
    if size and max(h, w) > 2 * size:
        scale = 2 * size / max(h, w)  # folga para quem ainda vai recortar ou reduzir
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    return img


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
