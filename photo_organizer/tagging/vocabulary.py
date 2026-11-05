"""Rótulos das tags (PT/EN), as descrições que o SigLIP compara com a foto e os limiares.

Mudou uma descrição ou uma tag? Rode scripts/fetch_models.py de novo: ele recalcula as
embeddings de texto (o programa recusa uma lista que não bate com elas).
Na dúvida, a tag não é gravada (decisão 11).
"""

from __future__ import annotations

from typing import NamedTuple

Label = tuple[str, str]  # (pt, en)


class Tag(NamedTuple):
    label: Label
    prompts: tuple[str, ...]  # em inglês, que o SigLIP entende melhor
    share: float = 0.12  # fatia mínima da tag entre todas as tags da foto (softmax)


STRICT = 0.35  # tags que confundem com facilidade (ex.: "natal" num pinheiro)
VERY_STRICT = 0.5  # erraram mesmo com STRICT nas fotos do NAS
MAX_TAGS = 5  # tags de cena/conteúdo por foto, as mais fortes

# fmt: off
TAGS: tuple[Tag, ...] = (
    Tag(("praia", "beach"), ("a beach", "people on a sandy beach by the sea")),
    Tag(("mar", "sea"), ("the sea", "ocean waves")),
    Tag(("montanha", "mountain"), ("mountains", "a mountain landscape")),
    Tag(("floresta", "forest"), ("a forest", "trees in a dense forest")),
    Tag(("campo", "countryside"), ("a countryside field", "farmland")),
    Tag(("cachoeira", "waterfall"), ("a waterfall",)),
    Tag(("lago", "lake"), ("a lake",)),
    Tag(("rio", "river"), ("a river",)),
    Tag(("neve", "snow"), ("snow", "a snowy landscape")),
    Tag(("deserto", "desert"), ("a desert",)),
    Tag(("cidade", "city"), ("a city street", "buildings in a city")),
    Tag(("monumento", "landmark"), ("a famous landmark", "a monument")),
    Tag(("igreja", "church"), ("the interior of a church", "a church", "a cathedral")),
    Tag(("museu", "museum"), ("the interior of a museum", "an art gallery")),
    Tag(("restaurante", "restaurant"), ("a restaurant", "people eating at a restaurant")),
    Tag(("cozinha", "kitchen"), ("a kitchen",)),
    Tag(("sala de estar", "living room"), ("a living room",)),
    Tag(("quarto", "bedroom"), ("a bedroom",)),
    Tag(("banheiro", "bathroom"), ("a bathroom",)),
    Tag(("escritório", "office"), ("an office",)),
    Tag(("escola", "school"), ("a classroom",)),
    Tag(("loja", "shop"), ("a shop", "a shopping mall")),
    Tag(("hotel", "hotel"), ("a hotel room",)),
    Tag(("aeroporto", "airport"), ("an airport",), STRICT),
    Tag(("estádio", "stadium"), ("a stadium",)),
    Tag(("parque", "park"), ("a park",)),
    Tag(("jardim", "garden"), ("a garden",)),
    Tag(("piscina", "swimming pool"), ("a swimming pool",)),
    Tag(("parque de diversões", "amusement park"), ("an amusement park",)),
    Tag(("zoológico", "zoo"), ("a zoo", "an aquarium")),
    Tag(("estrada", "road"), ("a road", "a highway")),
    Tag(("acampamento", "camping"), ("camping", "a tent")),
    Tag(("trilha", "hiking"), ("hiking on a trail",)),
    Tag(("pôr do sol", "sunset"), ("a sunset", "a sunrise")),
    Tag(("noite", "night"), ("a photo taken at night",)),
    Tag(("céu", "sky"), ("the sky with clouds",)),
    Tag(("chuva", "rain"), ("a rainy day", "rain"), VERY_STRICT),
    Tag(("fogos de artifício", "fireworks"), ("fireworks",)),
    Tag(("festa", "party"), ("a party",)),
    Tag(("evento", "event"), ("a convention or exhibition", "an audience at an indoor event")),
    Tag(("casamento", "wedding"), ("a wedding",), STRICT),
    Tag(("aniversário", "birthday"), ("a birthday party", "a birthday cake"), STRICT),
    Tag(("natal", "christmas"), ("christmas decorations", "a christmas tree"), STRICT),
    Tag(("show", "concert"), ("a concert",)),
    Tag(("esporte", "sports"), ("people playing sports",)),
    Tag(("comida", "food"), ("food", "a plate of food")),
    Tag(("bebida", "drink"), ("a drink", "a glass of wine or beer")),
    Tag(("documento", "document"), ("a document", "a paper with text")),
    Tag(("captura de tela", "screenshot"), ("a screenshot of a phone or computer screen",)),
    Tag(("selfie", "selfie"), ("a selfie",), VERY_STRICT),
    Tag(("retrato", "portrait"), ("a portrait of a person",)),
    Tag(("bebê", "baby"), ("a baby",), STRICT),
    Tag(("criança", "child"), ("a child", "kids playing")),
    Tag(("cachorro", "dog"), ("a dog",)),
    Tag(("gato", "cat"), ("a cat",)),
    Tag(("pássaro", "bird"), ("a bird",)),
    Tag(("cavalo", "horse"), ("a horse",)),
    Tag(("macaco", "monkey"), ("a monkey",)),
    Tag(("vaca", "cow"), ("a cow",)),
    Tag(("borboleta", "butterfly"), ("a butterfly",)),
    Tag(("inseto", "insect"), ("an insect",)),
    Tag(("peixe", "fish"), ("a fish",)),
    Tag(("carro", "car"), ("a car",)),
    Tag(("bicicleta", "bicycle"), ("a bicycle",)),
    Tag(("moto", "motorcycle"), ("a motorcycle",)),
    Tag(("barco", "boat"), ("a boat",)),
    Tag(("trem", "train"), ("a train",)),
    Tag(("avião", "airplane"), ("an airplane",)),
    Tag(("flores", "flowers"), ("flowers",)),
    Tag(("árvore", "tree"), ("a tree",)),
)
# fmt: on

