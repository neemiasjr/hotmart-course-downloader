"""Análise e pós-processamento de vídeos locais (ffprobe/ffmpeg)."""

import json
import os
import statistics
import subprocess

from .caminhos import _arquivo_pronto, _limpar_parcial
from .console import loga


def _duracao_mp4_local(path):
    """Duração do arquivo em segundos, ou None."""
    if not _arquivo_pronto(path):
        return None
    try:
        dur = subprocess.run(
            [
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', path,
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if dur.returncode != 0:
            return None
        return float((dur.stdout or '').strip())
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return None


def _mp4_valido_ffprobe(path):
    """True se o .mp4 abre no ffprobe e tem duração plausível (não truncado)."""
    if not _arquivo_pronto(path):
        return False
    try:
        probe = subprocess.run(
            [
                'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', path,
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if probe.returncode != 0 or 'video' not in (probe.stdout or '').lower():
            return False
        local = _duracao_mp4_local(path)
        return local is not None and local > 0.5
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return False


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


def _dimensoes_video_local(path):
    try:
        r = subprocess.run(
            [
                'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height',
                '-of', 'csv=p=0:s=x', path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None, None
        parts = r.stdout.strip().split('x')
        return int(parts[0]), int(parts[1])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None, None


def _parse_frame_rate(val):
    if not val or val in ('0/0', 'N/A'):
        return None
    if '/' in val:
        num, den = val.split('/', 1)
        try:
            den_f = float(den)
            if den_f:
                return round(float(num) / den_f, 3)
        except ValueError:
            return None
    try:
        return round(float(val), 3)
    except ValueError:
        return None


def _fps_video_local(path):
    try:
        r = subprocess.run(
            [
                'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=r_frame_rate,avg_frame_rate',
                '-of', 'csv=p=0', path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0:
            return 30.0
        parts = (r.stdout or '').strip().split(',')
        for raw in parts:
            fps = _parse_frame_rate(raw.strip())
            if fps and fps > 1:
                return fps
    except (OSError, subprocess.TimeoutExpired):
        pass
    return 30.0


def _fracao_pts_irregulares(path, amostra_seg=30):
    """
    Mede irregularidade de timestamps (HLS→MP4 costuma duplicar quadros).
    Retorna fração 0..1 de intervalos anômalos na amostra inicial.
    """
    try:
        r = subprocess.run(
            [
                'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-read_intervals', f'0%+{int(amostra_seg)}',
                '-show_frames', '-show_entries', 'frame=best_effort_timestamp_time',
                '-of', 'json', path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return 0.0
        frames = json.loads(r.stdout).get('frames') or []
        pts = [
            float(fr['best_effort_timestamp_time'])
            for fr in frames
            if fr.get('best_effort_timestamp_time') is not None
        ]
        if len(pts) < 12:
            return 0.0
        deltas = [pts[i + 1] - pts[i] for i in range(len(pts) - 1)]
        med = statistics.median(deltas)
        if med <= 0:
            return 1.0
        irreg = sum(
            1 for d in deltas
            if d < 0.001 or d > med * 1.5 or d < med * 0.4
        )
        return irreg / len(deltas)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        return 0.0


def _corrigir_fluidao_video(
    path, first_folder, crf=20, preset='faster', fps=None, forcar=False,
    limiar_irregular=0.08,
):
    """
    Reamostra o vídeo em FPS constante (elimina quadros duplicados / saltos do HLS).
    """
    if not os.path.isfile(path):
        return False
    irregular = _fracao_pts_irregulares(path)
    if not forcar and irregular < limiar_irregular:
        return False

    fps = fps or _fps_video_local(path)
    fps_txt = f'{fps:g}'
    tmp = path + '._fluid.tmp.mp4'
    _limpar_parcial(tmp)
    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
        '-i', path,
        '-map', '0:v:0', '-map', '0:a:0?',
        '-vf', f'fps={fps_txt}',
        '-c:v', 'libx264', '-preset', preset, '-crf', str(crf),
        '-c:a', 'copy',
        '-movflags', '+faststart',
        '-y', tmp,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not _arquivo_pronto(tmp, min_bytes=1024):
        _limpar_parcial(tmp)
        loga(
            first_folder, 'WARN',
            f'Correção de fluidez não aplicada: {(proc.stderr or "")[-200:]}',
        )
        return False
    os.replace(tmp, path)
    depois = _fracao_pts_irregulares(path)
    loga(
        first_folder, 'INFO',
        f'Fluidez corrigida (fps={fps_txt}, irregular {irregular:.0%}→{depois:.0%})',
    )
    return True


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
