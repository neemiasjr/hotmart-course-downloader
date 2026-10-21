"""Execução do ffmpeg com barra de progresso e detecção de travamento."""

import os
import queue
import subprocess
import threading
import time

from .console import _barra, _fmt_bytes, _fmt_tempo, _imprimir_progresso_linha


FFMPEG_TIMEOUT_INATIVO = 180


FFMPEG_RW_TIMEOUT_US = 30_000_000


FFMPEG_MAX_TENTATIVAS_TRAVAMENTO = 3


class FfmpegTravadoError(RuntimeError):
    """ffmpeg ficou sem progresso (tempo e arquivo parados) por tempo demais."""


def _assinatura_arquivo(path):
    try:
        st = os.stat(path)
        return st.st_size, st.st_mtime_ns
    except OSError:
        return 0, 0


def _encerrar_processo(proc):
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def _iniciar_ffmpeg(cmd, capturar_stdout=True):
    """Popen com stdin fechado e stderr drenado em thread (evita deadlock de pipe)."""
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capturar_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stderr_holder = []

    def _drenar_stderr():
        try:
            if proc.stderr:
                stderr_holder.append(proc.stderr.read())
        except (OSError, ValueError):
            pass

    stderr_thread = threading.Thread(target=_drenar_stderr, daemon=True)
    stderr_thread.start()
    return proc, stderr_holder, stderr_thread


def _rodar_ffmpeg_com_progresso(
    ffmpegcmd, part_path, duracao=None, timeout_inativo=FFMPEG_TIMEOUT_INATIVO,
):
    """
    Executa ffmpeg mostrando progresso ao vivo.
    Usa -progress pipe:1 (out_time_ms) + tamanho do arquivo parcial.
    Levanta FfmpegTravadoError se nada avançar por `timeout_inativo` segundos.
    """
    cmd = list(ffmpegcmd)
    cmd[1:1] = ['-progress', 'pipe:1', '-nostats']

    proc, stderr_holder, stderr_thread = _iniciar_ffmpeg(cmd)
    linhas = queue.Queue()

    def _ler_stdout():
        try:
            for raw_line in proc.stdout:
                linhas.put(raw_line)
        except (OSError, ValueError):
            pass
        finally:
            linhas.put(None)

    threading.Thread(target=_ler_stdout, daemon=True).start()

    tempo_atual = 0.0
    ultimo_tempo = -1.0
    ultima_assinatura = _assinatura_arquivo(part_path)
    ultima_atividade = time.monotonic()
    try:
        while True:
            try:
                line = linhas.get(timeout=1)
            except queue.Empty:
                line = ''
            if line is None:
                break

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

            assinatura = _assinatura_arquivo(part_path)
            if tempo_atual != ultimo_tempo or assinatura != ultima_assinatura:
                ultimo_tempo = tempo_atual
                ultima_assinatura = assinatura
                ultima_atividade = time.monotonic()
            elif time.monotonic() - ultima_atividade > timeout_inativo:
                _encerrar_processo(proc)
                print()
                raise FfmpegTravadoError(
                    f"ffmpeg sem progresso há {timeout_inativo}s "
                    f"(parado em {_fmt_tempo(tempo_atual)})"
                )
        returncode = proc.wait()
    except BaseException:
        _encerrar_processo(proc)
        print()
        raise

    stderr_thread.join(timeout=30)
    stderr = stderr_holder[0] if stderr_holder else ''

    if returncode == 0:
        size = os.path.getsize(part_path) if os.path.isfile(part_path) else 0
        tempo_label = _fmt_tempo(duracao or tempo_atual)
        _imprimir_progresso_linha(
            f"  {_barra(100)} 100%  {tempo_label}  {_fmt_bytes(size)}    "
        )
    print()
    return returncode, stderr


def _rodar_ffmpeg_simples(ffmpegcmd, part_path, timeout_inativo=FFMPEG_TIMEOUT_INATIVO):
    """ffmpeg sem barra ao vivo (usado em download paralelo), com watchdog de inatividade."""
    proc, stderr_holder, stderr_thread = _iniciar_ffmpeg(ffmpegcmd, capturar_stdout=False)
    ultima_assinatura = _assinatura_arquivo(part_path)
    ultima_atividade = time.monotonic()
    try:
        while True:
            try:
                returncode = proc.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                pass
            assinatura = _assinatura_arquivo(part_path)
            if assinatura != ultima_assinatura:
                ultima_assinatura = assinatura
                ultima_atividade = time.monotonic()
            elif time.monotonic() - ultima_atividade > timeout_inativo:
                _encerrar_processo(proc)
                raise FfmpegTravadoError(
                    f"ffmpeg sem progresso há {timeout_inativo}s"
                )
    except BaseException:
        _encerrar_processo(proc)
        raise

    stderr_thread.join(timeout=30)
    stderr = (stderr_holder[0] if stderr_holder else '').strip()
    return returncode, stderr
