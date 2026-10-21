"""Vídeos hospedados na Hotmart (HLS assinado)."""

import json
import os
import re
import time
import urllib.parse

import m3u8
import requests

from .api import USER_AGENT
from .caminhos import _caminho_parcial, _finalizar_download, _limpar_parcial
from .console import _fmt_bytes, _fmt_tempo, _print_lock, _print_seguro, loga
from .ffmpeg import (
    FFMPEG_MAX_TENTATIVAS_TRAVAMENTO,
    FFMPEG_RW_TIMEOUT_US,
    FfmpegTravadoError,
    _rodar_ffmpeg_com_progresso,
    _rodar_ffmpeg_simples,
)
from .midia import (
    _corrigir_fluidao_video,
    _dimensoes_video_local,
    _duracao_mp4_local,
    _fracao_pts_irregulares,
    _obter_duracao_media,
    _remux_sincronizar_av,
)
from .verificacao import _duracao_local_suficiente, _video_arquivo_pronto


def _asset_height(asset):
    try:
        return int(asset.get('height') or 0)
    except (TypeError, ValueError):
        return 0


def _headers_hls_hotmart():
    return {
        'User-Agent': USER_AGENT,
        'Referer': 'https://cf-embed.play.hotmart.com/',
        'Accept': '*/*',
    }


def _variante_playlist_altura(playlist):
    res = playlist.stream_info.resolution
    if res and len(res) == 2:
        try:
            return int(res[1])
        except (TypeError, ValueError):
            pass
    return 0


def _resolver_url_hls_melhor_variante(hls_url, qualidade=0):
    """
    Master playlists da Hotmart listam variantes do menor para o maior;
    o ffmpeg com -map 0:v:0 costuma pegar a primeira (240p/360p).
    Resolve até a media playlist da variante desejada.
    """
    headers = _headers_hls_hotmart()
    url_atual = hls_url
    for _ in range(10):
        resp = requests.get(url_atual, headers=headers, timeout=45)
        if resp.status_code != 200:
            break
        playlist = m3u8.loads(resp.text, uri=url_atual)
        if not playlist.is_variant or not playlist.playlists:
            return url_atual

        candidatos = []
        for pl in playlist.playlists:
            h = _variante_playlist_altura(pl)
            bw = int(pl.stream_info.bandwidth or 0)
            candidatos.append((h, bw, pl.uri))

        if not candidatos:
            return url_atual

        if qualidade:
            dentro = [c for c in candidatos if 0 < c[0] <= qualidade]
            if dentro:
                candidatos = dentro

        _, _, uri = max(candidatos, key=lambda c: (c[0], c[1]))
        url_atual = urllib.parse.urljoin(url_atual, uri)
    return url_atual


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
    hls_url = _resolver_url_hls_melhor_variante(hls_url, qualidade)
    return hls_url, _asset_height(chosen)


