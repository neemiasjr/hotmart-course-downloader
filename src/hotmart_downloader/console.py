"""Saída no terminal e log em arquivo."""

import datetime
import threading


_print_lock = threading.Lock()


def loga(curso, status, msg):
    with open(curso + "/log.txt", "a", encoding="utf-8") as logz:
        logz.write(f"[{datetime.datetime.today().replace(microsecond=0)}] {status}: {msg}\n")


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
