"""Gera a tradução para inglês da interface (o código-fonte está em português).

1. ``pyside6-lupdate`` extrai os textos de ``photo_organizer/ui`` para ``i18n/en.ts``;
2. este script preenche as traduções a partir da tabela ``EN`` abaixo;
3. ``pyside6-lrelease`` compila ``i18n/en.qm``, carregado por ``app.py``.

Uso:  uv run python scripts/build_translations.py
Textos novos sem tradução na tabela são listados e o script termina com erro.
"""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "photo_organizer" / "ui"
TS = ROOT / "photo_organizer" / "i18n" / "en.ts"
QM = TS.with_suffix(".qm")
BIN = Path(sys.executable).parent

EN = {
    # DuplicatesView
    "Grupos de duplicadas": "Duplicate groups",
    "Nenhuma duplicada encontrada.": "No duplicates found.",
    "{n} cópias": "{n} copies",
    "1 cópia": "1 copy",
    "Grupo {i} de {n} · {k} arquivos": "Group {i} of {n} · {k} files",
    "Vídeo": "Video",
    "Mover para «{folder}»": "Move to “{folder}”",
    "Modificado: {d}": "Modified: {d}",
    "Captura: {d}": "Taken: {d}",
    # Inspector
    "Inspetor": "Inspector",
    "Data de captura": "Date taken",
    "Câmera": "Camera",
    "Lente": "Lens",
    "Exposição": "Exposure",
    "Dimensões": "Dimensions",
    "Sidecar": "Sidecar",
    "Destino": "Destination",
    "Selecione um arquivo na grade para ver os detalhes.": "Select a file in the grid to see its details.",
    "sem data": "no date",
    "VÍDEO": "VIDEO",
    "Fica onde está": "Stays where it is",
    "Duplicada potencial: vai para a pasta de validação.": "Potential duplicate: goes to the review folder.",
    # LibraryView
    "{n} itens": "{n} items",
    "1 item": "1 item",
    # MainWindow
    "&Arquivo": "&File",
    "Escolher origem…": "Choose source…",
    "Escolher destino…": "Choose destination…",
    "Escanear": "Scan",
    "Organizar": "Organize",
    "Sair": "Exit",
    "&Exibir": "&View",
    "Idioma": "Language",
    "A&juda": "&Help",
    "Sobre o Photo Organizer": "About Photo Organizer",
    "Origem": "Source",
    "Escolher pasta…": "Choose folder…",
    "Duplicadas": "Duplicates",
    "Todos": "All",
    "Fotos": "Photos",
    "Vídeos": "Videos",
    "Cancelar": "Cancel",
    "Pasta de origem": "Source folder",
    "Pasta de destino": "Destination folder",
    "Não foi possível acessar a pasta de origem:": "Could not access the source folder:",
    "Não foi possível acessar a pasta de destino:": "Could not access the destination folder:",
    "A pasta não existe ou não está disponível.": "The folder does not exist or is not available.",
    "Pasta de rede: abra-a uma vez no Explorador de Arquivos para entrar com usuário e senha e tente de novo.": (
        "Network folder: open it once in File Explorer to sign in with your user name and "
        "password, then try again."
    ),
    "… e mais {n}": "… and {n} more",
    "{n} pastas não puderam ser lidas e ficaram de fora:": "{n} folders could not be read and were skipped:",
    "Nenhuma foto ou vídeo encontrado": "No photos or videos found",
    "A origem não tem JPEG, RAW ou vídeos suportados.": "The source has no supported JPEG, RAW or video files.",
    "Escolha o destino": "Choose the destination",
    "{n} arquivos lidos. Escolha a pasta de destino para ver o plano.": (
        "{n} files read. Choose the destination folder to see the plan."
    ),
    "Todos os arquivos já estão no lugar certo.": "All files are already in the right place.",
    "Mover {n} arquivos para\n{dest}?\n\nOs arquivos saem da origem. Não há desfazer; um relatório CSV registra cada arquivo.": (
        "Move {n} files to\n{dest}?\n\nThe files leave the source. There is no undo; a CSV "
        "report records every file."
    ),
    "Copiar {n} arquivos para\n{dest}?\n\nA origem não é alterada.": (
        "Copy {n} files to\n{dest}?\n\nThe source is not changed."
    ),
    "Mover": "Move",
    "Copiar": "Copy",
    "Organizados: {n}": "Organized: {n}",
    "Já estavam no lugar: {n}": "Already in place: {n}",
    "Com aviso: {n}": "With warnings: {n}",
    "Com erro: {n}": "Failed: {n}",
    "Cancelados (não tocados): {n}": "Cancelled (untouched): {n}",
    "Organização cancelada": "Organizing cancelled",
    "Organização concluída": "Organizing finished",
    "Abrir destino": "Open destination",
    "Abrir relatório": "Open report",
    "Ver falhas": "Show failures",
    "Escanear de novo": "Scan again",
    "Relatório: {path}": "Report: {path}",
    "Falhas": "Failures",
    "{n} arquivos tiveram erro ou aviso. A lista completa está no relatório.": (
        "{n} files had an error or warning. The full list is in the report."
    ),
    "Cancelando…": "Cancelling…",
    "Procurando arquivos… {d}": "Finding files… {d}",
    "Lendo metadados… {d} / {t}": "Reading metadata… {d} / {t}",
    "Comparando imagens… {d} / {t}": "Comparing images… {d} / {t}",
    "Organizando… {d} / {t}": "Organizing… {d} / {t}",
    "Ocorreu um erro:\n{m}": "An error occurred:\n{m}",
    "Preparando…": "Preparing…",
    "Pronto": "Ready",
    "Escolha a origem e o destino": "Choose the source and destination",
    "Origem: onde estão as fotos (cartão, pasta do celular…). Destino: onde ficará a biblioteca organizada.": (
        "Source: where the photos are (memory card, phone folder…). Destination: where the "
        "organized library will live."
    ),
    "Pronto para escanear": "Ready to scan",
    "Clique em Escanear para ler as datas dos arquivos da origem.": (
        "Click Scan to read the dates of the files in the source."
    ),
    "itens": "items",
    "item": "item",
    "escaneados": "scanned",
    "de {n}": "of {n}",
    "Vídeo {n}": "Video {n}",
    "Sem data {n}": "No date {n}",
    "Duplicadas {n}": "Duplicates {n}",
    "Reinicie o Photo Organizer para trocar o idioma.": "Restart Photo Organizer to change the language.",
    "<b>Photo Organizer {v}</b><br>Organiza fotos e vídeos por data EXIF/XMP, separa duplicadas e sugere tags.<br><br>Usa ExifTool (Phil Harvey), Qt, OpenCV e ícones Lucide.<br>Tags: YOLOX (Megvii, Apache-2.0, via OpenCV Model Zoo) e SigLIP 2 (Google, Apache-2.0).": (
        "<b>Photo Organizer {v}</b><br>Organizes photos and videos by EXIF/XMP date, sets "
        "duplicates aside and suggests tags.<br><br>Uses ExifTool (Phil Harvey), Qt, OpenCV "
        "and Lucide icons.<br>Tags: YOLOX (Megvii, Apache-2.0, via OpenCV Model Zoo) and "
        "SigLIP 2 (Google, Apache-2.0)."
    ),
    # Tags IA
    "Tags": "Tags",
    "Tags IA": "AI Tags",
    "Tarefa cancelada.": "Task cancelled.",
    "Não foi possível acessar a pasta:": "Could not access the folder:",
    "Nenhuma foto JPEG ou RAW encontrada nessa pasta.": "No JPEG or RAW photos found in this folder.",
    "Gravar as tags em {n} fotos?\n\nElas vão para os sidecars .xmp, somadas às que já existem; os arquivos originais não mudam.": (
        "Write the tags to {n} photos?\n\nThey go into the .xmp sidecars, added to the existing "
        "ones; the original files are not changed."
    ),
    "Fotos com tags gravadas: {n}": "Photos tagged: {n}",
    "Tags gravadas": "Tags written",
    "Analisando fotos… {d} / {t}": "Analyzing photos… {d} / {t}",
    "Gravando tags… {d} / {t}": "Writing tags… {d} / {t}",
    "Nenhuma pasta escolhida": "No folder chosen",
    "Hemisfério Sul": "Southern Hemisphere",
    "Hemisfério Norte": "Northern Hemisphere",
    "Define a estação do ano a partir da data da foto.": "Sets the season from the photo date.",
    "Analisar": "Analyze",
    "Arquivo": "File",
    "Tags sugeridas (editáveis)": "Suggested tags (editable)",
    "Já gravadas": "Already written",
    "Separe as tags por vírgula; apague o texto para não gravar nada nessa foto. As tags vão para o sidecar .xmp (o arquivo original não muda) e somam-se às que já existem.": (
        "Separate tags with commas; clear the text to write nothing for that photo. Tags go "
        "into the .xmp sidecar (the original file is not changed) and are added to the "
        "existing ones."
    ),
    "Escolha uma pasta e clique em Analisar. Cena, objetos, estação e sol são detectados no computador, sem enviar fotos para a internet.": (
        "Choose a folder and click Analyze. Scene, objects, season and sun are detected on "
        "this computer, without sending photos to the internet."
    ),
    "Gravar tags": "Write tags",
    "Pasta das fotos": "Photos folder",
    "{n} fotos analisadas · {k} com tags novas para gravar": (
        "{n} photos analyzed · {k} with new tags to write"
    ),
    "Há uma tarefa em andamento. Cancelar e sair?": "A task is running. Cancel it and exit?",
    # RulesPanel
    "Estrutura de pastas": "Folder structure",
    "Predefinições…": "Presets…",
    "aaaa > mm > dd": "yyyy > mm > dd",
    "aaaa = ano (2026) · aa = 26 · mm = mês (10) · month = Outubro · mon = Out · dd = dia\n'>' separa as pastas · texto entre aspas é literal": (
        "yyyy = year (2026) · yy = 26 · mm = month (10) · month = October · mon = Oct · "
        "dd = day\n'>' separates folders · quoted text is literal"
    ),
    "aaaa · aa · mm · month · mon · dd   ·   > nova pasta": "yyyy · yy · mm · month · mon · dd   ·   > new folder",
    "Tipos de arquivo": "File types",
    "Separar em pasta": "Move to a folder",
    "Duplicadas - Validar": "Duplicates - Review",
    "Critério: imagem parecida tirada no mesmo instante": "Rule: similar image taken at the same moment",
    "Arquivos sem data": "Files without a date",
    "Sem data": "No date",
    "Operação": "Operation",
    "Não há desfazer: cada execução gera um relatório CSV.": "There is no undo: every run writes a CSV report.",
    "Prioridade da data": "Date priority",
    "EXIF DateTimeOriginal": "EXIF DateTimeOriginal",
    "XMP do sidecar (.xmp)": "Sidecar XMP (.xmp)",
    "XMP embutido no arquivo": "XMP embedded in the file",
    "Data do vídeo (QuickTime)": "Video date (QuickTime)",
    "Digite um padrão, por exemplo: aaaa > mm > dd": "Type a pattern, for example: yyyy > mm > dd",
    "Há um nome de pasta vazio.": "A folder name is empty.",
    "Há uma aspa sem fechamento.": "A quote is not closed.",
    'Nomes de pasta não podem ter \\ / : * ? " < > |': 'Folder names cannot contain \\ / : * ? " < > |',
    "Nome de pasta não pode terminar com ponto.": "A folder name cannot end with a period.",
    "Nome reservado pelo Windows (CON, NUL, COM1…).": "Name reserved by Windows (CON, NUL, COM1…).",
    "Padrão inválido.": "Invalid pattern.",
    # Melhorias: data no nome, desmarcados, duplicadas no destino, vídeo
    "LIXEIRA": "RECYCLE BIN",
    "NO DESTINO": "IN DESTINATION",
    "SUBSTITUI": "REPLACES",
    "Incluir selecionados": "Include selected",
    "Deixar selecionados de fora": "Leave selected out",
    "Incluir todos os mostrados": "Include all shown",
    "Deixar todos os mostrados de fora": "Leave all shown out",
    "Marcar todas": "Mark all",
    "Aplica uma escolha a todos os grupos de uma vez.": "Applies one choice to every group at once.",
    "Só as sugeridas": "Suggested only",
    "Volta tudo à sugestão: cópias para a pasta de duplicadas; no destino, fica a de maior resolução.": "Resets everything to the suggestion: copies go to the duplicates folder; in the destination, the higher-resolution file stays.",
    "Selecionar todas (tudo para duplicadas)": "Select all (everything to duplicates)",
    "Nenhuma (não mover; manter as do destino)": "None (don't move; keep the destination files)",
    "Manter a do destino (não copiar nem mover)": "Keep the destination file (don't copy or move)",
    "Substituir a do destino (a antiga vai para a Lixeira)": "Replace the destination file (the old one goes to the Recycle Bin)",
    "manter a do destino": "keep destination",
    "para duplicadas": "to duplicates",
    "substituir": "replace",
    "Já no destino · {action}": "Already in destination · {action}",
    "Fica no destino normal o original (com data e maior). Desmarque o que não for duplicada.": "The original (dated and largest) stays in the normal destination. Uncheck anything that is not a duplicate.",
    "Grupo {i} de {n} · já no destino": "Group {i} of {n} · already in destination",
    "Esta foto da origem já existe no destino. Sugestão: ficar com a de maior resolução e, empatando, a maior.": "This source photo already exists in the destination. Suggestion: keep the higher-resolution one, or the larger file on a tie.",
    "JÁ NO DESTINO": "ALREADY IN DESTINATION",
    "Fica no destino normal (original)": "Stays in the normal destination (original)",
    "sugerido": "suggested",
    "{mp} MP": "{mp} MP",
    "Reproduzir o vídeo": "Play the video",
    "NOME": "NAME",
    "Fora: vai para a Lixeira ao mover": "Left out: goes to the Recycle Bin when moving",
    "Fora: fica onde está": "Left out: stays where it is",
    "Já está no destino": "Already in the destination",
    "Substitui a do destino": "Replaces the destination file",
    "A foto que está lá vai para a Lixeira.": "The photo there goes to the Recycle Bin.",
    "Vídeo · clique ▶ para assistir": "Video · click ▶ to watch",
    "Não foi possível reproduzir este vídeo.\n{m}": "Could not play this video.\n{m}",
    "Nenhum arquivo para copiar ou mover.": "No files to copy or move.",
    "{n} substituem fotos do destino; as antigas vão para a Lixeira.": "{n} replace destination photos; the old ones go to the Recycle Bin.",
    "{n} desmarcados saem da origem e vão para a Lixeira.": "{n} unchecked files leave the source and go to the Recycle Bin.",
    "Substituíram a do destino: {n}": "Replaced the destination file: {n}",
    "Já existiam no destino (ficou a de lá): {n}": "Already in the destination (kept that one): {n}",
    "Deixados de fora: {n}": "Left out: {n}",
    "Deixados de fora e enviados para a Lixeira: {n}": "Left out and sent to the Recycle Bin: {n}",
    "Procurando no destino… {d}": "Searching the destination… {d}",
    "Lendo o destino… {d} / {t}": "Reading the destination… {d} / {t}",
    "Nome {n}": "Name {n}",
    "Mandar os desmarcados para a Lixeira": "Send unchecked files to the Recycle Bin",
    "Só ao mover: os arquivos que você desmarcou na lista saem da origem e vão para a Lixeira do Windows. Em pendrive ou rede não há Lixeira e eles ficam.": "Only when moving: the files you unchecked in the list leave the source and go to the Windows Recycle Bin. USB drives and network folders have no Recycle Bin, so they stay.",
    "5  Data no nome do arquivo (IMG_20261027…)": "5  Date in the file name (IMG_20261027…)",
    "Só para arquivos sem nenhuma das datas acima. Sem data no nome, vão para a pasta de arquivos sem data.": "Only for files with none of the dates above. With no date in the name either, they go to the undated folder.",
}


def main() -> None:
    sources = sorted(str(p) for p in UI.glob("*.py"))
    subprocess.run(
        [str(BIN / "pyside6-lupdate"), *sources, "-ts", str(TS), "-no-obsolete",
         "-source-language", "pt_BR", "-target-language", "en"],
        check=True,
    )  # fmt: skip
    tree = ET.parse(TS)
    missing = []
    for message in tree.getroot().iter("message"):
        source = message.findtext("source") or ""
        translation = message.find("translation")
        if source in EN:
            translation.text = EN[source]
            translation.attrib.pop("type", None)
        else:
            missing.append(source)
    tree.write(TS, encoding="utf-8", xml_declaration=True)
    subprocess.run([str(BIN / "pyside6-lrelease"), str(TS), "-qm", str(QM)], check=True)
    if missing:
        sys.exit("Sem tradução:\n" + "\n".join(f"  {m!r}" for m in missing))
    print(f"{QM.relative_to(ROOT)} gerado.")


if __name__ == "__main__":
    main()
