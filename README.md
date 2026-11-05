# Photo Organizer

[![Release](https://img.shields.io/github/v/release/caebrida/photo-organizer)](https://github.com/caebrida/photo-organizer/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
![Windows 10/11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4)
![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB)

Sorts photos and videos into folders by the date they were taken, sets duplicates aside for you to review, and suggests tags for each photo with an AI model that runs on your own computer.

Point it at a memory card, a phone folder, or an old hard drive, pick a destination, and you see the full plan before a single file moves. Nothing is overwritten, and every run leaves a CSV report with the source and destination of each file.

```
Destination\
├── 2026\10\27\DSC0001.JPG
├── 2026\10\27\RAW\DSC0001.ARW + DSC0001.xmp
├── 2026\10\27\Video\C0031.MP4
├── No date\IMG-20261027-WA0003.jpg
└── Duplicates - Review\2026\10\27\DSC0001.JPG
```

## Installation

Download one of the two builds from the [releases page](https://github.com/caebrida/photo-organizer/releases/latest). Both come with everything included: ExifTool, the AI models, and the translations.

| File | Best for |
|---|---|
| `PhotoOrganizer-Setup-<version>.exe` | Installer. Starts faster and adds a Start menu shortcut. Needs no admin rights, and a new version upgrades the old one in place. |
| `PhotoOrganizer-portable.exe` | A single file, no install. Runs from any folder or USB drive. |

The executables are not signed, so Windows SmartScreen may warn you the first time. Click **More info**, then **Run anyway**.

Requirements: Windows 10 or 11, 64-bit.

## Usage

1. **Choose the source** (`Ctrl+O`): the folder with your photos. Subfolders are included.
2. **Scan** (`F5`): the app reads each file's date and looks for duplicates. The list shows how many files have a date and where it came from.
3. **Choose the destination** (`Ctrl+D`) and adjust the rules in the side panel. The plan is rebuilt after every change and appears in the list before you confirm.
4. **Organize** (`Ctrl+Enter`): confirm move or copy. When it finishes, the app shows a summary and offers to open the report, show failures, or open the destination.

The interface follows the Windows language (English or Portuguese). Switch it under **View > Language**.

## Features

### Sort by date

Each file's date comes from the first source that has one, in this order:

1. The file's own EXIF (`DateTimeOriginal` with milliseconds, then `CreateDate`)
2. The XMP sidecar (the `.xmp` next to the file)
3. XMP embedded in the file
4. The video date (QuickTime or RIFF)

A file with none of these dates goes to the `No date` folder. The file's modified date is never used, because copies and downloads change it.

Supported types:

| Type | Extensions | Goes to |
|---|---|---|
| Photo | `.jpg`, `.jpeg` | the date folder |
| RAW | `.arw`, `.cr2`, `.cr3`, `.crw`, `.dng` | a `RAW` subfolder |
| Video | `.mp4`, `.mov`, `.avi` | a `Video` subfolder |

Each type can be turned off in the **File types** panel. A Lightroom or Bridge `.xmp` sidecar always travels with its file and gets the same name.

### Folder structure

Type the pattern in the **Folder structure** field. `>` starts a subfolder:

| Pattern | Result for Oct 27, 2026 |
|---|---|
| `yyyy > mm > dd` | `2026\10\27` |
| `yyyy > month` | `2026\October` |
| `yyyy > mm - month > dd` | `2026\10 - October\27` |
| `yyyy-mm-dd` | `2026-10-27` |
| `"Trip" > yyyy > mon` | `Trip\2026\Oct` |

| Code | Meaning |
|---|---|
| `yyyy` or `aaaa` | 4-digit year |
| `yy` or `aa` | 2-digit year |
| `mm` | 2-digit month |
| `month` | month name, in the interface language |
| `mon` | short month name |
| `dd` | 2-digit day |

A word becomes a code only when it is made entirely of codes: `yyyymmdd` becomes `20261027`, but `Monday` stays `Monday`. Text in quotes is never treated as a code. The field warns you right away if a folder name isn't valid on Windows.

You can also rename the `No date` and `Duplicates - Review` folders.

### Duplicates

The app compares what the photos look like (a perceptual hash), so it finds exact copies as well as resized or re-exported versions. Two photos are duplicates when:

- they are the same type (the RAW + JPEG pair a camera saves together never counts as a duplicate);
- the images are nearly identical;
- they were taken in the same second, which keeps burst shots from being flagged.

An undated copy, like the ones WhatsApp creates, links only to the dated photo it most resembles. Videos count as duplicates only when they are exact copies.

In each group, the original photo (dated and largest) stays in the regular destination, and the others go to `Duplicates - Review`, under the same date structure. The **Duplicates** tab shows each group side by side, with file sizes and dates, and you choose photo by photo which ones go to that folder. The app never deletes duplicates.

Comparison results are cached, so scanning the same folder again is fast.

### AI Tags

The **AI Tags** tab analyzes a folder of photos (JPEG and RAW) and suggests up to five scene and content tags for each one, plus these:

- **People**: `person`, or `group of people` for three or more
- **Setting**: `outdoors` or `indoors`, and `sunny` on a sunny day
- **Season**, from the photo's date and the hemisphere you pick

The scene and content vocabulary has 70 tags, such as beach, mountain, waterfall, wedding, birthday, christmas, food, selfie, dog, and sunset. Tags are written in the interface language. When the model isn't sure, it doesn't suggest the tag.

You can edit the suggestions before writing them. When you click **Write tags**:

- the tags go into the `.xmp` sidecar (`dc:subject`), which Lightroom, Bridge, digiKam, and Windows read as keywords;
- the original file is never changed;
- tags the photo already has, in the sidecar or inside the file, are kept and not repeated, ignoring case.

Analysis runs on your computer. No photo is sent to the internet.

### File safety

- **Plan first.** No file is touched until you confirm the full plan.
- **Nothing is overwritten.** If a name already exists at the destination, the file gets `_1`, `_2`, and so on, and its sidecar gets the same suffix.
- **Verified copies.** When copying, or moving to another drive, the app rereads the copy and checks its hash before giving it the final name. The source is deleted only after that.
- **Files already in the right place** are skipped.
- **Long paths** (over 260 characters) work.
- **CSV report** in the destination folder, written file by file: status, operation, source, destination, sidecars, date, date source, type, duplicate, and error. It uses `;` as the separator, which Excel opens directly in Portuguese and most European locales.

There is no undo. The report is the record of where each file went.

## Running from source

You need [uv](https://docs.astral.sh/uv/) and Git.

```bash
git clone https://github.com/caebrida/photo-organizer.git
cd photo-organizer
uv sync
```

ExifTool and the AI models are not stored in the repository. Download them once:

```bash
uv run python scripts/fetch_exiftool.py
```

```bash
uv run --no-project --python 3.12 --with torch --with transformers --with sentencepiece --with protobuf --with onnx --with numpy --with opencv-python-headless --with truststore python scripts/fetch_models.py
```

The second command downloads SigLIP 2 (about 1.5 GB, cached in `%LOCALAPPDATA%\photo-organizer\hf`) and converts it to ONNX. torch is used only in this step, never by the app. Without the models, only the AI Tags tab is unavailable. Both scripts check the SHA-256 of everything they download.

Then:

```bash
uv run python -m photo_organizer
```

<details>
<summary><strong>Tests and lint</strong></summary>

```bash
uv run pytest
```

```bash
uv run ruff check .
```

Tests that need ExifTool, the models, or sample photos in `tests/samples` are skipped when those are missing.

</details>

<details>
<summary><strong>Building the executables</strong></summary>

Install [Inno Setup 6](https://jrsoftware.org/isinfo.php) once (without it, only the portable build is produced):

```bash
winget install JRSoftware.InnoSetup
```

The build runs in a separate environment with only the app's dependencies and PyInstaller. In PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\photo-organizer\build-venv"
uv run --no-dev --group build python scripts/build_exe.py
```

This produces `dist\PhotoOrganizer-portable.exe` and `dist\PhotoOrganizer-Setup-<version>.exe`.

If the project lives in a OneDrive folder and uv fails with a hardlink error, set `UV_LINK_MODE=copy`.

</details>

<details>
<summary><strong>Translation</strong></summary>

The interface is written in Portuguese. The English translation lives in the `EN` table in `scripts/build_translations.py`. After changing any interface text, run:

```bash
uv run python scripts/build_translations.py
```

The script lists new untranslated texts and exits with an error until all of them are in the table.

</details>

<details>
<summary><strong>Project layout</strong></summary>

```
photo_organizer/
├── core/       scanning, dates, duplicates, plan, execution, and report (no UI)
├── tagging/    AI models, vocabulary, and XMP writing
├── ui/         PySide6 interface
├── i18n/       English translation
└── resources/  ExifTool and models, downloaded by the scripts
scripts/        ExifTool and model downloads, build, and translation
tests/          pytest tests
```

</details>

## Third-party components

The executable bundles these components, each under its own license:

| Component | Used for | License |
|---|---|---|
| [ExifTool](https://exiftool.org/) | reading metadata and writing XMP | Artistic License or GPL |
| [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/) | interface | LGPL v3 |
| [OpenCV](https://opencv.org/) | images and running the models | Apache 2.0 |
| [SigLIP 2](https://huggingface.co/google/siglip2-base-patch16-224) (Google) | scene and content tags | Apache 2.0 |
| [YOLOX-s](https://huggingface.co/opencv/object_detection_yolox) (OpenCV Model Zoo) | people detection | Apache 2.0 |
| [PyExifTool](https://github.com/sylikc/pyexiftool) | talking to ExifTool | GPL v3+ or BSD |

## License

[MIT](LICENSE) © 2026 caebrida
