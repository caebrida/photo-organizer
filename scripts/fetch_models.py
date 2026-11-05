"""Baixa e prepara os modelos das tags em photo_organizer/resources/models.

- Pessoas: YOLOX-s do OpenCV Model Zoo (ONNX, Apache-2.0), usado como está.
- Cena e conteúdo: SigLIP 2 base (Google, Apache-2.0). A parte de imagem vira ONNX com os
  pesos guardados em fp16 (metade do tamanho; a conta continua em fp32). As frases de
  photo_organizer/tagging/vocabulary.py viram embeddings de texto aqui, uma única vez.
  O torch e o transformers só são necessários neste script, nunca no programa:

    uv run --no-project --python 3.12 --with torch --with transformers --with sentencepiece \\
        --with protobuf --with onnx --with numpy --with opencv-python-headless --with truststore \\
        python scripts/fetch_models.py

Mudou a lista de tags? Rode de novo: só as embeddings de texto são refeitas (o SigLIP
baixado fica em cache em %LOCALAPPDATA%\\photo-organizer\\hf).
Revisão e SHA-256 fixados para builds reproduzíveis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "photo_organizer" / "resources" / "models"
CACHE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "photo-organizer" / "hf"

YOLOX = (
    "https://huggingface.co/opencv/object_detection_yolox/resolve/main/"
    "object_detection_yolox_2022nov.onnx",
    "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063",
)
SIGLIP = "google/siglip2-base-patch16-224"
SIGLIP_REVISION = "75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2"
SIGLIP_FILES = {
    "config.json": "fe8b5fe6d5734360678fd71c11c21e1ea3364bd8598d34295d9206335973ffd7",
    "model.safetensors": "612923381c76ec5a9bed335d1c48827e3f2e506ac31b044b63b2031fadee6a0b",
    "preprocessor_config.json": "9b36b57ebaf20f09bf4c22100ccc21877ea6bfe5aead0c00c59f8af8ccefacfc",
    "special_tokens_map.json": "baec30ea10906f16adb8c18af7a34023002c1746542612b8b41c9f09e1351351",
    "tokenizer.json": "cb9140fae3ac5122c972d37adf83e1248471a38147ad76f8215c8872c6fd8322",
    "tokenizer.model": "61a7b147390c64585d6c3543dd6fc636906c9af3865a5548f27f31aee1d4c8e2",
    "tokenizer_config.json": "14afe629fe4959b9e0d51e1852b8d9f7ad074f90a1a7125a4fcdd17f06e78fc8",
}
OBSOLETE = (  # modelos da versão com Places365
    "places365_wrn18.onnx",
    "categories_places365.txt",
    "IO_places365.txt",
    "labels_sunattribute.txt",
)


def use_windows_certificates() -> None:
    """Redes com proxy que inspeciona HTTPS: confia nos certificados do Windows."""
    try:
        import truststore
    except ImportError:
        return
    truststore.inject_into_ssl()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, sha256: str, dest: Path) -> Path:
    if dest.is_file() and sha256_of(dest) == sha256:
        return dest
    print(f"Baixando {url} ...")
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as resp, partial.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    digest = sha256_of(partial)
    if digest != sha256:
        partial.unlink()
        sys.exit(f"SHA-256 de {dest.name} não confere: {digest}")
    partial.replace(dest)
    return dest


def fetch_siglip() -> Path:
    folder = CACHE / f"{SIGLIP.split('/')[1]}-{SIGLIP_REVISION[:8]}"
    for name, sha in SIGLIP_FILES.items():
        url = f"https://huggingface.co/{SIGLIP}/resolve/{SIGLIP_REVISION}/{name}"
        fetch(url, sha, folder / name)
    return folder


def export_image(model, out: Path) -> None:
    """Parte de imagem -> ONNX (embedding normalizada), com os pesos guardados em fp16."""
    import numpy as np
    import onnx
    import torch
    from onnx import TensorProto, helper, numpy_helper

    class Image(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.model = model

        def forward(self, pixels):
            f = self.model.get_image_features(pixel_values=pixels)
            f = getattr(f, "pooler_output", f)
            return f / f.norm(dim=-1, keepdim=True)

    with tempfile.TemporaryDirectory() as tmp:
        fp32 = Path(tmp) / "image.onnx"
        torch.onnx.export(
            Image().eval(), torch.zeros(1, 3, 224, 224), str(fp32),
            input_names=["image"], output_names=["embedding"], opset_version=17, dynamo=False,
        )  # fmt: skip
        graph_model = onnx.load(str(fp32))

    # Cada peso grande vira fp16 + um Cast para fp32: o arquivo cai à metade e o cv2.dnn
    # (que não calcula em fp16) continua fazendo a conta em fp32, com o mesmo resultado.
    graph = graph_model.graph
    inits, casts = [], []
    for init in graph.initializer:
        arr = numpy_helper.to_array(init)
        if arr.dtype == np.float32 and arr.size >= 1024:
            half = f"{init.name}__fp16"
            inits.append(numpy_helper.from_array(arr.astype(np.float16), half))
            casts.append(helper.make_node("Cast", [half], [init.name], to=TensorProto.FLOAT))
        else:
            inits.append(init)
    del graph.initializer[:]
    graph.initializer.extend(inits)
    nodes = casts + list(graph.node)
    del graph.node[:]
    graph.node.extend(nodes)
    onnx.save(graph_model, str(out))


def export_text(model, processor, out_dir: Path) -> None:
    import numpy as np
    import torch

    from photo_organizer.tagging import vocabulary as v
    from photo_organizer.tagging.scene import TEXT_EMBEDDINGS, TEXT_META

    prompts = v.prompts()
    with torch.no_grad():
        inputs = processor(text=prompts, padding="max_length", max_length=64, return_tensors="pt")
        t = model.get_text_features(**inputs)
        t = getattr(t, "pooler_output", t)
        t = t / t.norm(dim=-1, keepdim=True)
    np.save(out_dir / TEXT_EMBEDDINGS, t.numpy().astype(np.float32))
    meta = {
        "model": f"{SIGLIP}@{SIGLIP_REVISION}",
        "scale": float(model.logit_scale.exp()),
        "bias": float(model.logit_bias),
        "prompts": prompts,
    }
    (out_dir / TEXT_META).write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    print(f"{len(prompts)} frases -> {TEXT_EMBEDDINGS}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="exporta a parte de imagem de novo")
    args = parser.parse_args()

    use_windows_certificates()
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in OBSOLETE:
        (TARGET / name).unlink(missing_ok=True)
    fetch(*YOLOX, TARGET / "yolox_s.onnx")

    try:
        import torch  # noqa: F401
        from transformers import AutoModel, AutoProcessor
    except ImportError:
        sys.exit("O SigLIP precisa do torch e do transformers; veja o comando no topo do script.")

    sys.path.insert(0, str(ROOT))  # vocabulary.py e scene.py (sem instalar o projeto)
    from photo_organizer.tagging.scene import IMAGE_MODEL

    folder = fetch_siglip()
    model = AutoModel.from_pretrained(folder).eval()
    processor = AutoProcessor.from_pretrained(folder)
    image = TARGET / IMAGE_MODEL
    if image.is_file() and not args.force:
        print(f"{IMAGE_MODEL} já existe (use --force para exportar de novo).")
    else:
        export_image(model, image)
        print(f"{IMAGE_MODEL}: {image.stat().st_size / 1e6:.0f} MB")
    export_text(model, processor, TARGET)
    print(f"Modelos instalados em {TARGET}")


if __name__ == "__main__":
    main()
