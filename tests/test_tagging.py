import json
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from conftest import make_jpeg, make_sidecar, requires_exiftool, requires_models

from photo_organizer.core.metadata import MetadataReader
from photo_organizer.core.scanner import FileKind, MediaFile, scan
from photo_organizer.tagging import vocabulary as v
from photo_organizer.tagging.conditions import conditions, content_tags, season
from photo_organizer.tagging.scene import (
    TEXT_EMBEDDINGS,
    TEXT_META,
    SceneClassifier,
    SceneResult,
    VocabularyMismatchError,
)
from photo_organizer.tagging.tagger import Tagger, models_dir
from photo_organizer.tagging.xmp_writer import (
    SUBJECT,
    existing_tags,
    merge_tags,
    tag_sidecar,
    write_tags,
)


def scene(inout: float = 0.0, sun: float = 0.0, **tags: float) -> SceneResult:
    """Logits sintéticos: tudo em 0, menos as diferenças pedidas."""
    logits = dict.fromkeys(v.prompts(), 0.0)
    logits[v.phrase(v.OUTDOOR_PROMPT)] = inout
    logits[v.phrase(v.SUNNY_PROMPT)] = sun
    for label, value in tags.items():
        tag = next(t for t in v.TAGS if t.label[0] == label.replace("_", " "))
        for prompt in tag.prompts:
            logits[v.phrase(prompt)] = value
    return SceneResult(logits)


def test_season_depends_on_hemisphere():
    assert season(datetime(2026, 1, 15)) == v.SEASONS["summer"]
    assert season(datetime(2026, 1, 15), "north") == v.SEASONS["winter"]
    assert season(datetime(2026, 4, 1)) == v.SEASONS["autumn"]
    assert season(datetime(2026, 10, 1), "north") == v.SEASONS["autumn"]


def test_conditions_only_when_confident():
    assert conditions(scene(inout=4, sun=2)) == [v.OUTDOOR, v.SUN]
    assert conditions(scene(inout=4, sun=-2)) == [v.OUTDOOR]  # nublado: sem "sol"
    assert conditions(scene(inout=1, sun=3)) == []  # dúvida entre dentro e fora
    assert conditions(scene(inout=-5)) == [v.INDOOR]


def test_content_tags_keep_only_strong_ones():
    assert content_tags(scene(praia=8, mar=7)) == [("praia", "beach"), ("mar", "sea")]
    assert content_tags(scene()) == []  # nada se destaca
    # Três tags iguais (1/3 cada): as normais entram, a rigorosa ("natal") não.
    assert content_tags(scene(natal=6, árvore=6, floresta=6)) == [
        ("floresta", "forest"),
        ("árvore", "tree"),
    ]
    many = {t.label[0].replace(" ", "_"): 9 for t in v.TAGS[:8]}
    assert len(content_tags(scene(**many))) <= v.MAX_TAGS


def sidecar_tags(reader: MetadataReader, sidecar: Path) -> list[str]:
    [meta] = reader.read([sidecar], [SUBJECT])
    value = meta.get("XMP:Subject", [])
    return value if isinstance(value, list) else [value]


def test_merge_tags_cleans_text_and_ignores_case():
    # Uma quebra de linha viraria outro argumento do ExifTool (ex.: "-all=").
    assert merge_tags(["Beach"], ["beach", "praia\n-all=", "  ", "Mar ", "mar"]) == [
        "Beach",
        "praia -all=",
        "Mar",
    ]


def test_tag_sidecar_names():
    jpg = MediaFile(Path("D:/f/DSC1.JPG"), FileKind.JPEG)
    raw = MediaFile(Path("D:/f/DSC1.ARW"), FileKind.RAW)
    assert tag_sidecar(jpg).name == "DSC1.JPG.xmp"  # não mistura com o XMP do RAW
    assert tag_sidecar(raw).name == "DSC1.xmp"


@requires_exiftool
def test_write_tags_keeps_lightroom_sidecar_and_avoids_repeats(tmp_path):
    raw = tmp_path / "DSC0001.ARW"
    raw.write_bytes(b"raw")
    xmp = make_sidecar(tmp_path / "DSC0001.xmp", "2026-10-27T14:32:08")
    [media] = scan(tmp_path)
    assert media.sidecar == xmp
    with MetadataReader() as reader:
        assert write_tags(reader, media, ["praia", "verão"]) == xmp
        write_tags(reader, media, ["praia", "pôr do sol"])
        assert sidecar_tags(reader, xmp) == ["praia", "verão", "pôr do sol"]
        [meta] = reader.read([xmp], ["XMP:CreateDate"])
    assert str(meta["XMP:CreateDate"]).startswith("2026:10:27 14:32:08")  # data preservada
    assert raw.read_bytes() == b"raw"  # o original não muda


