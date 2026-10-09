# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
#                                      Hotmart Course Downloader                                                      #
#                                                                                                                     #
#  Baseado no gist original de @juvenal: https://gist.github.com/juvenal/2d9a822325769d30c45c635fbf388c1b           #
#  Com melhorias para download de PDFs embutidos do Google Drive                                                     #
#                                                                                                                     #
#  NOTA: A API da Hotmart mudou (2026) e agora você precisa adicionar manualmente os subdomínios                     #
#        dos cursos no arquivo config_cursos.py                                                                      #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

# Requisitos:
# - FFMPEG instalado no sistema (adicionado às variáveis de ambiente)
# - Dependências Python: pip install -r requirements.txt
#   (m3u8, beautifulsoup4, youtube_dl, requests)
#
# Como usar:
# 1. Configure os subdomínios no config_cursos.py
# 2. Execute: python hotmark.py
# 3. Informe email e senha quando solicitado
#
# O que o script faz:
# - Baixa vídeos (Hotmart, Vimeo, YouTube)
# - Baixa anexos normais (PDFs, arquivos zip, etc)
# - Baixa PDFs embutidos do Google Drive (iframes)
# - Salva links de leitura complementar
# - Salva descrições das aulas
# - Retoma downloads interrompidos automaticamente
# - Organiza tudo em pastas por módulo/aula


import time
import datetime
import requests
import m3u8  # pip install m3u8
import re
import os
import json
import base64
import urllib.parse
from bs4 import BeautifulSoup  # pip install beautifulsoup4
import youtube_dl  # pip install youtube_dl
import subprocess
import glob
import unicodedata
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

_print_lock = threading.Lock()
_page_cache = {}
_page_cache_lock = threading.Lock()

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


def extrair_google_drive_urls(html_content):
    """
    Extrai URLs do Google Drive de iframes no conteúdo HTML.
    Retorna uma lista de tuplas: (file_id, url_preview, url_download)
    """
    if not html_content:
        return []
    
    urls = []
    # Padrão para encontrar iframes com Google Drive
    pattern = r'drive\.google\.com/file/d/([a-zA-Z0-9_-]+)'
    matches = re.findall(pattern, html_content)
    
    for file_id in matches:
        preview_url = f"https://drive.google.com/file/d/{file_id}/preview"
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        urls.append((file_id, preview_url, download_url))
    
    return urls


def baixar_google_drive(file_id, download_url, output_path, first_folder):
    """
    Baixa um arquivo do Google Drive.
    Retorna True se o download foi bem-sucedido, False caso contrário.
    """
    try:
        loga(first_folder, "INFO", f"Iniciando download do Google Drive: {file_id}")
        
        # Cria uma sessão para manter cookies
        session = requests.Session()
        
        # Primeira tentativa: download direto
        response = session.get(download_url, stream=True)
        
        # Se o arquivo for grande, Google Drive mostra página de confirmação
        if 'confirm' in response.text or 'virus scan warning' in response.text.lower():
            # Procura pelo link de confirmação
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all('a'):
                href = link.get('href', '')
                if 'export=download' in href and 'confirm' in href:
                    download_url = 'https://drive.google.com' + href
                    response = session.get(download_url, stream=True)
                    break
        
        # Salva o arquivo
        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            # Verifica se o arquivo foi baixado corretamente
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                loga(first_folder, "INFO", f"Download concluído: {output_path} ({os.path.getsize(output_path)} bytes)")
                return True
            else:
                loga(first_folder, "ERRO", f"Arquivo vazio ou não criado: {output_path}")
                return False
        else:
            loga(first_folder, "ERRO", f"Falha no download do Google Drive: {response.status_code}")
            return False
            
    except Exception as e:
        loga(first_folder, "ERRO", f"Exceção ao baixar do Google Drive {file_id}: {str(e)}")
        return False

def loga(curso, status, msg):
    with open(curso + "/log.txt", "a", encoding="utf-8") as logz:
        logz.write(f"[{datetime.datetime.today().replace(microsecond=0)}] {status}: {msg}\n")


PROGRESS_FILE = '.progress.json'
_PENDENTE_ESCOLHA_VIDEO = '__escolher_video__'


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


def _arquivo_pronto(path, min_bytes=1024):
    """True se o arquivo existe e parece completo (não vazio / não parcial)."""
    try:
        return os.path.isfile(path) and os.path.getsize(path) >= min_bytes
    except OSError:
        return False


def _nome_arquivo_seguro(nome):
    return re.sub(r'[<>:"/\\|?*]', '', (nome or '')).strip()


def _prefixo_aula(page_order, lesson_name):
    return f"{slugify(str(page_order))}.{slugify(lesson_name)}"


def _pasta_aula_legada(folder_topico, page_order, lesson_name):
    """Layout antigo: subpasta por aula (compatível ao pular re-download)."""
    return os.path.join(folder_topico, _prefixo_aula(page_order, lesson_name))


def _caminho_video_no_topico(folder_topico, page_order, lesson_name, indice_video, total_videos=1):
    """Vídeos direto na pasta do tópico/módulo."""
    prefix = _prefixo_aula(page_order, lesson_name)
    if total_videos > 1:
        return os.path.join(folder_topico, f'{prefix}-v{indice_video}.mp4')
    return os.path.join(folder_topico, f'{prefix}.mp4')


def _caminho_descricao_aula(folder_topico, page_order, lesson_name):
    pasta = os.path.join(folder_topico, 'descricoes')
    return os.path.join(pasta, f'{_prefixo_aula(page_order, lesson_name)}.html')


def _pasta_materiais_topico(folder_topico):
    return os.path.join(folder_topico, 'Materiais')


def _caminho_anexo_aula(folder_topico, page_order, lesson_name, anexo_nome):
    return os.path.join(
        _pasta_materiais_topico(folder_topico),
        f'{_prefixo_aula(page_order, lesson_name)}_{anexo_nome}',
    )


def _caminho_gdrive_aula(folder_topico, page_order, lesson_name, file_id):
    return os.path.join(
        _pasta_materiais_topico(folder_topico),
        f'{_prefixo_aula(page_order, lesson_name)}_gdrive_{file_id}.pdf',
    )


def _caminho_links_aula(folder_topico, page_order, lesson_name):
    return os.path.join(
        _pasta_materiais_topico(folder_topico),
        f'{_prefixo_aula(page_order, lesson_name)}-links.txt',
    )


def _caminho_video_padrao(pasta_aula_legada, indice):
    return os.path.join(pasta_aula_legada, f'aula-{slugify(str(indice))}.mp4')


def _video_ja_baixado(
    folder_topico, page_order, lesson_name, indice,
    media_name=None, total_videos=1,
):
    """
    True se o vídeo já existe (pasta do tópico ou layout antigo por aula).
    """
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
                f'{_prefixo_aula(page_order, lesson_name)}-{slugify(safe)}.mp4',
            ))

    vistos = set()
    for path in candidatos:
        path = os.path.normpath(path)
        if path in vistos:
            continue
        vistos.add(path)
        if _arquivo_pronto(path):
            return True, path

    if total_videos == 1:
        alvo = _prefixo_aula(page_order, lesson_name)
        for path in glob.glob(os.path.join(folder_topico, '*.mp4')):
            base = os.path.basename(path)
            if '.part.' in base or base.endswith('.part'):
                continue
            if base.startswith(alvo):
                if _arquivo_pronto(path):
                    return True, path
        for path in glob.glob(os.path.join(legado, '*.mp4')):
            base = os.path.basename(path)
            if '.part.' in base or base.endswith('.part'):
                continue
            if _arquivo_pronto(path):
                return True, path

    return False, None


def _anexo_ja_baixado(path):
    return _arquivo_pronto(path, min_bytes=1)