# --- Condições: comparam duas descrições opostas (diferença de logit) -----------------
OUTDOOR: Label = ("ao ar livre", "outdoors")
INDOOR: Label = ("ambiente interno", "indoors")
OUTDOOR_PROMPT, INDOOR_PROMPT = "an outdoor scene", "an indoor scene"
INOUT_MARGIN = 2.0  # pega ~93% das "ao ar livre" e todas as "ambiente interno" do Places365
SUN: Label = ("sol", "sunny")
SUNNY_PROMPT, CLOUDY_PROMPT = "a sunny day with blue sky", "an overcast cloudy day"
SUN_MARGIN = 1.0  # fotos do NAS: nubladas de -5,3 a 0,4; ensolaradas de 0,8 para cima

SEASONS: dict[str, Label] = {
    "summer": ("verão", "summer"),
    "autumn": ("outono", "autumn"),
    "winter": ("inverno", "winter"),
    "spring": ("primavera", "spring"),
}

# --- Pessoas: YOLOX (classe 0 do COCO), que conta melhor que o SigLIP ----------------
PERSON = 0  # classe "person" do COCO
PERSON_LABEL: Label = ("pessoa", "person")
GROUP: Label = ("grupo de pessoas", "group of people")
GROUP_MIN = 3  # pessoas detectadas para a tag "grupo de pessoas"
OBJECT_SCORE = 0.5  # confiança mínima do detector
OBJECT_MIN_AREA = 0.005  # fração da foto; descarta pessoas minúsculas ao fundo


def prompts() -> list[str]:
    """Todas as frases, na ordem das embeddings de texto geradas por fetch_models.py."""
    phrases = [p for tag in TAGS for p in tag.prompts]
    phrases += [OUTDOOR_PROMPT, INDOOR_PROMPT, SUNNY_PROMPT, CLOUDY_PROMPT]
    return [phrase(p) for p in phrases]


def phrase(description: str) -> str:
    return f"This is a photo of {description}."


def text(label: Label, lang: str) -> str:
    return label[0] if lang == "pt" else label[1]