@requires_exiftool
def test_write_tags_creates_jpeg_sidecar(tmp_path):
    jpg = make_jpeg(tmp_path / "Férias" / "IMG_1.jpg")
    before = jpg.read_bytes()
    [media] = scan(tmp_path)
    with MetadataReader() as reader:
        sidecar = write_tags(reader, media, ["cachorro"])
        assert sidecar == jpg.with_name("IMG_1.jpg.xmp")
        assert sidecar_tags(reader, sidecar) == ["cachorro"]
    assert jpg.read_bytes() == before
    # O escaneamento seguinte associa o novo sidecar ao JPEG (e o organizador o leva junto).
    [again] = scan(tmp_path)
    assert again.sidecar == sidecar


@requires_exiftool
def test_write_tags_skips_keywords_already_in_the_file(tmp_path):
    jpg = make_jpeg(tmp_path / "IMG_2.jpg")
    [media] = scan(tmp_path)
    with MetadataReader() as reader:
        reader.write(
            jpg, ["-overwrite_original", "-XMP-dc:Subject=praia", "-IPTC:Keywords=familia"]
        )
        assert existing_tags(reader, [media]) == {jpg: ["praia", "familia"]}
        sidecar = write_tags(reader, media, ["praia", "familia", "cachorro"])
        assert sidecar_tags(reader, sidecar) == ["cachorro"]  # só a que faltava
        assert existing_tags(reader, [media]) == {jpg: ["praia", "familia", "cachorro"]}


@requires_exiftool
def test_tag_with_line_break_does_not_become_an_exiftool_command(tmp_path):
    raw = tmp_path / "DSC0001.ARW"
    raw.write_bytes(b"raw")
    xmp = make_sidecar(tmp_path / "DSC0001.xmp", "2026-10-27T14:32:08")
    [media] = scan(tmp_path)
    with MetadataReader() as reader:
        write_tags(reader, media, ["praia\n-all=", "Praia -ALL="])
        assert sidecar_tags(reader, xmp) == ["praia -all="]
        [meta] = reader.read([xmp], ["XMP:CreateDate"])
    assert str(meta["XMP:CreateDate"]).startswith("2026:10:27")  # o sidecar não foi apagado


def test_raw_files_with_same_name_get_their_own_sidecars(tmp_path):
    cr2, dng = tmp_path / "DSC1.CR2", tmp_path / "DSC1.DNG"
    cr2.write_bytes(b"raw")
    dng.write_bytes(b"raw")
    (tmp_path / "DSC1.xmp").write_text("x")  # já gravado para o CR2
    assert tag_sidecar(MediaFile(cr2, FileKind.RAW)) == tmp_path / "DSC1.xmp"
    assert tag_sidecar(MediaFile(dng, FileKind.RAW)) == tmp_path / "DSC1.DNG.xmp"
    assert [m.sidecar for m in scan(tmp_path)] == [tmp_path / "DSC1.xmp", None]


@requires_models
def test_text_embeddings_match_vocabulary(tmp_path):
    SceneClassifier(models_dir())  # não levanta: fetch_models.py gerou para esta lista
    for name in (TEXT_META, TEXT_EMBEDDINGS):  # a lista é conferida antes de abrir o ONNX
        shutil.copy2(models_dir() / name, tmp_path / name)
    meta = json.loads((tmp_path / TEXT_META).read_text("utf-8"))
    meta["prompts"][0] = "This is a photo of something else."
    (tmp_path / TEXT_META).write_text(json.dumps(meta), "utf-8")
    with pytest.raises(VocabularyMismatchError):
        SceneClassifier(tmp_path)


@requires_models
def test_tagger_runs_on_plain_image():
    tagger = Tagger("en", "north")
    sky = np.zeros((480, 640, 3), np.uint8)
    sky[:] = (235, 180, 120)  # azul-claro em BGR
    tags = tagger.tags(sky, datetime(2026, 7, 4))
    assert tags[-1] == "summer"
    assert len(tags) == len(set(tags))
    assert "summer" not in tagger.tags(sky, None)
    for thin in ((2, 3000, 3), (3000, 2, 3)):  # proporção acima de 640:1
        tagger.tags(np.zeros(thin, np.uint8), None)
