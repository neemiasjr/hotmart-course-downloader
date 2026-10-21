# Project structure

[Português](estrutura-do-projeto.md) | **English**

```
hotmark.py                 entry point (python hotmark.py)
iniciar.sh / .command / .bat
config_cursos.py           user configuration
requirements.txt
src/hotmart_downloader/    program code
scripts/                   standalone utilities
tests/                     automated tests
docs/                      documentation
```

The root `hotmark.py` only adds `src/` to the import path and calls
`hotmart_downloader.cli.main()`. The `iniciar.*` scripts still run
`hotmark.py`, so the way to use the program hasn't changed.

## Modules (`src/hotmart_downloader/`)

The flow starts in `cli.py`, which authenticates (`auth.py`) and calls
`listacursos` in `curso.py`. That's where the download steps live: choose the
course, define the scope, build the lesson structure and process each lesson.

| Module | Responsibility |
|---|---|
| `cli.py` | `main()`: login and the message shown when interrupted with Ctrl+C |
| `auth.py` | browser Bearer token or e-mail/password |
| `curso.py` | main flow and processing of each lesson |
| `selecao.py` | questions and parsing of quality, topics, lessons and videos |
| `estrutura.py` | lesson metadata (videos, attachments, links) fetched in parallel |
| `api.py` | Club API calls, navigation, course name and page cache |
| `hls.py` | HLS variant selection and Hotmart video download |
| `ffmpeg.py` | runs ffmpeg with a progress bar and stall detection |
| `midia.py` | ffprobe, duration, audio sync and smoothness fixes |
| `externos.py` | YouTube/Vimeo (yt-dlp or youtube_dl) and Google Drive PDFs |
| `materiais.py` | attachments, Google Drive PDFs and links of each lesson |
| `verificacao.py` | decides whether a video, attachment or lesson is already complete in the folder |
| `caminhos.py` | output paths and `.part` files |
| `nomes.py` | names faithful to the site and the old slug pattern |
| `migracao.py` | renames folders and files from previous versions |
| `progresso.py` | `.progress.json` to resume downloads |
| `config.py` | reads `config_cursos.py` with default values |
| `console.py` | file log and terminal output |

## Utilities (`scripts/`)

Run them from the project root:

- `python scripts/corrigir_sync_pasta.py Cursos` fixes audio sync and
  smoothness of videos already downloaded (`--dry-run` only lists them).
- `python scripts/achatar_videos_modulo.py <module folder>` moves videos from
  lesson subfolders (old layout) into the module folder.

## Tests

```bash
python -m unittest
```
