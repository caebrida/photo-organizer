"""Estação do ano (pela data e pelo hemisfério), condições e escolha das tags de conteúdo."""

from __future__ import annotations

import math
from datetime import datetime

from photo_organizer.tagging import vocabulary as v
from photo_organizer.tagging.scene import SceneResult

# Estações meteorológicas (meses inteiros), hemisfério Sul.
_SOUTH = {m: s for months, s in (((12, 1, 2), "summer"), ((3, 4, 5), "autumn"),
                                 ((6, 7, 8), "winter"), ((9, 10, 11), "spring"))
          for m in months}  # fmt: skip
_OPPOSITE = {"summer": "winter", "winter": "summer", "autumn": "spring", "spring": "autumn"}


def season(when: datetime, hemisphere: str = "south") -> v.Label:
    key = _SOUTH[when.month]
    return v.SEASONS[key if hemisphere == "south" else _OPPOSITE[key]]


def content_tags(scene: SceneResult) -> list[v.Label]:
    """Tags de vocabulary.TAGS: o softmax entre todas elas dá a fatia de cada uma na foto;
    entram as que passam do mínimo, das mais fortes para as mais fracas."""
    strength = [max(scene.logits[v.phrase(p)] for p in tag.prompts) for tag in v.TAGS]
    top = max(strength)
    weights = [math.exp(s - top) for s in strength]
    total = sum(weights)
    ranked = sorted(zip(v.TAGS, weights, strict=True), key=lambda tw: -tw[1])
    return [tag.label for tag, w in ranked if w / total >= tag.share][: v.MAX_TAGS]


def conditions(scene: SceneResult) -> list[v.Label]:
    """Ao ar livre / interno e sol, comparando duas frases opostas; só com folga clara
    (decisão 11). Neve e chuva são tags de conteúdo."""
    logit = scene.logits
    inout = logit[v.phrase(v.OUTDOOR_PROMPT)] - logit[v.phrase(v.INDOOR_PROMPT)]
    if inout >= v.INOUT_MARGIN:
        sun = logit[v.phrase(v.SUNNY_PROMPT)] - logit[v.phrase(v.CLOUDY_PROMPT)]
        return [v.OUTDOOR, v.SUN] if sun >= v.SUN_MARGIN else [v.OUTDOOR]
    if inout <= -v.INOUT_MARGIN:
        return [v.INDOOR]
    return []
