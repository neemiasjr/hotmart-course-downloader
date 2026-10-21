#!/usr/bin/env bash
# Inicia o Hotmart Course Downloader (macOS / Linux).
# Prepara o ambiente virtual, instala dependências quando o requirements.txt
# muda, confere o FFmpeg e executa o hotmark.py.
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
PYTHON="$VENV/bin/python"
CARIMBO="$VENV/.requirements.sha256"

erro() {
    printf '\nERRO: %s\n' "$*" >&2
    exit 1
}

encontrar_python() {
    local cmd
    for cmd in python3 python; do
        if command -v "$cmd" >/dev/null 2>&1 \
            && "$cmd" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
            echo "$cmd"
            return 0
        fi
    done
    return 1
}

if ! "$PYTHON" -c 'import sys' >/dev/null 2>&1; then
    PY_SISTEMA=$(encontrar_python) || erro "Python 3.8+ não encontrado.
Instale em https://www.python.org/downloads/ (macOS: brew install python3)."
    echo "Criando ambiente virtual em $VENV..."
    "$PY_SISTEMA" -m venv "$VENV" || erro "Não foi possível criar o ambiente virtual."
    rm -f "$CARIMBO"
fi

HASH_REQ=$("$PYTHON" -c 'import hashlib; print(hashlib.sha256(open("requirements.txt", "rb").read()).hexdigest())')
if [ ! -f "$CARIMBO" ] || [ "$(cat "$CARIMBO")" != "$HASH_REQ" ]; then
    echo "Instalando dependências (requirements.txt)..."
    "$PYTHON" -m pip install --disable-pip-version-check -q -r requirements.txt \
        || erro "Falha ao instalar as dependências. Verifique a internet e tente de novo."
    echo "$HASH_REQ" > "$CARIMBO"
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    echo "FFmpeg não encontrado (necessário para baixar os vídeos)."
    if [ "$(uname)" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
        read -r -p "Instalar agora com 'brew install ffmpeg'? [S/n] " resposta || resposta="n"
        case "$resposta" in
            [nN]*) erro "Instale o FFmpeg e rode o script de novo." ;;
            *) brew install ffmpeg || erro "Falha ao instalar o FFmpeg." ;;
        esac
    else
        erro "Instale o FFmpeg e rode o script de novo.
  macOS:          brew install ffmpeg
  Ubuntu/Debian:  sudo apt install ffmpeg
  Fedora:         sudo dnf install ffmpeg"
    fi
fi

[ -f config_cursos.py ] || erro "config_cursos.py não encontrado. Veja o README para configurar seus cursos."

exec "$PYTHON" hotmark.py "$@"