def baixar_video_hotmart(
    media_src_url, video_hash, output_path, first_folder, qualidade=0,
    medir_duracao=False, mostrar_progresso=True, corrigir_sync_av=True,
    corrigir_fluidao=True, fluidao_crf=20, fluidao_preset='faster',
    fluidao_limiar=0.08,
    verificar_completo=False, duracao_esperada=None, fracao_duracao_minima=0.90,
):
    if _video_arquivo_pronto(
        output_path, verificar_completo, duracao_esperada, fracao_duracao_minima,
    ):
        _, vh_existente = _dimensoes_video_local(output_path)
        if qualidade and vh_existente and vh_existente < int(qualidade * 0.75):
            _print_seguro(
                f"  Arquivo em {vh_existente}p (preferência {qualidade}p) — baixando de novo..."
            )
            loga(
                first_folder, "INFO",
                f"Re-download por resolução baixa ({vh_existente}p): {output_path}",
            )
            _limpar_parcial(output_path)
        else:
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
    duracao_hls = None
    if verificar_completo or (medir_duracao and mostrar_progresso):
        with _print_lock:
            print("  Obtendo duração...", end='', flush=True)
        duracao_hls = _obter_duracao_media(hls_url, headers_str)
        with _print_lock:
            if duracao_hls:
                print(f" {_fmt_tempo(duracao_hls)}")
            else:
                print(" indisponível (mostrando tamanho/tempo)")
    duracao_ref = duracao_esperada or duracao_hls
    duracao_barra = duracao_ref if (medir_duracao and mostrar_progresso) else duracao_ref

    def _montar_ffmpegcmd(url):
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-nostdin',
            '-loglevel', 'error',
            '-headers', headers_str,
            '-reconnect', '1',
            '-reconnect_streamed', '1',
            '-reconnect_on_network_error', '1',
            '-reconnect_delay_max', '5',
            '-rw_timeout', str(FFMPEG_RW_TIMEOUT_US),
            '-probesize', '32M',
            '-analyzeduration', '32M',
            '-fflags', '+genpts+discardcorrupt',
        ]
        cmd.extend([
            '-i', url,
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
        ])
        return cmd

    loga(first_folder, "INFO", "Iniciando o FFMPEG (URL assinada)")
    returncode = 1
    stderr = ''
    travamentos = 0
    tentativa_incompleta = 0
    while True:
        ffmpegcmd = _montar_ffmpegcmd(hls_url)
        try:
            if mostrar_progresso:
                returncode, stderr = _rodar_ffmpeg_com_progresso(
                    ffmpegcmd, part_path, duracao_barra,
                )
            else:
                returncode, stderr = _rodar_ffmpeg_simples(ffmpegcmd, part_path)
        except KeyboardInterrupt:
            loga(first_folder, "WARN", "Download interrompido pelo usuário (ffmpeg)")
            raise
        except FfmpegTravadoError as err:
            travamentos += 1
            _limpar_parcial(output_path)
            if travamentos >= FFMPEG_MAX_TENTATIVAS_TRAVAMENTO:
                loga(first_folder, "ERROR", f"{err} — desistindo após {travamentos} tentativas")
                raise RuntimeError(
                    f"{err}. Desistindo após {travamentos} tentativas; "
                    "rode o script de novo para retomar."
                ) from err
            loga(
                first_folder, "WARN",
                f"{err} — reiniciando download "
                f"(tentativa {travamentos + 1}/{FFMPEG_MAX_TENTATIVAS_TRAVAMENTO})",
            )
            _print_seguro(
                f"  {err}; reiniciando "
                f"(tentativa {travamentos + 1}/{FFMPEG_MAX_TENTATIVAS_TRAVAMENTO})..."
            )
            time.sleep(3)
            try:
                hls_url, _ = obter_url_hls_assinada(
                    media_src_url, video_hash, qualidade=qualidade,
                )
            except Exception as url_err:
                loga(first_folder, "WARN", f"Não renovou URL HLS ({url_err}); reutilizando")
            continue
        if returncode != 0:
            _limpar_parcial(output_path)
            detalhe = (stderr or '').strip().splitlines()[-1:]
            detalhe = detalhe[0] if detalhe else f"código {returncode}"
            raise RuntimeError(f"ffmpeg falhou: {detalhe}")
        if verificar_completo and duracao_ref and duracao_ref >= 60:
            local = _duracao_mp4_local(part_path)
            if not _duracao_local_suficiente(
                part_path, duracao_ref, fracao_duracao_minima,
            ):
                msg = (
                    f"Vídeo incompleto ({_fmt_tempo(local or 0)} de "
                    f"{_fmt_tempo(duracao_ref)} esperados)"
                )
                if tentativa_incompleta == 0:
                    tentativa_incompleta += 1
                    loga(first_folder, "WARN", f"{msg} — nova tentativa de download")
                    _print_seguro(f"  {msg}; tentando de novo...")
                    _limpar_parcial(output_path)
                    continue
                _limpar_parcial(output_path)
                raise RuntimeError(f"{msg}. Rode o script de novo com token válido.")
        break

    fluido_aplicado = False
    if corrigir_fluidao:
        irregular = _fracao_pts_irregulares(part_path)
        if irregular >= fluidao_limiar:
            _print_seguro(
                f'  Suavizando movimento (timestamps HLS ~{irregular:.0%} irregulares)...',
            )
            fluido_aplicado = _corrigir_fluidao_video(
                part_path, first_folder,
                crf=fluidao_crf, preset=fluidao_preset,
                limiar_irregular=fluidao_limiar, forcar=True,
            )
    if corrigir_sync_av and not fluido_aplicado:
        _print_seguro('  Ajustando sincronia áudio/vídeo...')
        _remux_sincronizar_av(part_path, first_folder)
    try:
        _finalizar_download(part_path, output_path)
    except Exception:
        _limpar_parcial(output_path)
        raise
    size = os.path.getsize(output_path)
    vw, vh = _dimensoes_video_local(output_path)
    if vw and vh:
        _print_seguro(f"  Resolução real: {vw}x{vh}")
        loga(first_folder, "INFO", f"Resolução do arquivo: {vw}x{vh}")
        if qualidade and vh < int(qualidade * 0.75):
            msg = (
                f"Arquivo em {vh}p, abaixo da preferência {qualidade}p "
                "(fonte pode não ter HD ou variante indisponível)."
            )
            _print_seguro(f"  Aviso: {msg}")
            loga(first_folder, "WARN", msg)
    _print_seguro(f"  Concluído: {output_path} ({_fmt_bytes(size)})")
    loga(first_folder, "INFO", f"FFMPEG concluído, aula baixada ({size} bytes).")
