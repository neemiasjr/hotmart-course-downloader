"""Vídeos externos (YouTube/Vimeo) e arquivos do Google Drive."""

import os
import re
import subprocess

import requests
import youtube_dl
from bs4 import BeautifulSoup

from .api import _referer_club
from .caminhos import _limpar_parcial
from .console import (
    _barra,
    _fmt_bytes,
    _fmt_tempo,
    _imprimir_progresso_linha,
    _print_seguro,
    loga,
)


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


def _ydl_format_por_qualidade(qualidade=0):
    """Formato youtube-dl limitado à altura máxima desejada."""
    if not qualidade:
        return "best"
    return (
        f"bestvideo[height<={qualidade}]+bestaudio/"
        f"best[height<={qualidade}]/best"
    )


def _normalizar_url_iframe(src):
    src = (src or '').strip()
    if src.startswith('//'):
        src = 'https:' + src
    return src


def _url_parece_video_externo(url):
    u = (url or '').lower()
    return (
        'youtube.com' in u or 'youtu.be' in u
        or 'vimeo.com' in u or 'player.vimeo' in u
    )


def _normalizar_url_youtube(url):
    """Embed/live → watch (yt-dlp/youtube-dl entendem melhor)."""
    url = _normalizar_url_iframe(url)
    m = re.search(
        r'(?:youtube\.com/(?:embed|live)/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        url,
    )
    if m:
        return f'https://www.youtube.com/watch?v={m.group(1)}'
    m = re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', url)
    if m:
        return f'https://www.youtube.com/watch?v={m.group(1)}'
    return url


def _link_video_externo_iframe(src, dominio):
    """
    Converte src de iframe (Vimeo/YouTube) em URL para youtube-dl.
    Mantém query string do Vimeo (?h=...) necessária para vídeos privados.
    """
    src = _normalizar_url_iframe(src)
    if not src:
        return None
    if 'player.vimeo' in src or 'vimeo.com' in src:
        if dominio:
            youtube_dl.utils.std_headers['Referer'] = _referer_club(dominio)
        if 'player.vimeo' in src:
            return src
        vimeo_id = src.split('vimeo.com/', 1)[-1]
        if '?' in vimeo_id:
            vimeo_id = vimeo_id.split('?', 1)[0]
        vimeo_id = vimeo_id.strip('/')
        return f"https://player.vimeo.com/video/{vimeo_id}"
    if 'youtube.com' in src or 'youtu.be' in src:
        return _normalizar_url_youtube(src)
    return None


def _extrair_candidatos_video_externo_html(html_content):
    """Iframes e links YouTube/Vimeo no HTML da aula."""
    if not html_content:
        return []
    soup = BeautifulSoup(html_content, features='html.parser')
    candidatos = []
    for iframe in soup.find_all('iframe'):
        src = iframe.get('src') or iframe.get('data-src') or ''
        if _url_parece_video_externo(src):
            candidatos.append(src)
    for anchor in soup.find_all('a', href=True):
        href = anchor.get('href') or ''
        if _url_parece_video_externo(href):
            candidatos.append(href)
    return candidatos


def _listar_links_video_externo(conteudo_html, registros_video, dominio):
    """URLs únicas para download (API mediasSrc + conteúdo HTML)."""
    vistos = set()
    links = []

    def _adicionar(raw):
        if not raw or 'wistia.com' in raw.lower():
            return
        link = _link_video_externo_iframe(raw, dominio)
        if not link:
            return
        # no YouTube o ID do vídeo está na query (watch?v=ID)
        chave = link if 'youtube.com/watch' in link else re.sub(r'\?.*', '', link)
        if chave in vistos:
            return
        vistos.add(chave)
        links.append(link)

    for item in registros_video or []:
        if len(item) > 2 and _url_parece_video_externo(item[2]):
            _adicionar(item[2])
    for raw in _extrair_candidatos_video_externo_html(conteudo_html):
        _adicionar(raw)
    return links


def _formato_ytdlp(qualidade_video):
    if not qualidade_video:
        return 'bestvideo+bestaudio/best'
    q = int(qualidade_video)
    return (
        f'bestvideo[height<={q}]+bestaudio/'
        f'best[height<={q}]/best'
    )


