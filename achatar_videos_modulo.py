#!/usr/bin/env python3
"""
Move vídeos das subpastas para a raiz do módulo, renomeando pelo nome da pasta da aula.

Ex.: 2.musicas-do-eli-soares-abertura/aula-1.mp4
  -> 2.musicas-do-eli-soares-abertura.mp4
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(
    ROOT,
    'Cursos',
    'curso-tecladista-pop',
    '5_modulo-musicas-eli-soares',
)


def _nome_destino(pasta_aula: str, nome_arquivo: str, indice: int, total: int) -> str:
    base = pasta_aula.strip()
    if total > 1 or not re.match(r'^aula-\d+\.mp4$', nome_arquivo, re.I):
        stem, _ = os.path.splitext(nome_arquivo)
        if re.match(r'^aula-(\d+)$', stem, re.I):
            n = stem.split('-', 1)[1]
            return f'{base}-v{n}.mp4'
        return f'{base}-{stem}.mp4'
    return f'{base}.mp4'


def achatar(modulo: str, dry_run: bool = False) -> tuple[int, int]:
    modulo = os.path.abspath(modulo)
    movidos = erros = 0

    subpastas = sorted(
        (e for e in os.scandir(modulo) if e.is_dir() and not e.name.startswith('.')),
        key=lambda e: e.name,
    )

    for sub in subpastas:
        mp4s = []
        for dirpath, _, files in os.walk(sub.path):
            for f in files:
                if f.lower().endswith('.mp4') and not f.lower().endswith('.part.mp4'):
                    mp4s.append(os.path.join(dirpath, f))
        mp4s.sort()
        if not mp4s:
            continue

        for i, src in enumerate(mp4s, start=1):
            nome = _nome_destino(sub.name, os.path.basename(src), i, len(mp4s))
            dest = os.path.join(modulo, nome)
            if os.path.abspath(src) == os.path.abspath(dest):
                continue
            if os.path.exists(dest):
                print(f'  SKIP (já existe): {nome}')
                erros += 1
                continue
            print(f'  {os.path.relpath(src, modulo)}  ->  {nome}')
            if not dry_run:
                os.makedirs(modulo, exist_ok=True)
                shutil.move(src, dest)
            movidos += 1

        if not dry_run:
            try:
                shutil.rmtree(sub.path)
                print(f'  removida pasta: {sub.name}/')
            except OSError as exc:
                print(f'  AVISO: não removeu {sub.name}/: {exc}')

    return movidos, erros


def main() -> int:
    p = argparse.ArgumentParser(description='Achata vídeos do módulo na pasta raiz.')
    p.add_argument('modulo', nargs='?', default=DEFAULT)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()

    if not os.path.isdir(args.modulo):
        print(f'Pasta não encontrada: {args.modulo}', file=sys.stderr)
        return 1

    print(f'Módulo: {os.path.abspath(args.modulo)}')
    if args.dry_run:
        print('(dry-run — nada será alterado)\n')
    movidos, erros = achatar(args.modulo, dry_run=args.dry_run)
    print(f'\n{movidos} movido(s), {erros} pulo(s)/erro(s).')
    return 1 if erros and not args.dry_run else 0


if __name__ == '__main__':
    raise SystemExit(main())
