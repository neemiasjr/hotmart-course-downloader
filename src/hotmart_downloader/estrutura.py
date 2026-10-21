"""Metadados das aulas (vídeos, anexos e links) a partir da API."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from .api import _get_page_json
from .nomes import _nome_arquivo_seguro


def _duracao_esperada_midia(video, page):
    for key in ('duration', 'mediaDuration'):
        try:
            val = video.get(key)
            if val is not None and float(val) > 0:
                return float(val)
        except (TypeError, ValueError):
            pass
    code = video.get('mediaCode')
    for midia in page.get('medias') or []:
        if code and midia.get('code') == code:
            try:
                val = midia.get('duration')
                if val is not None and float(val) > 0:
                    return float(val)
            except (TypeError, ValueError):
                pass
    try:
        val = page.get('mediaDuration')
        if val is not None and float(val) > 0:
            return float(val)
    except (TypeError, ValueError):
        pass
    return None


def _montar_registro_aula(item, aula_payload):
    page = item['page']
    registro = [
        page['pageOrder'],
        (page.get('name') or '').strip(),
        page['hash'],
        {'videos': []},
        {'anexos': []},
        {'links': []},
    ]
    try:
        for video in aula_payload['mediasSrc']:
            entrada = [
                _nome_arquivo_seguro(video['mediaName']),
                video['mediaCode'],
                video['mediaSrcUrl'],
            ]
            dur = _duracao_esperada_midia(video, page)
            if dur:
                entrada.append(dur)
            registro[3]['videos'].append(entrada)
    except KeyError:
        pass
    try:
        for anexo in aula_payload['attachments']:
            registro[4]['anexos'].append([
                anexo['fileMembershipId'],
                _nome_arquivo_seguro(anexo['fileName']),
            ])
    except KeyError:
        pass
    try:
        for link in aula_payload['complementaryReadings']:
            registro[5]['links'].append([
                _nome_arquivo_seguro(link['articleName']),
                link['articleUrl'],
            ])
    except KeyError:
        pass
    return item, registro


def _carregar_estrutura_aulas(authMart, plano_filtrado, api_paralelo):
    """Busca metadados das aulas em paralelo (só API, ainda sequencial por índice)."""
    resultados = [None] * len(plano_filtrado)

    def _fetch(pos_item):
        pos, item = pos_item
        payload = _get_page_json(authMart, item['hash'])
        return pos, _montar_registro_aula(item, payload)

    if len(plano_filtrado) <= 1 or api_paralelo <= 1:
        for pos, item in enumerate(plano_filtrado):
            _, par = _fetch((pos, item))
            resultados[pos] = par
        return resultados

    workers = min(api_paralelo, len(plano_filtrado))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_fetch, (pos, item)) for pos, item in enumerate(plano_filtrado)]
        for fut in as_completed(futures):
            pos, par = fut.result()
            resultados[pos] = par
    return resultados


def _contar_aulas(estrutura):
    return sum(len(aulas_lista) for modulo in estrutura.values() for aulas_lista in modulo.values())
