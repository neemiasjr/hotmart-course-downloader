"""Arquivo .progress.json para retomar downloads."""

import datetime
import json
import os


PROGRESS_FILE = '.progress.json'


def _progress_path(first_folder):
    return os.path.join(first_folder, PROGRESS_FILE)


def _carregar_progresso(first_folder):
    path = _progress_path(first_folder)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _salvar_progresso(first_folder, data):
    path = _progress_path(first_folder)
    payload = dict(data)
    payload['atualizado_em'] = datetime.datetime.today().replace(microsecond=0).isoformat()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
