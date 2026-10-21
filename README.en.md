# Hotmart Downloader

[Português](README.md) | **English**

Script to download Hotmart courses. It downloads videos, PDFs and embedded attachments.

## Origin

Based on the gist by [@juvenal](https://gist.github.com/juvenal/2d9a822325769d30c45c635fbf388c1b), with improvements for downloading PDFs embedded from Google Drive.

## Why is the subdomain manual?

The Hotmart API changed (2026) and the `check_token` endpoint now returns an empty `resources: []`, even when you have purchased courses. That's why the script needs you to enter the course subdomains manually in `config_cursos.py`. It's a workaround until another way to list courses automatically is found.

## Requirements

- Python 3.6+
- FFMPEG (must be in the system PATH)
- A stable connection if you are downloading videos

## Quick start

After setting up `config_cursos.py` (step 2 below), use the launcher script. It creates the virtual environment (`.venv`), installs dependencies whenever `requirements.txt` changes, checks FFmpeg and opens the program:

| System | How to start |
|---|---|
| macOS | double-click `iniciar.command` or run `./iniciar.sh` in the terminal |
| Linux | `./iniciar.sh` |
| Windows | double-click `iniciar.bat` |

On macOS, if FFmpeg is not installed and Homebrew is available, the script offers to install it with `brew install ffmpeg`. The first time you open `iniciar.command`, macOS may block it: right-click it → **Open**.

## How to use

1. Install the dependencies:
```bash
pip install -r requirements.txt
```

2. Edit `config_cursos.py` with the subdomain and, on the new Club, the product ID from the URL:
```python
CURSOS_SUBDOMINIOS = ["your-subdomain"]
CURSOS_PRODUCT_IDS = {
    "your-subdomain": "123456",  # .../products/123456
}
```

**How to find the subdomain and product ID:**
1. Go to https://sun.hotmart.com/minhas-compras
2. Click "Acessar" (Access) on the course
3. In the URL: `https://hotmart.com/pt-BR/club/YOUR-SUBDOMAIN/products/123456`
4. Subdomain = `YOUR-SUBDOMAIN` | Product ID = `123456`

3. Authentication (Bearer token from the browser — password login from the script usually fails):
```bash
export HOTMART_TOKEN='paste_the_JWT_copied_from_DevTools'
python hotmark.py
```

In Chrome: open the course → F12 → Network → F5 → filter by `consumption-gateway` or `api-club` → `status` or `navigation` request → copy **Authorization** (the whole JWT, without line breaks). **Do not** paste the token in chats or e-mails.

4. Run the script (if you didn't export the token, it asks for it):
```bash
python hotmark.py
```

## What it downloads

- Videos (Hotmart, Vimeo, YouTube)
- Regular attachments (PDFs, zip files, etc.)
- PDFs embedded from Google Drive (these used to be hidden)
- Further reading links
- Lesson descriptions

Everything is organized by **topic (module)**: videos in the topic folder (`2 - Lesson name.mp4`), descriptions in `descricoes/` and attachments in `Materiais/`.

Names follow what is shown on the site, with accents and capitalization, for example `Cursos/Cozinhar é bom demais!/1 - Comece por aqui/`. Only characters the file system doesn't accept are replaced (`|`, `/`, `\` and `:` become ` - `; `<`, `>`, `"`, `?` and `*` are removed). The course name comes from your Hotmart purchase list; to use a different one, set `CURSOS_NOMES` in `config_cursos.py`.

Downloads made by previous versions (folders like `1_comece-por-aqui` and files like `2.nome-da-aula.mp4`) are renamed to the new pattern automatically on the next run, without downloading anything again.

## Download only one topic, lesson or video

After you choose the course, the script asks:

1. **Topics (modules)** — `Enter` = all; `5` = only the 5th; `1,3` or `2-4`
2. **Lessons** — numbered list within the chosen topics; same syntax (`3`, `1,5`, `2-4`)
3. **A single video** — in the lessons question: `5:v2` (lesson 5, 2nd video) or `5:v` (shows the list of videos)

You can set these in `config_cursos.py` so it doesn't ask:

```python
TOPICOS_INDICES = 5          # or [1, 3] or "2-4"
AULAS_INDICES = [2, 5]       # optional
AULA_VIDEO = "5:v2"          # or {5: 2}
```

## Why is it slow?

The time is almost always **video size × quality × internet speed**. The script downloads the HLS stream with ffmpeg (one video at a time by default), and it used to pause for 1s and run ffprobe on every lesson.

To go **faster**:

1. **Lower quality** — the biggest gain: `QUALIDADE_VIDEO = 480` or `720` in `config_cursos.py`
2. **Parallel** — `DOWNLOAD_PARALELO = 2` (or `3` if your connection can handle it; don't overdo it to avoid being blocked)
3. **No ffprobe** — already the default (`MEDIR_DURACAO_VIDEO = False`); turn it on only if you want a more accurate % bar
4. **Smaller scope** — download only one topic/lesson (`TOPICOS_INDICES`, `AULAS_INDICES`)

## Video quality

When downloading, the script asks for the maximum quality (360p, 480p, 720p, 1080p or maximum). Lower qualities download faster and take less disk space.

To skip the question, set in `config_cursos.py`:
```python
QUALIDADE_VIDEO = 720  # or 360, 480, 1080, 0 (maximum)
DOWNLOAD_PARALELO = 2  # optional: 2–3 simultaneous Hotmart downloads
```

## Some details

- If an attachment download fails, it retries 3 times before giving up
- Google Drive PDFs are saved as `gdrive_xxxxx.pdf` in the Materiais folder
- If you already downloaded something, it won't download it again (saves time)
- You can stop with Ctrl+C and continue later: the script saves progress and asks whether you want to resume
- Shows the overall lesson progress and a live bar for each video (%, time and size)
- Incomplete videos (`.part.mp4`) are downloaded again; only finished files are skipped
- Logs everything it does so you can follow along

## Project structure

The code lives in `src/hotmart_downloader/`. The root only holds `hotmark.py` (entry point), the `iniciar.*` scripts, `config_cursos.py` and the documentation. Standalone utilities are in `scripts/` (for example, `python scripts/corrigir_sync_pasta.py Cursos` fixes audio sync and smoothness of videos already downloaded) and tests are in `tests/` (`python -m unittest`). The module map is in [docs/estrutura-do-projeto.md](docs/estrutura-do-projeto.md) (Portuguese).

## Warnings

- Use it only for courses you bought
- Some courses are large, it will take a while
- You need plenty of disk space

## Problems?

If it doesn't work:
1. Check that FFMPEG is installed (`ffmpeg -version` in the terminal)
2. Check that your e-mail/password is correct
3. Look at `log.txt` to see the error

---

Educational project. Use responsibly.
