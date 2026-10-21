"""Caminhos de saída dentro da pasta do tópico e arquivos temporários."""

import os

from .nomes import _prefixo_aula, _prefixo_aula_legado, slugify


def _arquivo_pronto(path, min_bytes=1024):
    """True se o arquivo existe e parece completo (não vazio / não parcial)."""
    try:
        return os.path.isfile(path) and os.path.getsize(path) >= min_bytes
    except OSError:
        return False


def _pasta_aula_legada(folder_topico, page_order, lesson_name):
    """Layout antigo: subpasta por aula (compatível ao pular re-download)."""
    return os.path.join(folder_topico, _prefixo_aula_legado(page_order, lesson_name))


def _caminho_video_no_topico(folder_topico, page_order, lesson_name, indice_video, total_videos=1):
    """Vídeos direto na pasta do tópico/módulo."""
    prefix = _prefixo_aula(page_order, lesson_name)
    if total_videos > 1:
        return os.path.join(folder_topico, f'{prefix} (vídeo {indice_video}).mp4')
    return os.path.join(folder_topico, f'{prefix}.mp4')


def _caminho_descricao_aula(folder_topico, page_order, lesson_name):
    pasta = os.path.join(folder_topico, 'descricoes')
    return os.path.join(pasta, f'{_prefixo_aula(page_order, lesson_name)}.html')


def _pasta_materiais_topico(folder_topico):
    return os.path.join(folder_topico, 'Materiais')


def _caminho_anexo_aula(folder_topico, page_order, lesson_name, anexo_nome):
    return os.path.join(
        _pasta_materiais_topico(folder_topico),
        f'{_prefixo_aula(page_order, lesson_name)} - {anexo_nome}',
    )


def _caminho_gdrive_aula(folder_topico, page_order, lesson_name, file_id):
    return os.path.join(
        _pasta_materiais_topico(folder_topico),
        f'{_prefixo_aula(page_order, lesson_name)} - gdrive_{file_id}.pdf',
    )


def _caminho_links_aula(folder_topico, page_order, lesson_name):
    return os.path.join(
        _pasta_materiais_topico(folder_topico),
        f'{_prefixo_aula(page_order, lesson_name)} - links.txt',
    )


def _caminho_video_padrao(pasta_aula_legada, indice):
    return os.path.join(pasta_aula_legada, f'aula-{slugify(str(indice))}.mp4')


def _caminho_parcial(path):
    """
    Caminho temporário preservando a extensão real (ex: aula-1.part.mp4).
    ffmpeg escolhe o muxer pela extensão — .part sozinho falha com Invalid argument.
    """
    root, ext = os.path.splitext(path)
    if not ext:
        ext = '.mp4'
    return f'{root}.part{ext}'


def _limpar_parcial(path):
    """Remove temporários (.part.mp4 / legado .mp4.part) e arquivo final incompleto."""
    candidatos = {
        _caminho_parcial(path),
        f'{path}.part',  # legado da versão anterior
    }
    for p in candidatos:
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass
    try:
        if os.path.isfile(path) and os.path.getsize(path) < 1024:
            os.remove(path)
    except OSError:
        pass


def _finalizar_download(part_path, output_path):
    """Move arquivo parcial → final só se o conteúdo for válido."""
    if not os.path.isfile(part_path) or os.path.getsize(part_path) < 1024:
        raise RuntimeError("download incompleto (arquivo parcial inválido)")
    os.replace(part_path, output_path)
