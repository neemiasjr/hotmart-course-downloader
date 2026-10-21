"""Vídeos externos (YouTube/Vimeo) e arquivos do Google Drive."""

import os
import re

import requests
import youtube_dl
from bs4 import BeautifulSoup

from .api import _referer_club
from .console import loga


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


def _link_video_externo_iframe(src, dominio):
    """
    Converte src de iframe (Vimeo/YouTube) em URL para youtube-dl.
    Mantém query string do Vimeo (?h=...) necessária para vídeos privados.
    """
    src = _normalizar_url_iframe(src)
    if not src:
        return None
    if 'player.vimeo' in src or 'vimeo.com' in src:
        youtube_dl.utils.std_headers['Referer'] = _referer_club(dominio)
        if 'player.vimeo' in src:
            return src
        vimeo_id = src.split('vimeo.com/', 1)[-1]
        if '?' in vimeo_id:
            vimeo_id = vimeo_id.split('?', 1)[0]
        vimeo_id = vimeo_id.strip('/')
        return f"https://player.vimeo.com/video/{vimeo_id}"
    if 'youtube.com' in src or 'youtu.be' in src:
        return src
    return None
