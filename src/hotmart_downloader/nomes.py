"""Nomes de pastas e arquivos (padrão atual e slug legado)."""

import os
import re
import unicodedata


def slugify(value, allow_unicode=False):
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())
    return re.sub(r'[-\s]+', '-', value).strip('-_')


def _nome_arquivo_corresponde_aula(basename, page_order, lesson_name):
    """Reconhece vídeo na raiz do módulo (layout achatado ou renomeado)."""
    base = unicodedata.normalize('NFC', basename).lower()
    if '.part.' in base or base.endswith('.part'):
        return False
    for alvo in (
        _prefixo_aula(page_order, lesson_name).lower(),
        _prefixo_aula_legado(page_order, lesson_name),
    ):
        if base.startswith(alvo):
            return True
    slug_aula = slugify(lesson_name)
    slug_arq = slugify(os.path.splitext(basename)[0])
    if slug_aula and len(slug_aula) >= 8 and slug_aula in slug_arq:
        return True
    return False


def _nome_arquivo_seguro(nome):
    return re.sub(r'[<>:"/\\|?*]', '', (nome or '')).strip()


_NOMES_RESERVADOS_WINDOWS = frozenset(
    ['CON', 'PRN', 'AUX', 'NUL']
    + [f'COM{i}' for i in range(1, 10)]
    + [f'LPT{i}' for i in range(1, 10)]
)


NOME_MAX_CARACTERES = 120


def _nome_fiel(nome, max_len=NOME_MAX_CARACTERES):
    """
    Nome legível para pasta/arquivo, fiel ao título original (acentos,
    maiúsculas e espaços). Só troca o que o sistema de arquivos não aceita:
    | / \\ : viram ' - ' e < > " ? * são removidos.
    """
    texto = unicodedata.normalize('NFC', str(nome or ''))
    texto = re.sub(r'[\x00-\x1f\x7f]', '', texto)
    texto = re.sub(r'\s*[|/\\:]\s*', ' - ', texto)
    texto = re.sub(r'[<>"?*]', '', texto)
    texto = re.sub(r'\s+', ' ', texto)
    texto = re.sub(r'(?:\s-)+\s', ' - ', texto)
    texto = texto.strip(' .-')
    if max_len and len(texto) > max_len:
        texto = texto[:max_len].rstrip(' .-')
    if texto.split('.')[0].upper() in _NOMES_RESERVADOS_WINDOWS:
        texto += '_'
    return texto


def _prefixo_aula(page_order, lesson_name):
    return f"{page_order} - {_nome_fiel(lesson_name)}"


def _prefixo_aula_legado(page_order, lesson_name):
    """Prefixo em slug usado até a v1.1.2 (ex.: 8.yakissoba)."""
    return f"{slugify(str(page_order))}.{slugify(_nome_arquivo_seguro(lesson_name))}"


def _nome_pasta_topico(module_order, module_name):
    return f"{module_order} - {_nome_fiel(module_name)}"


def _nome_pasta_topico_legado(module_order, module_name):
    return f"{slugify(str(module_order))}_{slugify(_nome_arquivo_seguro(module_name))}"


def _sanitizar_nome_curso(nome):
    return re.sub(r'[<>:"/\\|?*]', '', str(nome)).strip()