def _aula_ja_completa_na_pasta(folder_topico, aula):
    """Pula a aula inteira se vídeos, anexos e materiais da descrição já estão na pasta."""
    page_order, lesson_name = aula[0], aula[1]
    materiais = _pasta_materiais_topico(folder_topico)
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
            )
            if not pronto:
                return False
    else:
        alvo = _prefixo_aula(page_order, lesson_name)
        mp4_prontos = [
            p for p in glob.glob(os.path.join(folder_topico, '*.mp4'))
            if os.path.basename(p).startswith(alvo)
            and '.part.' not in os.path.basename(p)
            and _arquivo_pronto(p)
        ]
        if not mp4_prontos:
            mp4_prontos = [
                p for p in glob.glob(os.path.join(legado, '*.mp4'))
                if '.part.' not in os.path.basename(p) and _arquivo_pronto(p)
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


def _fmt_bytes(n):
    n = float(n or 0)
    for unidade in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unidade == 'TB':
            if unidade == 'B':
                return f"{int(n)}B"
            return f"{n:.1f}{unidade}"
        n /= 1024
    return f"{n:.1f}TB"


def _fmt_tempo(segundos):
    segundos = max(0, int(segundos or 0))
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _barra(pct, largura=24):
    pct = max(0, min(100, int(pct)))
    preenchido = int(largura * pct / 100)
    return f"{'█' * preenchido}{'░' * (largura - preenchido)}"


def _imprimir_progresso_linha(msg):
    with _print_lock:
        print(f"\r{msg}", end='', flush=True)


def _print_seguro(msg=''):
    with _print_lock:
        print(msg, flush=True)


def _carregar_desempenho():
    """Opções de velocidade (config_cursos.py ou padrões)."""
    cfg = {
        'pausa_entre_videos': 0.0,
        'medir_duracao': False,
        'download_paralelo': 1,
        'api_paralelo': 6,
    }
    try:
        from config_cursos import PAUSA_ENTRE_VIDEOS
        if PAUSA_ENTRE_VIDEOS is not None:
            cfg['pausa_entre_videos'] = max(0.0, float(PAUSA_ENTRE_VIDEOS))
    except (ImportError, TypeError, ValueError):
        pass
    try:
        from config_cursos import MEDIR_DURACAO_VIDEO
        if MEDIR_DURACAO_VIDEO is not None:
            cfg['medir_duracao'] = bool(MEDIR_DURACAO_VIDEO)
    except ImportError:
        pass
    try:
        from config_cursos import DOWNLOAD_PARALELO
        if DOWNLOAD_PARALELO is not None:
            cfg['download_paralelo'] = max(1, min(int(DOWNLOAD_PARALELO), 4))
    except (TypeError, ValueError):
        pass
    try:
        from config_cursos import API_PARALELO
        if API_PARALELO is not None:
            cfg['api_paralelo'] = max(1, min(int(API_PARALELO), 16))
    except (TypeError, ValueError):
        pass
    cfg['corrigir_sync_av'] = True
    try:
        from config_cursos import CORRIGIR_SYNC_AV
        if CORRIGIR_SYNC_AV is not None:
            cfg['corrigir_sync_av'] = bool(CORRIGIR_SYNC_AV)
    except ImportError:
        pass
    return cfg


def _limpar_cache_paginas():
    with _page_cache_lock:
        _page_cache.clear()


def _get_page_json(authMart, page_hash):
    with _page_cache_lock:
        if page_hash in _page_cache:
            return _page_cache[page_hash]
    product_id = getattr(authMart, 'hotmart_product_id', None)
    subdomain = getattr(authMart, 'hotmart_subdomain', None)
    headers_salvos = dict(authMart.headers)
    if product_id:
        _aplicar_headers_consumidor(authMart, product_id, subdomain)
    try:
        resp = authMart.get(
            f'{CLUB_API}/page/{page_hash}',
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    finally:
        authMart.headers.clear()
        authMart.headers.update(headers_salvos)
    with _page_cache_lock:
        _page_cache[page_hash] = data
    return data


def _montar_registro_aula(item, aula_payload):
    page = item['page']
    registro = [
        page['pageOrder'],
        _nome_arquivo_seguro(page['name']),
        page['hash'],
        {'videos': []},
        {'anexos': []},
        {'links': []},
    ]
    try:
        for video in aula_payload['mediasSrc']:
            registro[3]['videos'].append([
                _nome_arquivo_seguro(video['mediaName']),
                video['mediaCode'],
                video['mediaSrcUrl'],
            ])
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


class _GerenciadorDownloadsVideo:
    """Limita quantos ffmpeg rodam ao mesmo tempo."""

    def __init__(self, max_workers):
        self.max_workers = max(1, int(max_workers))
        self._executor = (
            ThreadPoolExecutor(max_workers=self.max_workers)
            if self.max_workers > 1 else None
        )
        self._futures = []

    def run(self, fn, *args, **kwargs):
        if self._executor is None:
            fn(*args, **kwargs)
            return
        self._futures.append(self._executor.submit(fn, *args, **kwargs))

    def aguardar(self):
        if not self._executor:
            return
        erros = []
        for fut in as_completed(self._futures):
            try:
                fut.result()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                erros.append(e)
        self._futures.clear()
        self._executor.shutdown(wait=True)
        self._executor = None
        if erros:
            raise erros[0]


def _contar_aulas(estrutura):
    return sum(len(aulas_lista) for modulo in estrutura.values() for aulas_lista in modulo.values())


def _obter_duracao_media(url, headers_str):
    """Duração em segundos via ffprobe, ou None se indisponível."""
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-headers', headers_str,
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (ValueError, OSError, subprocess.TimeoutExpired):
        pass
    return None


def _rodar_ffmpeg_com_progresso(ffmpegcmd, part_path, duracao=None):
    """
    Executa ffmpeg mostrando progresso ao vivo.
    Usa -progress pipe:1 (out_time_ms) + tamanho do arquivo parcial.
    """
    cmd = list(ffmpegcmd)
    cmd[1:1] = ['-progress', 'pipe:1', '-nostats']

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    tempo_atual = 0.0
    try:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith('out_time_ms='):
                raw = line.split('=', 1)[1]
                if raw.isdigit():
                    tempo_atual = int(raw) / 1_000_000
                size = os.path.getsize(part_path) if os.path.isfile(part_path) else 0
                if duracao and duracao > 0:
                    pct = min(99, int(100 * tempo_atual / duracao))
                    _imprimir_progresso_linha(
                        f"  {_barra(pct)} {pct:3d}%  "
                        f"{_fmt_tempo(tempo_atual)}/{_fmt_tempo(duracao)}  "
                        f"{_fmt_bytes(size)}    "
                    )
                else:
                    _imprimir_progresso_linha(
                        f"  baixando {_fmt_tempo(tempo_atual)}  {_fmt_bytes(size)}    "
                    )
            elif line == 'progress=end':
                break
        returncode = proc.wait()
    except KeyboardInterrupt:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        print()
        raise
    except Exception:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        print()
        raise

    stderr = ''
    try:
        if proc.stderr:
            stderr = proc.stderr.read()
    except OSError:
        pass

    if returncode == 0:
        size = os.path.getsize(part_path) if os.path.isfile(part_path) else 0
        tempo_label = _fmt_tempo(duracao or tempo_atual)
        _imprimir_progresso_linha(
            f"  {_barra(100)} 100%  {tempo_label}  {_fmt_bytes(size)}    "
        )
    print()
    return returncode, stderr


def _rodar_ffmpeg_simples(ffmpegcmd):
    """ffmpeg sem barra ao vivo (usado em download paralelo)."""
    proc = subprocess.run(
        ffmpegcmd,
        capture_output=True,
        text=True,
    )
    stderr = (proc.stderr or '').strip()
    return proc.returncode, stderr


def _asset_height(asset):
    try:
        return int(asset.get('height') or 0)
    except (TypeError, ValueError):
        return 0


def _escolher_asset_por_qualidade(assets, qualidade=0):
    """
    Escolhe o mediaAsset conforme a preferência.
    qualidade=0 → máxima disponível
    qualidade=N → maior resolução <= N; se nenhuma, a menor disponível
    """
    if not assets:
        raise RuntimeError("Embed sem mediaAssets")

    if not qualidade:
        return max(assets, key=_asset_height)

    abaixo = [a for a in assets if 0 < _asset_height(a) <= qualidade]
    if abaixo:
        return max(abaixo, key=_asset_height)

    com_altura = [a for a in assets if _asset_height(a) > 0]
    if com_altura:
        return min(com_altura, key=_asset_height)
    return assets[0]


def _ydl_format_por_qualidade(qualidade=0):
    """Formato youtube-dl limitado à altura máxima desejada."""
    if not qualidade:
        return "best"
    return (
        f"bestvideo[height<={qualidade}]+bestaudio/"
        f"best[height<={qualidade}]/best"
    )


def _selecionar_qualidade():
    """
    Pergunta a qualidade máxima dos vídeos.
    Retorna altura em pixels (0 = máxima disponível).
    Pode ser pré-definida em config_cursos.QUALIDADE_VIDEO.
    """
    opcoes = [
        (360, "360p — mais rápido, menor qualidade"),
        (480, "480p — rápido"),
        (720, "720p — equilibrado (recomendado)"),
        (1080, "1080p — alta qualidade"),
        (0, "Máxima disponível — mais lento"),
    ]

    try:
        from config_cursos import QUALIDADE_VIDEO as cfg_qualidade
    except ImportError:
        cfg_qualidade = None

    if cfg_qualidade is not None:
        try:
            q = int(cfg_qualidade)
        except (TypeError, ValueError):
            q = None
        if q is not None and (q == 0 or q in {o[0] for o in opcoes if o[0]}):
            label = next((lbl for h, lbl in opcoes if h == q), f"{q}p")
            print(f"\nQualidade definida em config_cursos.py: {label}")
            return q
        if q is not None and q > 0:
            print(f"\nQualidade definida em config_cursos.py: até {q}p")
            return q

    print("\n=== Qualidade do vídeo ===")
    for i, (_, label) in enumerate(opcoes, start=1):
        print(f"{i}. {label}")
    print("\nQualidades menores = download mais rápido e menos espaço em disco.")

    raw = input("> ").strip().lower()
    if not raw or raw in ('3', '720', '720p'):
        print("Usando 720p.")
        return 720

    mapa_texto = {
        '1': 360, '360': 360, '360p': 360,
        '2': 480, '480': 480, '480p': 480,
        '3': 720, '720': 720, '720p': 720,
        '4': 1080, '1080': 1080, '1080p': 1080,
        '5': 0, 'max': 0, 'maxima': 0, 'máxima': 0, '0': 0,
    }
    if raw in mapa_texto:
        escolhida = mapa_texto[raw]
        label = next((lbl for h, lbl in opcoes if h == escolhida), f"{escolhida}p")
        print(f"Usando: {label}")
        return escolhida

    try:
        q = int(raw.replace('p', ''))
        if q > 0:
            print(f"Usando até {q}p.")
            return q
    except ValueError:
        pass

    print("Opção inválida. Usando 720p.")
    return 720


def obter_url_hls_assinada(media_src_url, video_hash=None, qualidade=0):
    """
    Hotmart passou a proteger o HLS com assinatura Akamai/CloudFront.
    O contentplayer sem assinatura devolve MissingKey.
    Fluxo atual: abrir o embed (mediaSrcUrl com jwtToken) e ler mediaAssets.
    qualidade: altura máxima desejada em pixels (0 = máxima disponível).
    """
    parsed = urllib.parse.urlparse(media_src_url)
    qs = urllib.parse.parse_qs(parsed.query)
    jwt = (qs.get('jwtToken') or qs.get('token') or [None])[0]
    app = (qs.get('applicationCode') or [None])[0]
    user = (qs.get('userCode') or [None])[0]
    code = video_hash or parsed.path.rstrip('/').split('/')[-1]

    if not jwt or not app:
        raise RuntimeError(f"mediaSrcUrl sem jwtToken/applicationCode: {media_src_url[:120]}")

    embed_url = (
        f"https://cf-embed.play.hotmart.com/embed/{code}"
        f"?applicationCode={urllib.parse.quote(app)}"
        f"&userCode={urllib.parse.quote(user or '')}"
        f"&jwtToken={urllib.parse.quote(jwt)}"
    )
    resp = requests.get(
        embed_url,
        headers={
            'user-agent': USER_AGENT,
            'accept': 'text/html,application/xhtml+xml',
            'referer': 'https://hotmart.com/',
        },
        timeout=45,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Embed HTTP {resp.status_code}")

    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        resp.text,
        flags=re.DOTALL,
    )
    if not match:
        raise RuntimeError("Embed sem __NEXT_DATA__ (jwt expirado ou inválido?)")

    page_props = json.loads(match.group(1)).get('props', {}).get('pageProps', {})
    if page_props.get('error'):
        raise RuntimeError(f"Embed retornou erro: {page_props.get('error')}")

    assets = (page_props.get('applicationData') or {}).get('mediaAssets') or []
    if not assets:
        raise RuntimeError("Embed sem mediaAssets")

    chosen = _escolher_asset_por_qualidade(assets, qualidade)
    hls_url = chosen.get('url') or chosen.get('urlEncrypted')
    if not hls_url:
        raise RuntimeError("mediaAsset sem URL HLS")
    return hls_url, _asset_height(chosen)


def _video_tem_audio(path):
    try:
        r = subprocess.run(
            [
                'ffprobe', '-v', 'error', '-select_streams', 'a:0',
                '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return r.returncode == 0 and 'audio' in (r.stdout or '').lower()
    except (OSError, subprocess.TimeoutExpired):
        return False


def _remux_sincronizar_av(path, first_folder):
    """
    HLS da Hotmart com -c copy costuma gerar áudio adiantado (PTS desalinhado).
    Remux: vídeo copy + áudio AAC com aresample async.
    """
    if not _video_tem_audio(path):
        return
    tmp = path + '._sync.tmp.mp4'
    _limpar_parcial(tmp)
    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
        '-i', path,
        '-map', '0:v:0', '-map', '0:a:0?',
        '-c:v', 'copy',
        '-c:a', 'aac', '-b:a', '192k',
        '-af', 'aresample=async=1:first_pts=0',
        '-avoid_negative_ts', 'make_zero',
        '-movflags', '+faststart',
        '-y', tmp,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not _arquivo_pronto(tmp, min_bytes=1024):
        _limpar_parcial(tmp)
        loga(first_folder, 'WARN', f'Remux A/V não aplicado: {(proc.stderr or "")[-200:]}')
        return
    os.replace(tmp, path)
    loga(first_folder, 'INFO', 'Remux A/V aplicado (sync áudio/vídeo)')


def baixar_video_hotmart(
    media_src_url, video_hash, output_path, first_folder, qualidade=0,
    medir_duracao=False, mostrar_progresso=True, corrigir_sync_av=True,
):
    if _arquivo_pronto(output_path):
        size = os.path.getsize(output_path)
        _print_seguro(f"  [OK] Arquivo já presente ({_fmt_bytes(size)}), pulando")
        loga(first_folder, "INFO", f"Vídeo já presente, pulado: {output_path}")
        return

    hls_url, height = obter_url_hls_assinada(media_src_url, video_hash, qualidade=qualidade)
    preferida = f"{qualidade}p" if qualidade else "máxima"
    _print_seguro(f"  Qualidade: {height or 'auto'}p (preferência: {preferida})")
    loga(first_folder, "INFO", f"HLS assinado obtido ({height}p, preferência={preferida})")

    _limpar_parcial(output_path)
    part_path = _caminho_parcial(output_path)

    referer = 'https://cf-embed.play.hotmart.com/'
    headers_str = f'Referer: {referer}\r\nUser-Agent: {USER_AGENT}\r\n'
    duracao = None
    if medir_duracao and mostrar_progresso:
        with _print_lock:
            print("  Obtendo duração...", end='', flush=True)
        duracao = _obter_duracao_media(hls_url, headers_str)
        with _print_lock:
            if duracao:
                print(f" {_fmt_tempo(duracao)}")
            else:
                print(" indisponível (mostrando tamanho/tempo)")

    ffmpegcmd = [
        'ffmpeg',
        '-hide_banner',
        '-loglevel', 'error',
        '-headers', headers_str,
        '-reconnect', '1',
        '-reconnect_streamed', '1',
        '-reconnect_delay_max', '5',
        '-probesize', '32M',
        '-analyzeduration', '32M',
        '-fflags', '+genpts+discardcorrupt',
        '-i', hls_url,
        '-map', '0:v:0',
        '-map', '0:a:0?',
        '-c:v', 'copy',
        '-c:a', 'copy',
        '-bsf:a', 'aac_adtstoasc',
        '-avoid_negative_ts', 'make_zero',
        '-max_muxing_queue_size', '9999',
        '-movflags', '+faststart',
        '-y',
        part_path,
    ]
    loga(first_folder, "INFO", "Iniciando o FFMPEG (URL assinada)")
    try:
        if mostrar_progresso:
            returncode, stderr = _rodar_ffmpeg_com_progresso(ffmpegcmd, part_path, duracao)
        else:
            returncode, stderr = _rodar_ffmpeg_simples(ffmpegcmd)
    except KeyboardInterrupt:
        loga(first_folder, "WARN", "Download interrompido pelo usuário (ffmpeg)")
        raise
    if returncode != 0:
        _limpar_parcial(output_path)
        detalhe = (stderr or '').strip().splitlines()[-1:]
        detalhe = detalhe[0] if detalhe else f"código {returncode}"
        raise RuntimeError(f"ffmpeg falhou: {detalhe}")
    if corrigir_sync_av:
        _print_seguro('  Ajustando sincronia áudio/vídeo...')
        _remux_sincronizar_av(part_path, first_folder)
    try:
        _finalizar_download(part_path, output_path)
    except Exception:
        _limpar_parcial(output_path)
        raise
    size = os.path.getsize(output_path)
    _print_seguro(f"  Concluído: {output_path} ({_fmt_bytes(size)})")
    loga(first_folder, "INFO", f"FFMPEG concluído, aula baixada ({size} bytes).")


def _parse_selecao_numeros(raw, max_n):
    """
    Interpreta seleção numérica: Enter/0/todos = todos; 2; 1,3; 2-4.
    Retorna set de índices 1..max_n ou None se max_n==0.
    """
    if max_n <= 0:
        return set()

    raw = (raw or '').strip().lower()
    if not raw or raw in ('0', 'all', 'todos', '*'):
        return set(range(1, max_n + 1))

    escolhidos = set()
    for parte in raw.replace(' ', '').split(','):
        if not parte:
            continue
        if '-' in parte and ':v' not in parte:
            a, b = parte.split('-', 1)
            try:
                inicio, fim = int(a), int(b)
            except ValueError:
                print(f"Ignorando trecho inválido: {parte}")
                continue
            for n in range(min(inicio, fim), max(inicio, fim) + 1):
                if 1 <= n <= max_n:
                    escolhidos.add(n)
        else:
            try:
                n = int(re.match(r'^(\d+)', parte).group(1))
            except (ValueError, AttributeError):
                print(f"Ignorando trecho inválido: {parte}")
                continue
            if 1 <= n <= max_n:
                escolhidos.add(n)

    if not escolhidos:
        print("Nenhuma opção válida. Usando todos.")
        return set(range(1, max_n + 1))
    return escolhidos


def _modulos_ordenados(modulos):
    return sorted(modulos, key=lambda m: m.get('moduleOrder', 0))


def _selecionar_modulos(modulos, raw=None):
    """
    Mostra a lista de módulos e deixa o usuário escolher quais baixar.
    Aceita: 0/all/enter=todos | 2 | 1,3,5 | 2-4
    raw: seleção pré-definida (ex.: config_cursos.TOPICOS_INDICES como string "5")
    """
    ordenados = _modulos_ordenados(modulos)
    print(f"\n=== Módulos / tópicos ({len(ordenados)}) ===")
    for i, modulo in enumerate(ordenados, start=1):
        num_aulas = len(modulo.get('pages') or [])
        nome = _nome_arquivo_seguro(modulo.get('name', 'Sem nome'))
        print(f"{i}. {nome} ({num_aulas} aula(s))")

    if raw is None:
        raw = input(
            "\nQuais tópicos deseja baixar?\n"
            "  0 ou Enter = todos | ex: 2 | 1,3,5 | 2-4\n"
            "> "
        )

    escolhidos = _parse_selecao_numeros(raw, len(ordenados))
    if len(escolhidos) == len(ordenados):
        print(f"Baixando todos os {len(ordenados)} tópico(s).")
        return ordenados

    filtrados = [m for i, m in enumerate(ordenados, start=1) if i in escolhidos]
    print("Tópicos selecionados:")
    for m in filtrados:
        print(f" - {_nome_arquivo_seguro(m.get('name', ''))}")
    return filtrados


def _plano_aulas(modulos_escolhidos):
    """Lista plana de aulas (1..N) nos tópicos escolhidos."""
    plano = []
    idx = 0
    for modulo in _modulos_ordenados(modulos_escolhidos):
        pages = sorted(modulo.get('pages') or [], key=lambda p: p.get('pageOrder', 0))
        for page in pages:
            idx += 1
            plano.append({
                'idx': idx,
                'module': modulo,
                'page': page,
                'module_order': modulo.get('moduleOrder'),
                'module_name': _nome_arquivo_seguro(modulo.get('name', '')),
                'page_order': page.get('pageOrder'),
                'page_name': _nome_arquivo_seguro(page.get('name', '')),
                'hash': page.get('hash'),
            })
    return plano


def _parse_videos_de_texto(texto):
    """Ex.: '2', '1,3', '1-3' -> set de índices de vídeo (1-based)."""
    texto = (texto or '').strip().lower()
    if not texto or texto in ('0', '*', 'all', 'todos'):
        return None
    return _parse_selecao_numeros(texto, 9999)


def _parse_escopo_aulas(raw, num_aulas):
    """
    Interpreta seleção de aulas/vídeos.
    Retorna (set índices de aula, dict aula_idx -> set vídeos ou None=todos).
    Valores especiais em videos_por_aula: chave com set() vazio = escolher vídeos depois.
    """
    raw = (raw or '').strip().lower()
    if not raw or raw in ('0', 'all', 'todos', '*'):
        return set(range(1, num_aulas + 1)), {}

    aulas = set()
    videos_por_aula = {}

    for parte in raw.replace(' ', '').split(','):
        if not parte:
            continue
        match = re.match(r'^(\d+)(?::v([\d,\-*]*))?$', parte)
        if not match:
            print(f"Ignorando trecho inválido: {parte}")
            continue
        a_idx = int(match.group(1))
        if not (1 <= a_idx <= num_aulas):
            print(f"Ignorando aula fora da lista: {a_idx}")
            continue
        aulas.add(a_idx)
        sufixo = match.group(2)
        if sufixo is None:
            continue
        if sufixo == '':
            videos_por_aula[a_idx] = _PENDENTE_ESCOLHA_VIDEO
        else:
            vids = _parse_videos_de_texto(sufixo)
            if vids:
                videos_por_aula[a_idx] = vids

    if not aulas:
        print("Nenhuma aula válida. Usando todas.")
        return set(range(1, num_aulas + 1)), {}

    return aulas, videos_por_aula


def _listar_videos_da_pagina(authMart, page_hash):
    """Retorna lista de nomes de vídeo Hotmart na página (ordem da API)."""
    try:
        payload = _get_page_json(authMart, page_hash)
    except Exception:
        return []
    nomes = []
    for video in payload.get('mediasSrc') or []:
        nomes.append(_nome_arquivo_seguro(video.get('mediaName', 'Vídeo')))
    return nomes


def _resolver_videos_pendentes(videos_por_aula, plano, authMart):
    """Completa seleção quando o usuário usou N:v (escolher vídeo interativamente)."""
    out = {}
    for a_idx, filtro in videos_por_aula.items():
        if filtro is not _PENDENTE_ESCOLHA_VIDEO:
            out[a_idx] = filtro
            continue
        item = plano[a_idx - 1]
        nomes = _listar_videos_da_pagina(authMart, item['hash'])
        print(f"\n=== Vídeos da aula {a_idx}: {item['page_name']} ===")
        if not nomes:
            print("  (nenhum vídeo Hotmart na API — serão tentados embeds externos)")
            out[a_idx] = None
            continue
        for vi, nome in enumerate(nomes, start=1):
            print(f"  v{vi}. {nome}")
        raw_v = input(
            "Qual(is) vídeo(s)? Enter = todos | ex: 2 | 1,3\n> "
        ).strip().lower()
        escolha = _parse_videos_de_texto(raw_v.replace('v', ''))
        out[a_idx] = escolha

    return out


def _escopo_aulas_de_config(plano):
    """Lê AULAS_INDICES / AULA_VIDEO de config_cursos.py, se definidos."""
    try:
        from config_cursos import AULAS_INDICES, AULA_VIDEO
    except ImportError:
        return None

    if AULAS_INDICES is None and AULA_VIDEO is None:
        return None

    n = len(plano)
    if AULAS_INDICES is not None:
        raw = _indices_config_para_raw(AULAS_INDICES, 'AULAS_INDICES')
        aulas, videos = _parse_escopo_aulas(raw, n)
    else:
        aulas = set(range(1, n + 1))
        videos = {}

    if AULA_VIDEO is not None:
        if isinstance(AULA_VIDEO, dict):
            for key, val in AULA_VIDEO.items():
                a_idx = int(key)
                aulas.add(a_idx)
                if isinstance(val, (list, tuple, set)):
                    videos[a_idx] = {int(v) for v in val}
                else:
                    videos[a_idx] = {int(val)}
        else:
            extra_aulas, extra_v = _parse_escopo_aulas(str(AULA_VIDEO), n)
            if AULAS_INDICES is None:
                aulas = extra_aulas
            else:
                aulas &= extra_aulas
                if not aulas:
                    aulas = extra_aulas
            videos.update(extra_v)

    print("\nEscopo de aulas definido em config_cursos.py")
    return aulas, videos


def _selecionar_escopo_aulas(plano, authMart, raw=None):
    """
    Escolhe quais aulas (e opcionalmente vídeos) baixar.
    Ex.: 3 | 1,5 | 5:v2 (só vídeo 2 da aula 5) | 5:v (lista vídeos)
    """
    if not plano:
        return set(), {}

    cfg = None if raw is not None else _escopo_aulas_de_config(plano)
    if cfg is not None:
        aulas, videos_por_aula = cfg
    else:
        print(f"\n=== Aulas nos tópicos selecionados ({len(plano)}) ===")
        for item in plano:
            print(
                f"{item['idx']}. [{item['module_name']}] "
                f"{item['page_order']}. {item['page_name']}"
            )
        if raw is None:
            raw = input(
                "\nQuais aulas baixar?\n"
                "  Enter ou 0 = todas\n"
                "  ex: 3 | 1,5,10 | 2-4\n"
                "  Um vídeo só: 5:v2 (aula 5, vídeo 2) | 5:v (escolher na lista)\n"
                "> "
            )
        aulas, videos_por_aula = _parse_escopo_aulas(raw, len(plano))

    if any(v is _PENDENTE_ESCOLHA_VIDEO for v in videos_por_aula.values()):
        videos_por_aula = _resolver_videos_pendentes(videos_por_aula, plano, authMart)

    videos_por_aula = {
        k: v for k, v in videos_por_aula.items()
        if v is not None and v is not _PENDENTE_ESCOLHA_VIDEO
    }

    print(f"\nBaixando {len(aulas)} aula(s) de {len(plano)}.")
    if videos_por_aula:
        for a_idx, vids in sorted(videos_por_aula.items()):
            nomes = ','.join(f'v{v}' for v in sorted(vids))
            print(f"  Aula {a_idx}: somente {nomes}")
    return aulas, videos_por_aula


def _indices_config_para_raw(valor, nome_cfg='INDICES'):
    """
    Converte TOPICOS_INDICES / AULAS_INDICES do config para string de seleção.
    Aceita: "1-2", [1, 2], 5 | int único | None
    """
    if valor is None:
        return None
    if isinstance(valor, str):
        return valor.strip()
    if isinstance(valor, int):
        if valor < 0:
            print(
                f"\nAVISO: {nome_cfg}={valor} parece subtração (ex.: 1-2 sem aspas vira -1).\n"
                f"Use string \"1-2\" ou lista [1, 2] em config_cursos.py.\n"
            )
        return str(valor)
    if isinstance(valor, (list, tuple, set)):
        return ','.join(str(x) for x in valor)
    return str(valor)


def _topicos_raw_de_config():
    try:
        from config_cursos import TOPICOS_INDICES
    except ImportError:
        return None
    return _indices_config_para_raw(TOPICOS_INDICES, 'TOPICOS_INDICES')


def _escopo_de_progresso(progresso, plano, authMart):
    indices = progresso.get('aulas_indices')
    if not indices:
        return _selecionar_escopo_aulas(plano, authMart)
    aulas = set(int(i) for i in indices)
    videos_por_aula = {}
    for key, vals in (progresso.get('videos_por_aula') or {}).items():
        videos_por_aula[int(key)] = set(int(v) for v in vals)
    print(f"\nRetomando escopo salvo: {len(aulas)} aula(s).")
    return aulas, videos_por_aula


def _serializar_videos_por_aula(videos_por_aula):
    return {
        str(k): sorted(videos_por_aula[k])
        for k in videos_por_aula
    }


def _video_incluido_no_escopo(aula_idx, video_idx, videos_por_aula):
    """True se este vídeo deve ser baixado (1-based)."""
    if aula_idx is None or aula_idx not in videos_por_aula:
        return True
    return video_idx in videos_por_aula[aula_idx]


def _aula_apenas_videos(aula_idx, videos_por_aula):
    """True se o usuário pediu só alguns vídeos (sem anexos/descrição completa)."""
    if aula_idx is None:
        return False
    return aula_idx in videos_por_aula


USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
)

CLUB_API = 'https://api-club.hotmart.com/hot-club-api/rest/v3'
CLUB_CONSUMER_GW = (
    'https://api-club-course-consumption-gateway-ga.cb.hotmart.com'
)
CLUB_CONSUMER_APP = '@hotmart/app-club-consumer_v1.366.4'
CLUB_CONSUMER_HTTP = 'APP_CLUB_CONSUMER_API_COURSE_CONSUMPTION_GATEWAY_INSTANCE'


def _product_id_por_subdominio(subdomain):
    subdomain = (subdomain or '').strip()
    try:
        from config_cursos import CURSOS_PRODUCT_IDS
        if isinstance(CURSOS_PRODUCT_IDS, dict):
            pid = CURSOS_PRODUCT_IDS.get(subdomain)
            if pid:
                return str(pid).strip()
    except (ImportError, AttributeError):
        pass
    try:
        from config_cursos import HOTMART_PRODUCT_ID
        if HOTMART_PRODUCT_ID:
            return str(HOTMART_PRODUCT_ID).strip()
    except (ImportError, AttributeError):
        pass
    return None


def _club_locale():
    try:
        from config_cursos import CLUB_LOCALE
        if CLUB_LOCALE:
            return str(CLUB_LOCALE).strip().lower()
    except (ImportError, AttributeError):
        pass
    return 'pt-br'


def _referer_club(subdomain):
    locale = _club_locale()
    return f'https://hotmart.com/{locale}/club/{subdomain}/'


def _aplicar_headers_club(session, subdomain):
    """Club novo abre em hotmart.com/pt-br/club/SUBDOMAIN (não só *.club.hotmart.com)."""
    session.headers['club'] = subdomain
    session.headers['origin'] = 'https://hotmart.com'
    session.headers['referer'] = _referer_club(subdomain)


def _aplicar_headers_consumidor(session, product_id, subdomain=None):
    """App Club novo (consumption-gateway + page v3 com x-product-id)."""
    session.headers['x-product-id'] = str(product_id)
    session.headers['x-app-name'] = CLUB_CONSUMER_APP
    session.headers['x-hot-club-http'] = CLUB_CONSUMER_HTTP
    session.headers.pop('club', None)
    session.headers['origin'] = 'https://hotmart.com'
    if subdomain:
        base = _referer_club(subdomain).rstrip('/')
        session.headers['referer'] = f'{base}/products/{product_id}/'


def _normalizar_modulos_gateway(data):
    for i, modulo in enumerate(data.get('modules') or [], start=1):
        modulo['moduleOrder'] = i
        for j, page in enumerate(modulo.get('pages') or [], start=1):
            page.setdefault('pageOrder', j)
    return data


def _get_navigation_json(session, subdomain, product_id=None):
    product_id = product_id or _product_id_por_subdominio(subdomain)
    if product_id:
        _aplicar_headers_consumidor(session, product_id, subdomain)
        resp = session.get(
            f'{CLUB_CONSUMER_GW}/v1/navigation?productId={product_id}',
            timeout=30,
        )
        resp.raise_for_status()
        return _normalizar_modulos_gateway(resp.json())
    _aplicar_headers_club(session, subdomain)
    resp = session.get(f'{CLUB_API}/navigation', timeout=30)
    if resp.status_code == 403:
        raise RuntimeError(
            "A API antiga do Club (navigation) retornou 403. "
            "Cursos em hotmart.com/pt-br/club/.../products/ID precisam do ID "
            "em config_cursos.py → CURSOS_PRODUCT_IDS."
        )
    resp.raise_for_status()
    return resp.json()


def _sanitizar_nome_curso(nome):
    return re.sub(r'[<>:"/\\|?*]', '', str(nome)).strip()


def _obter_nome_curso(session, subdomain, product_id=None):
    product_id = product_id or _product_id_por_subdominio(subdomain)
    if product_id:
        try:
            _aplicar_headers_consumidor(session, product_id, subdomain)
            st = session.get(
                f'{CLUB_CONSUMER_GW}/v1/user/{product_id}/status',
                timeout=30,
            )
            if st.status_code == 200 and st.json().get('active'):
                nav = _get_navigation_json(session, subdomain, product_id)
                mods = nav.get('modules') or []
                if mods:
                    rotulo = ' / '.join(
                        _sanitizar_nome_curso(m.get('name', ''))
                        for m in mods[:2]
                        if m.get('name')
                    )
                    if rotulo:
                        return _sanitizar_nome_curso(
                            f"{subdomain.replace('-', ' ')} ({rotulo[:80]})"
                        )
        except Exception as e:
            loga(".", "DEBUG", f"Nome via consumption-gateway: {e}")

    _aplicar_headers_club(session, subdomain)
    for url in (
        f'{CLUB_API}/membership?attach_token=false',
        f'{CLUB_API}/navigation',
    ):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code != 200:
                continue
            data = resp.json()
            for key in ('name', 'title', 'productName', 'clubName', 'productTitle'):
                val = data.get(key)
                if val:
                    return _sanitizar_nome_curso(val)
        except Exception as e:
            loga(".", "DEBUG", f"Nome do curso via {url}: {e}")
    fallback = _sanitizar_nome_curso(subdomain.replace('-', ' '))
    loga(".", "WARN", f"Nome do curso não veio da API; usando '{fallback}'")
    return fallback


def _validar_token_club(session, subdomain, product_id=None):
    product_id = product_id or _product_id_por_subdominio(subdomain)
    if product_id:
        _aplicar_headers_consumidor(session, product_id, subdomain)
        probe = session.get(
            f'{CLUB_CONSUMER_GW}/v1/user/{product_id}/status',
            timeout=30,
        )
        if probe.status_code in (401, 403):
            return False, probe.status_code, (probe.text or '')[:200]
        if probe.status_code == 200:
            try:
                if probe.json().get('active'):
                    return True, probe.status_code, ''
            except Exception:
                pass
        nav = session.get(
            f'{CLUB_CONSUMER_GW}/v1/navigation?productId={product_id}',
            timeout=30,
        )
        if nav.status_code in (401, 403):
            return False, nav.status_code, (nav.text or '')[:200]
        if nav.status_code == 200 and (nav.json().get('modules') is not None):
            return True, nav.status_code, ''
        return False, nav.status_code, (nav.text or '')[:200]

    _aplicar_headers_club(session, subdomain)
    probe = session.get(f'{CLUB_API}/navigation', timeout=30)
    if probe.status_code in (401, 403):
        return False, probe.status_code, probe.text[:200]
    try:
        payload = probe.json()
        if payload.get('error') == 'invalid_token':
            desc = payload.get('error_description') or payload.get('error')
            return False, probe.status_code, str(desc)
        if probe.status_code == 200 and payload.get('modules') is not None:
            return True, probe.status_code, ''
    except Exception:
        pass
    if probe.status_code != 200:
        return False, probe.status_code, (probe.text or '')[:200]
    return True, probe.status_code, ''


# Endpoint antigo (Sparkle) foi desligado/bloqueado no ELB e responde 403 HTML.
# Fluxo atual da Hotmart Club usa OIDC em sso.hotmart.com; login por senha
# via script costuma falhar por WAF/client secret. Preferir Bearer token do browser.
OAUTH_ENDPOINTS = [
    'https://sso.hotmart.com/oidc/accessToken',
    'https://api-sec-vlc.hotmart.com/security/oauth/token',
    'https://api.sparkleapp.com.br/oauth/token',
]


def _normalizar_token(token):
    if not token:
        return None
    token = token.strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    return token or None


def _verificar_jwt_local(token):
    """Detecta token truncado/corrompido antes de chamar a api-club."""
    parts = token.split('.')
    if len(parts) != 3:
        return False, (
            f"Token JWT inválido: esperadas 3 partes separadas por '.', "
            f"encontradas {len(parts)}."
        )
    if not all(parts):
        return False, "Token incompleto (parte vazia no JWT)."
    try:
        pad = '=' * (-len(parts[1]) % 4)
        json.loads(base64.urlsafe_b64decode(parts[1] + pad))
    except Exception:
        return False, (
            "O JWT colado não decodifica como JSON (cópia incompleta ou alterada).\n"
            "No Chrome: Rede > api-club > request navigation > Request Headers > "
            "Authorization > botão direito > Copy value.\n"
            "Cole direto no terminal (export HOTMART_TOKEN='...'), sem WhatsApp/chat."
        )
    return True, ''


def _sessao_com_token(access_token):
    authMart = requests.session()
    authMart.headers.clear()
    authMart.headers['user-agent'] = USER_AGENT
    authMart.headers['authorization'] = 'Bearer ' + access_token
    authMart.headers['accept'] = 'application/json, text/plain, */*'
    return authMart, {'token': access_token}


def _obter_token_por_senha(authMart, email, senha):
    data = {'username': email, 'password': senha, 'grant_type': 'password'}
    client_id = os.environ.get('HOTMART_CLIENT_ID', '').strip()
    client_secret = os.environ.get('HOTMART_CLIENT_SECRET', '').strip()
    if client_id:
        data['client_id'] = client_id
    if client_secret:
        data['client_secret'] = client_secret

    loga(".", "INFO", f"Tentando autenticar com email {email} (senha omitida do log)")

    ultimo_erro = None
    for url in OAUTH_ENDPOINTS:
        try:
            resp = authMart.post(url, data=data, timeout=30)
        except requests.RequestException as e:
            ultimo_erro = f"{url}: exceção {e}"
            loga(".", "ERROR", ultimo_erro)
            continue

        content_type = (resp.headers.get('content-type') or '').lower()
        if resp.status_code == 200 and 'json' in content_type:
            payload = resp.json()
            if payload.get('access_token'):
                loga(".", "INFO", f"Autenticação bem sucedida via {url}")
                return payload['access_token']
            ultimo_erro = f"{url}: 200 sem access_token"
            loga(".", "ERROR", ultimo_erro)
            continue

        body_preview = (resp.text or '')[:300].replace('\n', ' ')
        ultimo_erro = f"{url}: HTTP {resp.status_code} — {body_preview}"
        loga(".", "ERROR", f"Autenticação falhou em {url}. Código: {resp.status_code}")
        if '<html' in (resp.text or '').lower():
            loga(".", "ERROR", "Resposta HTML (endpoint bloqueado/desligado), não é erro de senha.")
        else:
            loga(".", "ERROR", body_preview)

    raise RuntimeError(ultimo_erro or "Falha ao autenticar")


def autenticacao(**kwargs):
    if not os.path.exists('temp'):
        os.makedirs('temp')
    for f in glob.glob("temp/*"):
        os.remove(f)

    authMart = requests.session()
    authMart.headers['user-agent'] = USER_AGENT
    authMart.headers['accept'] = 'application/json, text/plain, */*'

    # 1) Token já obtido no navegador (recomendado)
    token = _normalizar_token(
        kwargs.get('token')
        or os.environ.get('HOTMART_TOKEN')
        or os.environ.get('HOTMART_ACCESS_TOKEN')
    )

    if not token:
        print(
            "\nA autenticação por email/senha do endpoint antigo (Sparkle) está bloqueada (403).\n"
            "Opção mais confiável: colar o Bearer token da sessão do Club no navegador.\n"
            "\nComo pegar o token:\n"
            "  1. Abra o curso (ex.: hotmart.com/pt-br/club/SEU-SUBDOMAIN/products/...)\n"
            "  2. DevTools (F12) > Rede; recarregue a página (F5)\n"
            "  3. Filtre por 'consumption-gateway' ou 'api-club' (ex.: .../status ou navigation)\n"
            "  4. Copie o Authorization inteiro (JWT com duas pontos; sem quebra de linha)\n"
            "\nOu exporte: export HOTMART_TOKEN='cole_só_o_jwt_ou_Bearer_jwt'\n"
        )
        token_input = input(
            "Cole o Bearer token (ou pressione Enter para tentar email/senha):\n"
        ).strip()
        token = _normalizar_token(token_input)

    if token:
        ok_jwt, msg_jwt = _verificar_jwt_local(token)
        if not ok_jwt:
            print(msg_jwt)
            loga(".", "ERROR", msg_jwt.replace('\n', ' '))
            exit(13)
        loga(".", "INFO", "Autenticando com Bearer token fornecido")
        session, params = _sessao_com_token(token)
        # Tokens do Club (client b432cdd3-...) são rejeitados pelo check_token antigo.
        # Valida direto na API do Club, que é o que o download usa.
        subdomain = None
        try:
            from config_cursos import CURSOS_SUBDOMINIOS
            if CURSOS_SUBDOMINIOS:
                subdomain = CURSOS_SUBDOMINIOS[0].strip()
        except Exception:
            pass
        if not subdomain:
            subdomain = 'tecladistapop'
        product_id = _product_id_por_subdominio(subdomain)
        ok, status, detalhe = _validar_token_club(session, subdomain, product_id)
        if not ok:
            print(
                "Token inválido, incompleto ou expirado.\n"
                "Com o curso aberto em hotmart.com/pt-br/club/..., copie de novo o "
                "Authorization (consumption-gateway ou api-club).\n"
                f"Detalhe: HTTP {status}" + (f" — {detalhe}" if detalhe else "")
            )
            loga(".", "ERROR", f"Token rejeitado na api-club: HTTP {status} {detalhe}")
            exit(13)
        loga(".", "INFO", "Token aceito pela api-club")
        return session, params

    # 2) Fallback: email/senha nos endpoints atuais
    email = kwargs.get("email", None)
    if email is None:
        email = str(input("Qual o email de login?\n"))
    senha = kwargs.get("senha", None)
    if senha is None:
        senha = str(input("Qual a senha de login?\n"))

    try:
        access_token = _obter_token_por_senha(authMart, email, senha)
    except RuntimeError as e:
        print(
            "\nNão foi possível autenticar com email/senha.\n"
            "Isso é esperado: o endpoint Sparkle retorna 403 e o SSO novo usa WAF/OIDC.\n"
            "Rode de novo e cole o Bearer token do navegador (veja as instruções acima).\n"
            f"Detalhe técnico: {e}\n"
        )
        loga(".", "ERROR", f"Autenticação por senha esgotou endpoints: {e}")
        exit(13)

    return _sessao_com_token(access_token)


def listacursos(authMart, params):
    import json

    # check_token rejeita tokens OIDC do Club ("Client not valid: b432cdd3-...").
    # Tenta mesmo assim; se falhar, usa config_cursos.py.
    produtos = []
    try:
        check_resp = authMart.get(
            'https://api-sec-vlc.hotmart.com/security/oauth/check_token',
            params=params,
            timeout=30,
        )
        check_token_response = check_resp.json()
        with open("api_response_debug.json", "w", encoding="utf-8") as f:
            json.dump(check_token_response, f, indent=2, ensure_ascii=False)

        if check_token_response.get('error'):
            loga(".", "WARN",
                 f"check_token indisponível para este token "
                 f"({check_token_response.get('error')}: {check_token_response.get('error_description')}). "
                 f"Usando config_cursos.py.")
            print("\nAVISO: check_token não lista cursos com token do Club (esperado).")
            print("Usando subdomínios de config_cursos.py.")
        else:
            produtos = check_token_response.get('resources', [])
            loga(".", "DEBUG", "Resposta do check_token salva em api_response_debug.json")
    except Exception as e:
        loga(".", "WARN", f"Falha ao chamar check_token: {e}")
        print("\nAVISO: não foi possível listar cursos via check_token.")

    # Se não encontrou produtos via API, tenta carregar do arquivo de configuração
    if not produtos:
        loga(".", "WARN", "Nenhum produto encontrado no check_token")
        print("\nAVISO: A API não retornou cursos automaticamente.")
        
        # Tenta importar do arquivo de configuração
        try:
            from config_cursos import CURSOS_SUBDOMINIOS
            if CURSOS_SUBDOMINIOS:
                print(f"\nEncontrados {len(CURSOS_SUBDOMINIOS)} curso(s) no arquivo config_cursos.py")
                for subdomain in CURSOS_SUBDOMINIOS:
                    subdomain = subdomain.strip()
                    resource = {
                        'subdomain': subdomain,
                        'status': 'ACTIVE',
                    }
                    pid = _product_id_por_subdominio(subdomain)
                    if pid:
                        resource['product_id'] = pid
                    produtos.append({
                        'resource': resource,
                        'roles': ['STUDENT']
                    })
                loga(".", "INFO", f"Carregados {len(CURSOS_SUBDOMINIOS)} cursos do arquivo de configuração")
            else:
                print("\nAVISO: O arquivo config_cursos.py está vazio.")
        except ImportError:
            print("\nAVISO: Arquivo config_cursos.py não encontrado.")
        except Exception as e:
            loga(".", "ERROR", f"Erro ao carregar config_cursos.py: {e}")
            print(f"\nAVISO: Erro ao carregar configuração: {e}")
        
        # Se ainda não tem cursos, permite entrada manual
        if not produtos:
            print("\nPara encontrar o subdomínio do seu curso:")
            print("1. Acesse https://sun.hotmart.com/minhas-compras")
            print("2. Clique em 'Acessar' no curso desejado")
            print("3. Na URL você verá: https://hotmart.com/pt-br/club/SUBDOMAIN/...")
            print("4. O 'SUBDOMAIN' é o que você precisa informar")
            print("\nDica: Edite o arquivo 'config_cursos.py' para salvar os subdomínios permanentemente\n")
            
            # Permite adicionar múltiplos cursos manualmente
            subdominios_manuais = []
            while True:
                subdomain = input("Digite o subdomínio do curso (ou pressione Enter para finalizar): ").strip()
                if not subdomain:
                    if not subdominios_manuais:
                        print("AVISO: Nenhum curso adicionado. Finalizando...")
                        exit(0)
                    break
                subdominios_manuais.append(subdomain)
                print(f"Subdomínio '{subdomain}' adicionado\n")
            
            # Cria produtos com os subdomínios manuais
            for subdomain in subdominios_manuais:
                produtos.append({
                    'resource': {
                        'subdomain': subdomain,
                        'status': 'ACTIVE'
                    },
                    'roles': ['STUDENT']
                })
            
            loga(".", "INFO", f"Adicionados {len(subdominios_manuais)} cursos manualmente")

    loga(".", "INFO", f"Listando produtos da conta.")
    loga(".", "DEBUG", f"Total de produtos encontrados: {len(produtos)}")

    cursosValidos = []
    for idx, i in enumerate(produtos):
        try:
            loga(".", "DEBUG", f"Produto {idx + 1}: status={i.get('resource', {}).get('status')}, roles={i.get('roles')}")
            
            if i['resource']['status'] == "ACTIVE" and "STUDENT" in i['roles']:
                dominio = i['resource']['subdomain']
                product_id = i['resource'].get('product_id')
                loga(".", "DEBUG", f"Produto válido encontrado. Domínio: {dominio}")
                i["nome"] = _obter_nome_curso(authMart, dominio, product_id)
                loga(".", "DEBUG", f"Nome do curso obtido: {i['nome']}")
                cursosValidos.append(i)
            else:
                loga(".", "DEBUG", f"Produto {idx + 1} não atende aos critérios (ACTIVE + STUDENT)")
        except KeyError as e:
            loga(".", "WARN", f"Produto presumido como inválido. Erro: {e}")
            loga(".", "WARN", f"{i}")
            continue
        except Exception as e:
            loga(".", "ERROR", f"Erro ao processar produto: {e}")
            loga(".", "ERROR", f"{i}")
            continue
    
    print(f"\n=== Cursos disponíveis ({len(cursosValidos)} encontrado(s)) ===")
    for i, curso in enumerate(cursosValidos, start=1):
        print(f"{i}. {curso['nome']}")
    opcao = int(input('Qual curso deseja baixar?\n')) - 1
    nmcurso = slugify(cursosValidos[opcao]['nome'])

    loga(".", "INFO", f"Iniciando download do curso {nmcurso}")
    loga(".", "INFO", f"{cursosValidos[opcao]}")
    desempenho = _carregar_desempenho()
    _limpar_cache_paginas()
    first_folder = f'Cursos/{nmcurso}'
    if not os.path.exists(first_folder):
        os.makedirs(first_folder)
    dominio = cursosValidos[opcao]['resource']['subdomain']
    product_id = cursosValidos[opcao]['resource'].get('product_id')
    authMart.hotmart_subdomain = dominio
    authMart.hotmart_product_id = product_id or _product_id_por_subdominio(dominio)
    curso = _get_navigation_json(
        authMart, dominio, authMart.hotmart_product_id,
    )

    progresso = _carregar_progresso(first_folder)
    retomar = False
    if progresso and progresso.get('status') == 'em_andamento':
        q = progresso.get('qualidade')
        n_mod = len(progresso.get('module_orders') or [])
        qlabel = f"{q}p" if q else "máxima"
        feitas = progresso.get('aulas_feitas')
        total = progresso.get('aulas_total')
        progresso_aulas = (
            f"\n  Aulas: {feitas}/{total}"
            if feitas is not None and total
            else ""
        )
        print(
            f"\n=== Download incompleto encontrado ===\n"
            f"  Curso: {nmcurso}\n"
            f"  Qualidade: {qlabel}\n"
            f"  Tópicos salvos: {n_mod}"
            f"{progresso_aulas}\n"
            f"  Arquivos já baixados serão pulados."
        )
        raw_retoma = input("Continuar de onde parou? [S/n]\n> ").strip().lower()
        retomar = raw_retoma in ('', 's', 'sim', 'y', 'yes')

    if retomar:
        qualidade_video = int(progresso.get('qualidade') or 0)
        orders = set(progresso.get('module_orders') or [])
        todos = sorted(curso.get('modules') or [], key=lambda m: m.get('moduleOrder', 0))
        modulos_escolhidos = [m for m in todos if m.get('moduleOrder') in orders]
        if not modulos_escolhidos:
            print("Progresso inválido (tópicos não encontrados). Seleção manual.")
            qualidade_video = _selecionar_qualidade()
            modulos_escolhidos = _selecionar_modulos(curso.get('modules') or [])
            retomar = False
        else:
            qlabel = f"{qualidade_video}p" if qualidade_video else "qualidade máxima"
            print(f"Retomando {len(modulos_escolhidos)} tópico(s) — {qlabel}.")
            loga(first_folder, "INFO", f"Retomando download (qualidade={qualidade_video})")
    else:
        qualidade_video = _selecionar_qualidade()
        modulos_escolhidos = _selecionar_modulos(
            curso.get('modules') or [],
            raw=_topicos_raw_de_config(),
        )

    plano = _plano_aulas(modulos_escolhidos)
    if retomar:
        aulas_selecionadas, videos_por_aula = _escopo_de_progresso(progresso, plano, authMart)
    else:
        aulas_selecionadas, videos_por_aula = _selecionar_escopo_aulas(plano, authMart)
    plano_filtrado = [p for p in plano if p['idx'] in aulas_selecionadas]
    hash_para_idx = {p['hash']: p['idx'] for p in plano_filtrado}

    if desempenho['download_paralelo'] > 1:
        print(
            f"\nDesempenho: até {desempenho['download_paralelo']} vídeos Hotmart em paralelo "
            f"(ajuste DOWNLOAD_PARALELO em config_cursos.py)."
        )
    if not desempenho['medir_duracao']:
        print(
            "Dica: ffprobe desligado por padrão (mais rápido). "
            "MEDIR_DURACAO_VIDEO = True para barra de % mais precisa.\n"
        )

    _salvar_progresso(first_folder, {
        'status': 'em_andamento',
        'curso': nmcurso,
        'qualidade': qualidade_video,
        'module_orders': [m.get('moduleOrder') for m in modulos_escolhidos],
        'module_names': [
            re.sub(r'[<>:"/\\|?*]', '', m.get('name', '')).strip()
            for m in modulos_escolhidos
        ],
        'aulas_indices': sorted(aulas_selecionadas),
        'videos_por_aula': _serializar_videos_por_aula(videos_por_aula),
    })

    estrutura = {}
    tempAula = []
    aulas = []
    tempAnexo = []
    tempLink = []
    x = 0

    loga(first_folder, "INFO", "Estrutura obtida com sucesso, criando dicionário")
    loga(first_folder, "INFO", f"Módulos selecionados: {[m.get('name') for m in modulos_escolhidos]}")
    loga(
        first_folder, "INFO",
        f"Aulas selecionadas: {sorted(aulas_selecionadas)} | vídeos filtrados: {videos_por_aula}",
    )

    print(f"Carregando metadados de {len(plano_filtrado)} aula(s)...")
    pares_aula = _carregar_estrutura_aulas(
        authMart, plano_filtrado, desempenho['api_paralelo'],
    )
    for item, aulas in pares_aula:
        modulo = item['module']
        mod_name = _nome_arquivo_seguro(modulo['name'])
        if modulo['moduleOrder'] not in estrutura:
            estrutura[modulo['moduleOrder']] = {mod_name: []}
        elif mod_name not in estrutura[modulo['moduleOrder']]:
            estrutura[modulo['moduleOrder']][mod_name] = []
        x += 1
        print(f"Aulas contabilizadas: {x}/{len(plano_filtrado)}")
        estrutura[modulo['moduleOrder']][mod_name].append(aulas)

    # Dump do dict caso algo estranho ocorra a pessoa possa mandar, usar prettify.py para ver a monstruosidade
    with open(first_folder + '/debug.txt', 'a', encoding='utf-8') as debug:
        debug.write(str(modulos_escolhidos) + '\n\n\n' + str(estrutura))

    loga(first_folder, "INFO", "Dicionário criado com sucesso, dumpado como debug.txt")
    loga(first_folder, "INFO", f"Total de aulas no curso {nmcurso} {str(x)}")
    print(
        "\nDica: pode interromper (Ctrl+C) e rodar de novo — "
        "arquivos prontos serão pulados e o download continua de onde parou.\n"
    )
    videos_baixados = 0
    videos_pulados = 0
    total_aulas = _contar_aulas(estrutura) or x or 1
    aula_atual = 0
    paralelo = desempenho['download_paralelo'] > 1
    gerenciador_videos = _GerenciadorDownloadsVideo(desempenho['download_paralelo'])
    opts_video = {
        'medir_duracao': desempenho['medir_duracao'],
        'mostrar_progresso': not paralelo,
        'corrigir_sync_av': desempenho['corrigir_sync_av'],
    }

    stats_lock = threading.Lock()

    for modulo in estrutura:
        for aulas in estrutura[modulo]:
            folder_path = f'{first_folder}/{slugify(str(modulo))}_{slugify(aulas)}'
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)

                loga(first_folder, "INFO", f"Criada a pasta do módulo {str(modulo)}.{aulas}")

            for aula in estrutura[modulo][aulas]:
                aula_idx = hash_para_idx.get(aula[2])
                page_order, lesson_name = aula[0], aula[1]
                aula_atual += 1
                pct_geral = int(100 * aula_atual / total_aulas)
                so_videos = _aula_apenas_videos(aula_idx, videos_por_aula)
                print(
                    f"\n[{aula_atual}/{total_aulas}] {_barra(pct_geral)} {pct_geral}%  "
                    f"{page_order}. {lesson_name}"
                )
                print(f"  Tópico: {folder_path}")
                _salvar_progresso(first_folder, {
                    'status': 'em_andamento',
                    'curso': nmcurso,
                    'qualidade': qualidade_video,
                    'module_orders': [m.get('moduleOrder') for m in modulos_escolhidos],
                    'module_names': [
                        re.sub(r'[<>:"/\\|?*]', '', m.get('name', '')).strip()
                        for m in modulos_escolhidos
                    ],
                    'aulas_feitas': aula_atual - 1,
                    'aulas_total': total_aulas,
                    'aula_atual': f"{aula[0]}. {aula[1]}",
                    'aulas_indices': sorted(aulas_selecionadas),
                    'videos_por_aula': _serializar_videos_por_aula(videos_por_aula),
                })
                if not so_videos and _aula_ja_completa_na_pasta(folder_path, aula):
                    n_v = len(aula[3]['videos']) or 0
                    if n_v:
                        videos_pulados += n_v
                    print("  [OK] Arquivos da aula já estão na pasta — pulando para a próxima")
                    loga(
                        first_folder, "INFO",
                        f"Aula completa na pasta, pulada: {aula[0]}. {aula[1]}",
                    )
                    continue

                descricao_path = _caminho_descricao_aula(folder_path, page_order, lesson_name)
                if so_videos:
                    print("  Modo vídeo específico — pulando descrição/anexos desta aula")
                elif _arquivo_pronto(descricao_path, min_bytes=32):
                    print("  [OK] descrição já presente, pulando")
                    loga(first_folder, "INFO", f"Descrição já existente: {descricao_path}")
                elif not so_videos:
                    try:
                        desct = _get_page_json(authMart, aula[2])['content']
                        os.makedirs(os.path.dirname(descricao_path), exist_ok=True)
                        with open(descricao_path, 'w', encoding='utf-8') as dd:
                            dd.write(str(desct))
                            loga(
                                first_folder, "INFO",
                                f"Descrição salva com sucesso, aula {page_order}.{lesson_name}",
                            )
                    except KeyError:
                        print("Aula sem descrição/não textual")
                    except Exception:
                        print("Erro ao salvar descrição, churrasque-se")
                        loga(
                            first_folder, "ERROR",
                            f"Falha ao salvar a descrição da aula {str(aula[0])}. {aula[1]}",
                        )

                if not aula[3]['videos']:

                    loga(first_folder, "WARN",
                         "Aula não continha dicionário de videos, verificando por externos, verificar se é textual")

                    try:
                        pjson = BeautifulSoup(
                            _get_page_json(authMart, aula[2])['content'],
                            features="html.parser",
                        )
                        viframe = pjson.findAll("iframe")
                        for x, i in enumerate(viframe, start=1):
                            if not _video_incluido_no_escopo(aula_idx, x, videos_por_aula):
                                continue
                            if 'player.vimeo' in i.get("src"):
                                youtube_dl.utils.std_headers['Referer'] = _referer_club(dominio)

                                loga(first_folder, "INFO", f"Vídeo encontrado! {i.get('src')}")

                                if '?' in i.get("src"):
                                    linkV = i.get("src").split('?')[0]
                                else:
                                    linkV = i.get("src")
                                if linkV[-1] == "/":
                                    linkV = linkV.split("/")[-1]

                            elif 'vimeo.com' in i.get("src"):
                                youtube_dl.utils.std_headers['Referer'] = _referer_club(dominio)

                                loga(first_folder, "INFO", f"Vídeo encontrado! {i.get('src')}")

                                vimeoID = i.get("src").split('vimeo.com/')[1]
                                if "?" in vimeoID:
                                    vimeoID = vimeoID.split("?")[0]
                                linkV = "https://player.vimeo.com/video/" + vimeoID

                            elif "wistia.com" in i.get("src"):

                                loga(first_folder, "ERROR", f"WISTIA! Vídeo encontrado! {i.get('src')}")

                                # Método de download caiu, era pelo bin :( Ajuda noix Telegram: @katomaro
                                pass

                            elif "youtube.com" in i.get("src") or "youtu.be" in i.get("src"):

                                loga(first_folder, "INFO", f"Vídeo encontrado! {i.get('src')}")

                                linkV = i.get("src")
                            destino_video = _caminho_video_no_topico(
                                folder_path, page_order, lesson_name, x, total_videos=1,
                            )
                            pronto, existente = _video_ja_baixado(
                                folder_path, page_order, lesson_name, x, total_videos=1,
                            )
                            if pronto:
                                print(f"  [OK] Aula já presente ({existente}), pulando")
                                loga(first_folder, "INFO", f"Aula externa já presente: {existente}")
                                videos_pulados += 1
                            else:
                                _limpar_parcial(destino_video)
                                print(f"  Baixando aula externa\n\t {destino_video}")
                                ydl_opts = {
                                    "format": _ydl_format_por_qualidade(qualidade_video),
                                    'outtmpl': destino_video,
                                    'continuedl': True,
                                    'nooverwrites': False,
                                }
                                with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                                    ydl.download([linkV])
                                    loga(first_folder, "INFO", f"Vídeo externo baixado com sucesso.")
                                if _arquivo_pronto(destino_video):
                                    videos_baixados += 1
                                else:
                                    _limpar_parcial(destino_video)
                                    print("  Vídeo externo incompleto — será tentado de novo na próxima execução")
                                    loga(first_folder, "WARN", "Vídeo externo incompleto após download")

                    except KeyboardInterrupt:
                        raise
                    except:

                        loga(first_folder, "WARN",
                             "Plataforma não retornou vídeos, verificar se é postagem (aula textual)")

                        pass

                else:  # 0 nome, 1 id, 2 link
                    total_vids = len(aula[3]['videos'])
                    for x, i in enumerate(aula[3]['videos'], start=1):
                        if not _video_incluido_no_escopo(aula_idx, x, videos_por_aula):
                            continue
                        destino_video = _caminho_video_no_topico(
                            folder_path, page_order, lesson_name, x, total_videos=total_vids,
                        )
                        pronto, existente = _video_ja_baixado(
                            folder_path, page_order, lesson_name, x, i[0],
                            total_videos=total_vids,
                        )
                        if pronto:
                            print(f"  [OK] Vídeo {x}/{total_vids} já presente ({existente}), pulando")
                            loga(first_folder, "INFO", f"Vídeo já presente: {existente}")
                            videos_pulados += 1
                        else:
                            _limpar_parcial(destino_video)
                            print(f"  Baixando vídeo {x}/{total_vids}: {destino_video}")
                            loga(first_folder, "INFO", f"Tentando baixar a aula {str(x)} ({lesson_name})")
                            try:
                                if paralelo:
                                    def _job(
                                        url=i[2], vhash=i[1], dest=destino_video,
                                    ):
                                        nonlocal videos_baixados
                                        baixar_video_hotmart(
                                            url, vhash, dest, first_folder,
                                            qualidade=qualidade_video,
                                            **opts_video,
                                        )
                                        with stats_lock:
                                            videos_baixados += 1
                                    gerenciador_videos.run(_job)
                                else:
                                    baixar_video_hotmart(
                                        i[2], i[1], destino_video, first_folder,
                                        qualidade=qualidade_video,
                                        **opts_video,
                                    )
                                    videos_baixados += 1
                            except KeyboardInterrupt:
                                _limpar_parcial(destino_video)
                                raise
                            except FileNotFoundError:
                                msg = "ffmpeg não encontrado no PATH. Instale com: brew install ffmpeg"
                                print(f"  {msg}")
                                loga(first_folder, "ERROR", msg)
                            except Exception as e:
                                _limpar_parcial(destino_video)
                                loga(first_folder, "ERROR", f"Erro ao baixar vídeo Hotmart: {e}")
                                print(f"  {e}")
                            pausa = desempenho['pausa_entre_videos']
                            if pausa and not paralelo:
                                time.sleep(pausa)

                if so_videos:
                    continue

                if aula[4]['anexos']:  # 0 id 1 nome
                    print(f"\n{len(aula[4]['anexos'])} anexo(s) encontrado(s) para a aula: {lesson_name}")
                    pasta_materiais = _pasta_materiais_topico(folder_path)
                    os.makedirs(pasta_materiais, exist_ok=True)
                    loga(first_folder, "INFO", f"Materiais do tópico: {pasta_materiais}")

                    anexos_baixados = 0
                    anexos_pulados = 0
                    anexos_falhos = 0

                    for idx, i in enumerate(aula[4]['anexos'], 1):
                        anexo_id = i[0]
                        anexo_nome = i[1]
                        destino_anexo = _caminho_anexo_aula(
                            folder_path, page_order, lesson_name, anexo_nome,
                        )
                        legado_anexo = os.path.join(
                            _pasta_aula_legada(folder_path, page_order, lesson_name),
                            'Materiais', anexo_nome,
                        )
                        
                        print(f"  [{idx}/{len(aula[4]['anexos'])}] {anexo_nome}")
                        
                        if _anexo_ja_baixado(destino_anexo):
                            file_size = os.path.getsize(destino_anexo)
                            print(f"      [OK] Já existe ({file_size} bytes) - pulando")
                            loga(
                                first_folder, "INFO",
                                f"Anexo já existente: {anexo_nome} ({file_size} bytes)",
                            )
                            anexos_pulados += 1
                            continue
                        if _anexo_ja_baixado(legado_anexo):
                            file_size = os.path.getsize(legado_anexo)
                            print(f"      [OK] Já existe no layout antigo ({file_size} bytes) - pulando")
                            anexos_pulados += 1
                            continue
                        if os.path.isfile(destino_anexo):
                            print("      [AVISO] Arquivo existe mas está vazio - rebaixando")
                            loga(first_folder, "WARN", f"Anexo vazio detectado, rebaixando: {anexo_nome}")
                            os.remove(destino_anexo)
                        
                        # Tenta baixar com retry
                        max_tentativas = 3
                        sucesso = False
                        
                        for tentativa in range(1, max_tentativas + 1):
                            try:
                                if tentativa > 1:
                                    print(f"      [RETRY] Tentativa {tentativa}/{max_tentativas}...")
                                    time.sleep(2)  # Aguarda antes de retry
                                
                                loga(first_folder, "INFO", f"Baixando anexo {anexo_nome} (tentativa {tentativa})")
                                
                                # Tenta obter URL de download
                                response = authMart.get(
                                    f'https://api-club.hotmart.com/hot-club-api/rest/v3/attachment/{anexo_id}/download',
                                    timeout=30
                                )
                                
                                if response.status_code != 200:
                                    raise Exception(f"Erro HTTP {response.status_code}: {response.text[:100]}")
                                
                                anexo_info = response.json()
                                
                                # Tenta baixar via directDownloadUrl
                                if 'directDownloadUrl' in anexo_info:
                                    print(f"      [DOWNLOAD] Baixando via directDownloadUrl...")
                                    anexo = requests.get(anexo_info['directDownloadUrl'], timeout=60)
                                    
                                    if anexo.status_code != 200:
                                        raise Exception(f"Erro ao baixar: HTTP {anexo.status_code}")
                                
                                # Fallback para lambdaUrl
                                elif 'lambdaUrl' in anexo_info:
                                    print(f"      [DOWNLOAD] Baixando via lambdaUrl...")
                                    vrum = requests.session()
                                    vrum.headers.update(authMart.headers)
                                    vrum.headers['token'] = anexo_info.get('token', '')
                                    
                                    lambda_response = vrum.get(anexo_info['lambdaUrl'], timeout=30)
                                    download_url = lambda_response.text
                                    anexo = requests.get(download_url, timeout=60)
                                    del vrum
                                    
                                    if anexo.status_code != 200:
                                        raise Exception(f"Erro ao baixar via lambda: HTTP {anexo.status_code}")
                                else:
                                    raise Exception("Nenhuma URL de download encontrada na resposta da API")
                                
                                # Valida o conteúdo
                                if not anexo.content or len(anexo.content) == 0:
                                    raise Exception("Conteúdo vazio recebido")
                                
                                # Salva o arquivo
                                with open(destino_anexo, 'wb') as ann:
                                    ann.write(anexo.content)
                                
                                # Verifica se foi salvo corretamente
                                if not os.path.exists(destino_anexo):
                                    raise Exception("Arquivo não foi salvo")
                                
                                file_size = os.path.getsize(destino_anexo)
                                if file_size == 0:
                                    raise Exception("Arquivo salvo está vazio")
                                
                                # Sucesso!
                                print(f"      [OK] Baixado com sucesso ({file_size} bytes)")
                                loga(first_folder, "INFO", f"Anexo baixado: {anexo_nome} ({file_size} bytes)")
                                anexos_baixados += 1
                                sucesso = True
                                break
                                
                            except Exception as e:
                                erro_msg = str(e)
                                loga(first_folder, "ERROR", f"Erro ao baixar anexo {anexo_nome} (tentativa {tentativa}): {erro_msg}")
                                
                                if tentativa == max_tentativas:
                                    print(f"      [ERRO] FALHA após {max_tentativas} tentativas: {erro_msg}")
                                    anexos_falhos += 1
                                    
                                    # Remove arquivo parcial se existir
                                    if os.path.exists(destino_anexo):
                                        try:
                                            os.remove(destino_anexo)
                                        except OSError:
                                            pass
                                else:
                                    print(f"      [AVISO] Erro: {erro_msg}")
                        
                        # Pequena pausa entre downloads
                        if sucesso:
                            time.sleep(0.5)
                    
                    # Resumo dos anexos
                    print(f"\n  [RESUMO] Anexos:")
                    print(f"     Baixados: {anexos_baixados}")
                    print(f"     Pulados: {anexos_pulados}")
                    if anexos_falhos > 0:
                        print(f"     Falhas: {anexos_falhos}")
                    print()
                    
                    loga(first_folder, "INFO", f"Anexos processados - Baixados: {anexos_baixados}, Pulados: {anexos_pulados}, Falhas: {anexos_falhos}")

                # Processar PDFs embutidos no campo 'content' (Google Drive iframes)
                try:
                    aula_completa = _get_page_json(authMart, aula[2])
                    content_html = aula_completa.get('content', '')
                    
                    if content_html:
                        google_drive_files = extrair_google_drive_urls(content_html)
                        
                        if google_drive_files:
                            print(f"\n{len(google_drive_files)} arquivo(s) do Google Drive encontrado(s) no conteúdo")
                            
                            os.makedirs(_pasta_materiais_topico(folder_path), exist_ok=True)

                            gdrive_baixados = 0
                            gdrive_pulados = 0
                            gdrive_falhos = 0

                            for idx, (file_id, preview_url, download_url) in enumerate(google_drive_files, 1):
                                output_path = _caminho_gdrive_aula(
                                    folder_path, page_order, lesson_name, file_id,
                                )
                                file_name = os.path.basename(output_path)

                                print(f"  [{idx}/{len(google_drive_files)}] {file_name}")
                                
                                # Verifica se já existe
                                if _anexo_ja_baixado(output_path):
                                    file_size = os.path.getsize(output_path)
                                    print(f"      [OK] Já existe ({file_size} bytes) - pulando")
                                    loga(first_folder, "INFO", f"Google Drive file já existente: {file_name}")
                                    gdrive_pulados += 1
                                    continue
                                if os.path.isfile(output_path):
                                    print("      [AVISO] Arquivo existe mas está vazio - rebaixando")
                                    os.remove(output_path)
                                
                                # Tenta baixar
                                print(f"      [DOWNLOAD] Baixando do Google Drive...")
                                sucesso = baixar_google_drive(file_id, download_url, output_path, first_folder)
                                
                                if sucesso:
                                    print(f"      [OK] Baixado com sucesso")
                                    gdrive_baixados += 1
                                else:
                                    print(f"      [ERRO] Falha no download")
                                    gdrive_falhos += 1
                                
                                time.sleep(1)  # Pausa entre downloads
                            
                            # Resumo
                            print(f"\n  [RESUMO] Arquivos do Google Drive:")
                            print(f"     Baixados: {gdrive_baixados}")
                            print(f"     Pulados: {gdrive_pulados}")
                            if gdrive_falhos > 0:
                                print(f"     Falhas: {gdrive_falhos}")
                            print()
                            
                            loga(first_folder, "INFO", f"Google Drive files - Baixados: {gdrive_baixados}, Pulados: {gdrive_pulados}, Falhas: {gdrive_falhos}")
                
                except Exception as e:
                    loga(first_folder, "ERROR", f"Erro ao processar conteúdo Google Drive: {str(e)}")

                if aula[5]['links']:  # 0 nome 1 url
                    os.makedirs(_pasta_materiais_topico(folder_path), exist_ok=True)
                    links_path = _caminho_links_aula(folder_path, page_order, lesson_name)
                    print(f"Salvando links encontrados para a aula\n\t {links_path}")
                    loga(first_folder, "INFO", f"Links detectados para a aula {page_order}.{lesson_name}")
                    with open(links_path, "a", encoding="utf-8") as linkz:
                        for i in aula[5]['links']:
                            linkz.write(f"{i[0]}: {i[1]}\n")
                    loga(first_folder, "INFO", "Links salvos")

    gerenciador_videos.aguardar()

    _salvar_progresso(first_folder, {
        'status': 'concluido',
        'curso': nmcurso,
        'qualidade': qualidade_video,
        'module_orders': [m.get('moduleOrder') for m in modulos_escolhidos],
        'module_names': [
            re.sub(r'[<>:"/\\|?*]', '', m.get('name', '')).strip()
            for m in modulos_escolhidos
        ],
        'aulas_feitas': total_aulas,
        'aulas_total': total_aulas,
        'aulas_indices': sorted(aulas_selecionadas),
        'videos_por_aula': _serializar_videos_por_aula(videos_por_aula),
    })
    print(f"\n[{total_aulas}/{total_aulas}] {_barra(100)} 100%")
    print(f"[RESUMO] Vídeos — baixados: {videos_baixados} | já existiam: {videos_pulados}")
    loga(first_folder, "INFO", f"Download concluído. Vídeos novos: {videos_baixados}, pulados: {videos_pulados}")


# login = {"email": "EMAIL@EMAIL", "senha": "SENHA"}
if __name__ == '__main__':
    login = {
        "Info": "Pode colocar o email/senha ali em cima e apagar esse dicionário para deixar os dados salvos no script",
        "autor": "Telegram: @katomaro"}

    try:
        listacursos(*autenticacao(**login))
    except KeyboardInterrupt:
        print(
            "\n\nDownload interrompido. Rode o script de novo, escolha o mesmo curso "
            "e confirme 'Continuar de onde parou'.\n"
            "Arquivos já baixados serão pulados; o vídeo incompleto reinicia.\n"
        )