def _hook_progresso_download_externo(d):
    """Barra ao vivo para yt-dlp / youtube-dl (mesmo estilo do ffmpeg)."""
    status = d.get('status')
    if status == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate')
        baixado = d.get('downloaded_bytes') or 0
        velocidade = d.get('speed') or 0
        eta = d.get('eta')
        if total:
            pct = 100.0 * baixado / total
            eta_txt = f"  ETA {_fmt_tempo(eta)}" if eta is not None else ''
            vel_txt = f"  {_fmt_bytes(velocidade)}/s" if velocidade else ''
            _imprimir_progresso_linha(
                f"  {_barra(pct)} {int(pct):3d}%  "
                f"{_fmt_bytes(baixado)}/{_fmt_bytes(total)}{vel_txt}{eta_txt}    ",
            )
        elif baixado:
            _imprimir_progresso_linha(
                f"  {_barra(0)} ...  {_fmt_bytes(baixado)} baixados    ",
            )
    elif status == 'finished':
        fname = d.get('filename') or d.get('info_dict', {}).get('_filename', '')
        size = os.path.getsize(fname) if fname and os.path.isfile(fname) else 0
        _imprimir_progresso_linha(
            f"  {_barra(100)} 100%  "
            f"{_fmt_bytes(size) if size else 'ok'}  (mesclando se necessário)    ",
        )


def _baixar_video_externo(
    link, destino, first_folder, qualidade_video, dominio, mostrar_progresso=True,
):
    """YouTube/Vimeo via yt-dlp (preferido) ou youtube-dl."""
    _limpar_parcial(destino)
    hooks = [_hook_progresso_download_externo] if mostrar_progresso else []
    ytdlp_fmt = _formato_ytdlp(qualidade_video)

    try:
        import yt_dlp
    except ImportError:
        yt_dlp = None

    if yt_dlp is not None:
        opts = {
            'format': ytdlp_fmt,
            'merge_output_format': 'mp4',
            'noplaylist': True,
            'outtmpl': destino,
            'quiet': True,
            'no_warnings': True,
            'retries': 3,
        }
        if hooks:
            opts['progress_hooks'] = hooks
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([link])
            if mostrar_progresso:
                size = os.path.getsize(destino) if os.path.isfile(destino) else 0
                _imprimir_progresso_linha(
                    f"  {_barra(100)} 100%  {_fmt_bytes(size)}    ",
                )
                _print_seguro('')
            return
        except Exception as err:
            loga(first_folder, "WARN", f"yt-dlp (lib) falhou ({link}): {err}")

    cmd = [
        'yt-dlp',
        '-f', ytdlp_fmt,
        '--merge-output-format', 'mp4',
        '--no-playlist',
        '--newline',
        '-o', destino,
        link,
    ]
    if not mostrar_progresso:
        cmd.insert(1, '--quiet')
    try:
        if mostrar_progresso:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            assert proc.stderr is not None
            for line in proc.stderr:
                m = re.search(r'\[download\]\s+([\d.]+)%', line)
                if m:
                    pct = float(m.group(1))
                    _imprimir_progresso_linha(
                        f"  {_barra(pct)} {int(pct):3d}%  {line.strip()[:50]}    ",
                    )
            code = proc.wait(timeout=7200)
            if code != 0:
                raise subprocess.CalledProcessError(code, cmd)
            size = os.path.getsize(destino) if os.path.isfile(destino) else 0
            _imprimir_progresso_linha(f"  {_barra(100)} 100%  {_fmt_bytes(size)}    ")
            _print_seguro('')
        else:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=7200)
        return
    except FileNotFoundError:
        loga(first_folder, "INFO", "yt-dlp não encontrado — usando youtube-dl")
    except subprocess.CalledProcessError as err:
        msg = (getattr(err, 'stderr', None) or str(err))[:400]
        loga(first_folder, "WARN", f"yt-dlp falhou ({link}): {msg}")
    except subprocess.TimeoutExpired:
        loga(first_folder, "WARN", f"yt-dlp excedeu tempo limite: {link}")

    ydl_opts = {
        'format': _ydl_format_por_qualidade(qualidade_video),
        'outtmpl': destino,
        'continuedl': True,
        'nooverwrites': False,
        'quiet': True,
        'no_warnings': True,
    }
    if hooks:
        ydl_opts['progress_hooks'] = hooks
    if dominio and 'vimeo' in link:
        youtube_dl.utils.std_headers['Referer'] = _referer_club(dominio)
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        ydl.download([link])
    if mostrar_progresso:
        size = os.path.getsize(destino) if os.path.isfile(destino) else 0
        _imprimir_progresso_linha(f"  {_barra(100)} 100%  {_fmt_bytes(size)}    ")
        _print_seguro('')
