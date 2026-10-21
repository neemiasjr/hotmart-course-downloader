"""Decide se vídeos, anexos e aulas já estão baixados."""

import glob
import os

from .caminhos import (
    _arquivo_pronto,
    _caminho_anexo_aula,
    _caminho_descricao_aula,
    _caminho_gdrive_aula,
    _caminho_links_aula,
    _caminho_video_no_topico,
    _caminho_video_padrao,
    _pasta_aula_legada,
)
from .externos import extrair_google_drive_urls
from .midia import _dimensoes_video_local, _duracao_mp4_local, _mp4_valido_ffprobe
from .nomes import _nome_arquivo_corresponde_aula, _nome_arquivo_seguro, _prefixo_aula, slugify


def _duracao_local_suficiente(path, duracao_esperada, fracao_minima=0.90):
    """False se o arquivo existe mas é claramente mais curto que a aula no site."""
    if not duracao_esperada or duracao_esperada < 60:
        return True
    local = _duracao_mp4_local(path)
    if local is None:
        return False
    return local >= float(duracao_esperada) * fracao_minima


def _duracao_esperada_registro_video(video_row):
    if not video_row or len(video_row) < 4:
        return None
    try:
        val = float(video_row[3])
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def _video_arquivo_pronto(
    path, verificar_completo=False, duracao_esperada=None, fracao_duracao_minima=0.90,
):
    if not path.lower().endswith('.mp4'):
        return _arquivo_pronto(path)
    if verificar_completo:
        if not _mp4_valido_ffprobe(path):
            return False
        if not _duracao_local_suficiente(path, duracao_esperada, fracao_duracao_minima):
            return False
    return _arquivo_pronto(path)


def _video_ja_baixado(
    folder_topico, page_order, lesson_name, indice,
    media_name=None, total_videos=1, verificar_completo=False,
    duracao_esperada=None, fracao_duracao_minima=0.90,
    qualidade_desejada=0,
):
    """
    True se o vídeo já existe (pasta do tópico ou layout antigo por aula).
    Com verificar_completo, usa ffprobe (ignora .mp4 truncado/corrompido).
    """

    def _pronto(path):
        if not _video_arquivo_pronto(
            path, verificar_completo, duracao_esperada, fracao_duracao_minima,
        ):
            return False
        if qualidade_desejada:
            _, vh = _dimensoes_video_local(path)
            if vh and vh < int(qualidade_desejada * 0.75):
                return False
        return True

    candidatos = [
        _caminho_video_no_topico(
            folder_topico, page_order, lesson_name, indice, total_videos=total_videos,
        ),
    ]
    legado = _pasta_aula_legada(folder_topico, page_order, lesson_name)
    candidatos.append(_caminho_video_padrao(legado, indice))
    if media_name:
        safe = _nome_arquivo_seguro(media_name)
        if safe:
            candidatos.append(os.path.join(folder_topico, f'{slugify(safe)}.mp4'))
            candidatos.append(os.path.join(legado, f'{slugify(safe)}.mp4'))
            candidatos.append(os.path.join(
                folder_topico,
                f'{_prefixo_aula(page_order, lesson_name)} - {slugify(safe)}.mp4',
            ))

    vistos = set()
    for path in candidatos:
        path = os.path.normpath(path)
        if path in vistos:
            continue
        vistos.add(path)
        if _pronto(path):
            return True, path

    if total_videos == 1:
        for path in glob.glob(os.path.join(folder_topico, '*.mp4')):
            base = os.path.basename(path)
            if not _nome_arquivo_corresponde_aula(base, page_order, lesson_name):
                continue
            if _pronto(path):
                return True, path
        for path in glob.glob(os.path.join(legado, '*.mp4')):
            base = os.path.basename(path)
            if not _nome_arquivo_corresponde_aula(base, page_order, lesson_name):
                continue
            if _pronto(path):
                return True, path

    return False, None


def _anexo_ja_baixado(path):
    return _arquivo_pronto(path, min_bytes=1)


def _aula_ja_completa_na_pasta(folder_topico, aula, verificar_completo=False):
    """Pula a aula inteira se vídeos, anexos e materiais da descrição já estão na pasta."""
    page_order, lesson_name = aula[0], aula[1]
    descricao_path = _caminho_descricao_aula(folder_topico, page_order, lesson_name)
    legado = _pasta_aula_legada(folder_topico, page_order, lesson_name)
    descricao_legada = os.path.join(legado, 'descricao.html')
    videos = aula[3]['videos']
    tem_algo = False

    if videos:
        tem_algo = True
        total = len(videos)
        for indice, item in enumerate(videos, start=1):
            pronto, _ = _video_ja_baixado(
                folder_topico, page_order, lesson_name, indice,
                item[0], total_videos=total,
                verificar_completo=verificar_completo,
                duracao_esperada=_duracao_esperada_registro_video(item),
            )
            if not pronto:
                return False
    else:
        mp4_prontos = [
            p for p in glob.glob(os.path.join(folder_topico, '*.mp4'))
            if _nome_arquivo_corresponde_aula(os.path.basename(p), page_order, lesson_name)
            and _video_arquivo_pronto(p, verificar_completo)
        ]
        if not mp4_prontos:
            mp4_prontos = [
                p for p in glob.glob(os.path.join(legado, '*.mp4'))
                if _nome_arquivo_corresponde_aula(os.path.basename(p), page_order, lesson_name)
                and _video_arquivo_pronto(p, verificar_completo)
            ]
        if mp4_prontos:
            tem_algo = True

    if aula[4]['anexos']:
        tem_algo = True
        for anexo in aula[4]['anexos']:
            destino = _caminho_anexo_aula(folder_topico, page_order, lesson_name, anexo[1])
            legado_anexo = os.path.join(legado, 'Materiais', anexo[1])
            if not _anexo_ja_baixado(destino) and not _anexo_ja_baixado(legado_anexo):
                return False

    if aula[5]['links']:
        tem_algo = True
        links_path = _caminho_links_aula(folder_topico, page_order, lesson_name)
        legado_links = os.path.join(legado, 'Materiais', 'links.txt')
        if not _arquivo_pronto(links_path, min_bytes=1) and not _arquivo_pronto(legado_links, min_bytes=1):
            return False

    if not tem_algo:
        return False

    if _arquivo_pronto(descricao_path, min_bytes=32):
        descricao_ler = descricao_path
    elif _arquivo_pronto(descricao_legada, min_bytes=32):
        descricao_ler = descricao_legada
    else:
        return False

    try:
        with open(descricao_ler, encoding='utf-8') as desc_f:
            content_html = desc_f.read()
    except OSError:
        return False

    gdrive = extrair_google_drive_urls(content_html)
    if gdrive:
        tem_algo = True
    for file_id, _, _ in gdrive:
        gdrive_path = _caminho_gdrive_aula(folder_topico, page_order, lesson_name, file_id)
        legado_g = os.path.join(legado, 'Materiais', f'gdrive_{file_id}.pdf')
        if not _anexo_ja_baixado(gdrive_path) and not _anexo_ja_baixado(legado_g):
            return False

    return tem_algo
