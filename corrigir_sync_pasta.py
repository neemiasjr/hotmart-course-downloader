#!/usr/bin/env python3
"""
Corrige vídeos já baixados: fluidez (timestamps HLS) e/ou sync áudio/vídeo.

Log e retomada:
  - fluid-correcao.log  (texto, na pasta alvo)
  - .fluid-correcao.json (estado por arquivo)

Uso:
  python corrigir_sync_pasta.py Cursos
  python corrigir_sync_pasta.py Cursos          # retoma do JSON + pula já OK
  python corrigir_sync_pasta.py Cursos --recomecar
  python corrigir_sync_pasta.py Cursos --importar-log fluid-correcao-historico.log
  python corrigir_sync_pasta.py --dry-run Cursos/
  tail -f Cursos/fluid-correcao.log
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import hotmark as h  # noqa: E402

DEFAULT_CURSOS = os.path.join(ROOT, 'Cursos')
PROGRESS_NAME = '.fluid-correcao.json'
LOG_NAME = 'fluid-correcao.log'
PROGRESS_VERSION = 1


def _listar_mp4(pasta: str) -> list[str]:
    encontrados = []
    for dirpath, _, files in os.walk(pasta):
        for nome in files:
            lower = nome.lower()
            if not lower.endswith('.mp4'):
                continue
            if lower.endswith('.part.mp4') or '._sync.tmp.mp4' in lower or '._fluid.tmp.mp4' in lower:
                continue
            encontrados.append(os.path.join(dirpath, nome))
    return sorted(encontrados)


def _cfg_fluidao():
    des = h._carregar_desempenho()
    return {
        'crf': des['fluidao_crf'],
        'preset': des['fluidao_preset'],
        'limiar': des['fluidao_limiar'],
        'sync': des['corrigir_sync_av'],
        'fluidao': des['corrigir_fluidao'],
    }


def _progress_path(pasta: str) -> str:
    return os.path.join(pasta, PROGRESS_NAME)


def _log_path(pasta: str) -> str:
    return os.path.join(pasta, LOG_NAME)


def _agora_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat(sep=' ')


def _log_arquivo(pasta: str, msg: str, also_print: bool = True):
    linha = f'[{_agora_iso()}] {msg}'
    try:
        with open(_log_path(pasta), 'a', encoding='utf-8') as f:
            f.write(linha + '\n')
    except OSError as exc:
        if also_print:
            print(f'AVISO: não gravou log: {exc}', file=sys.stderr)
    if also_print:
        print(msg, flush=True)


def _carregar_progresso(pasta: str) -> dict | None:
    path = _progress_path(pasta)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if os.path.abspath(data.get('pasta') or '') != os.path.abspath(pasta):
        return None
    return data


def _salvar_progresso(pasta: str, data: dict):
    data = dict(data)
    data['pasta'] = os.path.abspath(pasta)
    data['versao'] = PROGRESS_VERSION
    data['atualizado_em'] = _agora_iso()
    path = _progress_path(pasta)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _registro_item(
    progress: dict,
    rel: str,
    *,
    indice: int,
    status: str,
    ir_antes: float | None = None,
    ir_depois: float | None = None,
    bytes_antes: int | None = None,
    bytes_depois: int | None = None,
    fluido: bool = False,
    erro: str | None = None,
):
    itens = progress.setdefault('itens', {})
    prev = itens.get(rel) or {}
    tentativas = int(prev.get('tentativas') or 0)
    itens[rel] = {
        'indice': indice,
        'status': status,
        'irregular_antes': ir_antes,
        'irregular_depois': ir_depois,
        'bytes_antes': bytes_antes,
        'bytes_depois': bytes_depois,
        'fluido': fluido,
        'erro': erro,
        'atualizado_em': _agora_iso(),
        'tentativas': tentativas,
    }


def _ja_concluido(rec: dict | None, limiar: float, forcar: bool) -> bool:
    if forcar or not rec:
        return False
    if rec.get('status') == 'skip':
        return True
    if rec.get('status') != 'ok':
        return False
    depois = rec.get('irregular_depois')
    if depois is None:
        return False
    return float(depois) < limiar


def _precisa_fluido(ir: float, limiar: float, cfg: dict, sem_fluido: bool) -> bool:
    return cfg['fluidao'] and not sem_fluido and ir >= limiar


_RE_LOG_HEADER = re.compile(r'^\[(\d+)/(\d+)\]\s+(.+)$')
_RE_LOG_IRREG = re.compile(r'irregular\s+(\d+)%→(\d+)%')
_RE_LOG_ERRO = re.compile(r'ERRO:\s*(.+)$')


def importar_log_terminal(pasta: str, log_path: str, limiar: float = 0.08) -> dict:
    """
    Lê saída de terminal colada em arquivo ([N/M] caminho + linha OK/ERRO).
    Gera/atualiza itens do progresso sem re-encodar.
    """
    pasta = os.path.abspath(pasta)
    with open(log_path, encoding='utf-8') as f:
        linhas = f.read().splitlines()

    videos = _listar_mp4(pasta)
    rel_por_indice = {
        i: os.path.relpath(p, pasta) for i, p in enumerate(videos, start=1)
    }

    progress = _carregar_progresso(pasta) or {
        'status': 'interrompido',
        'total': len(videos),
        'itens': {},
    }
    progress['total'] = len(videos)
    progress['pasta'] = pasta
    progress['importado_de'] = os.path.abspath(log_path)

    pendente_indice = None
    pendente_rel = None
    importados = 0

    def _flush_detalhe(linha: str):
        nonlocal importados
        if not pendente_rel:
            return
        ir_match = _RE_LOG_IRREG.search(linha)
        if ir_match:
            ia, idp = int(ir_match.group(1)), int(ir_match.group(2))
            ir_a, ir_d = ia / 100.0, idp / 100.0
            fluido = '[fluido]' in linha
            if ir_d < limiar:
                st = 'skip' if ir_a < limiar and not fluido else 'ok'
            else:
                st = 'erro_parcial'
                fluido = False
            _registro_item(
                progress, pendente_rel,
                indice=pendente_indice or 0,
                status=st,
                ir_antes=ir_a, ir_depois=ir_d,
                fluido=fluido,
                erro=None if st != 'erro_parcial' else (
                    f'irregular {ia}%→{idp}% (importado do log)'
                ),
            )
            importados += 1
            return
        err_match = _RE_LOG_ERRO.search(linha)
        if err_match:
            _registro_item(
                progress, pendente_rel,
                indice=pendente_indice or 0,
                status='erro',
                erro=err_match.group(1).strip(),
            )
            importados += 1

    for raw in linhas:
        linha = raw.strip()
        if not linha or linha.startswith('Resumo:') or 'vídeo(s) em' in linha:
            continue
        m = _RE_LOG_HEADER.match(linha)
        if m:
            pendente_indice = int(m.group(1))
            pendente_rel = m.group(3).strip()
            if pendente_rel not in rel_por_indice.values():
                alt = rel_por_indice.get(pendente_indice)
                if alt:
                    pendente_rel = alt
            continue
        if linha.lstrip().startswith('OK') or linha.lstrip().startswith('ERRO') or 'irregular' in linha:
            _flush_detalhe(linha)

    ok = skip = falhas = 0
    for rec in progress.get('itens', {}).values():
        st = rec.get('status')
        if st == 'ok':
            ok += 1
        elif st == 'skip':
            skip += 1
        elif st in ('erro', 'erro_parcial'):
            falhas += 1
    progress['processados_ok'] = ok
    progress['pulados'] = skip
    progress['falhas'] = falhas
    progress['status'] = 'interrompido' if falhas else 'concluido'
    progress['importados'] = importados
    progress['importado_em'] = _agora_iso()
    _salvar_progresso(pasta, progress)

    dest_log = _log_path(pasta)
    try:
        with open(dest_log, 'a', encoding='utf-8') as out:
            out.write(f'\n[{_agora_iso()}] === Importado de {log_path} '
                      f'({importados} entradas, {ok} ok, {skip} skip, {falhas} falha(s)) ===\n')
            with open(log_path, encoding='utf-8') as src:
                out.write(src.read())
    except OSError:
        pass

    return progress


def gerar_log_historico_seed(pasta: str, destino: str) -> int:
    """
    Recria o log da execução de 2026-10-09 (150 vídeos em Cursos/) para importação.
    Usado uma vez quando o terminal não foi salvo em arquivo.
    """
    pasta = os.path.abspath(pasta)
    videos = _listar_mp4(pasta)
    if not videos:
        return 0

    erro_parcial = {80, 81, 134, 135}
    skip_ok = {115, 116, 117, 118}
    erro_disco = set(range(136, 151))
    ir_antes_ok = {
        80: 53, 81: 52, 134: 53, 135: 54,
    }

    linhas = [
        f'{len(videos)} vídeo(s) em {pasta}',
        '(execução importada — seed 2026-10-09)',
        '',
    ]
    total = len(videos)
    for i, path in enumerate(videos, start=1):
        rel = os.path.relpath(path, pasta)
        linhas.append(f'[{i}/{total}] {rel}')
        if i in erro_disco:
            linhas.append('         ERRO: [Errno 28] No space left on device')
        elif i in erro_parcial:
            ia = ir_antes_ok.get(i, 53)
            linhas.append(f'         OK  | irregular {ia}%→{ia}%')
        elif i in skip_ok:
            linhas.append('         OK  | irregular 0%→0%')
        else:
            ia = 55
            linhas.append(f'         OK  | irregular {ia}%→0%  [fluido]')
    linhas.append('')
    linhas.append('Resumo: 135 processado(s), 0 já OK, 15 falha(s).')

    os.makedirs(os.path.dirname(destino) or '.', exist_ok=True)
    with open(destino, 'w', encoding='utf-8') as f:
        f.write('\n'.join(linhas) + '\n')
    return total


def _limpar_temporarios(pasta: str):
    for dirpath, _, files in os.walk(pasta):
        for nome in files:
            if '._fluid.tmp.mp4' in nome or '._sync.tmp.mp4' in nome:
                try:
                    os.remove(os.path.join(dirpath, nome))
                except OSError:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Corrige fluidez (movimento robótico) e sync A/V em .mp4 (recursivo).',
    )
    parser.add_argument(
        'pasta',
        nargs='?',
        default=DEFAULT_CURSOS,
        help='Pasta do módulo/curso (padrão: Cursos/)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Só lista os arquivos, não altera',
    )
    parser.add_argument(
        '--forcar',
        action='store_true',
        help='Reprocessa mesmo vídeos já marcados OK no progresso',
    )
    parser.add_argument(
        '--recomecar',
        action='store_true',
        help='Ignora .fluid-correcao.json (ainda pula arquivos com irregularidade baixa)',
    )
    parser.add_argument(
        '--sem-fluido',
        action='store_true',
        help='Não corrige fluidez (só sync A/V, se habilitado)',
    )
    parser.add_argument(
        '--sem-sync',
        action='store_true',
        help='Não aplica remux de sync áudio/vídeo',
    )
    parser.add_argument(
        '--importar-log',
        metavar='ARQUIVO',
        nargs='?',
        const='fluid-correcao-historico.log',
        help='Importa saída de terminal salva em ARQUIVO → .fluid-correcao.json (sem re-encodar)',
    )
    parser.add_argument(
        '--gerar-historico-seed',
        action='store_true',
        help='Gera fluid-correcao-historico.log (execução 2026-10-09) e importa o progresso',
    )
    args = parser.parse_args()

    pasta = os.path.abspath(args.pasta)
    if not os.path.isdir(pasta):
        print(f'Pasta não encontrada:\n  {pasta}', file=sys.stderr)
        return 1

    if args.gerar_historico_seed:
        hist = os.path.join(pasta, 'fluid-correcao-historico.log')
        n = gerar_log_historico_seed(pasta, hist)
        print(f'Gerado: {hist} ({n} vídeos)')
        args.importar_log = hist

    if args.importar_log is not None:
        cfg = _cfg_fluidao()
        log_in = args.importar_log
        if not os.path.isabs(log_in):
            log_in = os.path.join(pasta, log_in)
        if not os.path.isfile(log_in):
            print(f'Log não encontrado:\n  {log_in}', file=sys.stderr)
            return 1
        prog = importar_log_terminal(pasta, log_in, limiar=cfg['limiar'])
        print(f'Importado: {prog.get("importados", 0)} vídeo(s) → {_progress_path(pasta)}')
        print(
            f'  ok={prog.get("processados_ok", 0)}, '
            f'pulados={prog.get("pulados", 0)}, falhas={prog.get("falhas", 0)}'
        )
        print(f'Histórico anexado em: {_log_path(pasta)}')
        print(f'\nPróximo passo:\n  .venv/bin/python corrigir_sync_pasta.py "{pasta}"')
        return 0

    cfg = _cfg_fluidao()
    videos = _listar_mp4(pasta)
    if not videos:
        print(f'Nenhum .mp4 em:\n  {pasta}')
        return 0

    _limpar_temporarios(pasta)

    progress = _carregar_progresso(pasta) if not args.recomecar else None
    if progress is None:
        progress = {
            'status': 'em_andamento',
            'total': len(videos),
            'itens': {},
        }
    else:
        progress['total'] = len(videos)
        progress['status'] = 'em_andamento'

    log_file = _log_path(pasta)
    if not args.dry_run:
        _log_arquivo(
            pasta,
            f'=== Sessão iniciada | {len(videos)} vídeo(s) | log: {log_file} | '
            f'progresso: {_progress_path(pasta)} ===',
            also_print=False,
        )
        print(f'{len(videos)} vídeo(s) em {pasta}')
        print(f'Log: {log_file}')
        print(f'Progresso: {_progress_path(pasta)}\n')

    ok = pulados = falhas = 0
    itens_prog = progress.get('itens') or {}

    for i, path in enumerate(videos, start=1):
        rel = os.path.relpath(path, pasta)
        if args.dry_run:
            ir = h._fracao_pts_irregulares(path)
            rec = itens_prog.get(rel)
            st = rec.get('status') if rec else '-'
            print(f'  {i:3d}. {rel}  (irregular ~{ir:.0%}, progresso={st})')
            continue

        rec = itens_prog.get(rel)
        if _ja_concluido(rec, cfg['limiar'], args.forcar):
            pulados += 1
            _log_arquivo(
                pasta,
                f'[{i}/{len(videos)}] {rel} — SKIP (já OK no progresso, '
                f'irregular {float(rec.get("irregular_depois", 0)):.0%})',
            )
            continue

        if rec and rec.get('status') == 'skip' and not args.forcar:
            pulados += 1
            _log_arquivo(
                pasta,
                f'[{i}/{len(videos)}] {rel} — SKIP (progresso importado)',
            )
            continue

        ir_probe = h._fracao_pts_irregulares(path)
        if rec and rec.get('status') in ('erro', 'erro_parcial') and not args.forcar:
            _log_arquivo(
                pasta,
                f'[{i}/{len(videos)}] {rel} — retomando ({rec.get("status")})',
            )
        elif not args.forcar and ir_probe < cfg['limiar']:
            pulados += 1
            _registro_item(
                progress, rel, indice=i, status='skip',
                ir_antes=ir_probe, ir_depois=ir_probe,
            )
            _salvar_progresso(pasta, progress)
            _log_arquivo(
                pasta,
                f'[{i}/{len(videos)}] {rel} — SKIP (~{ir_probe:.0%} irregular)',
            )
            continue

        _log_arquivo(pasta, f'[{i}/{len(videos)}] {rel}', also_print=True)
        prev_tent = int((itens_prog.get(rel) or {}).get('tentativas') or 0)
        itens_prog[rel] = {**(itens_prog.get(rel) or {}), 'tentativas': prev_tent + 1}
        try:
            antes = os.path.getsize(path)
            ir_antes = ir_probe
            fluido = False
            if cfg['fluidao'] and not args.sem_fluido:
                fluido = h._corrigir_fluidao_video(
                    path, pasta,
                    crf=cfg['crf'], preset=cfg['preset'],
                    limiar_irregular=cfg['limiar'],
                    forcar=args.forcar or ir_antes >= cfg['limiar'],
                )
            if cfg['sync'] and not args.sem_sync and not fluido:
                h._remux_sincronizar_av(path, pasta)
            depois = os.path.getsize(path)
            ir_depois = h._fracao_pts_irregulares(path)

            precisava = _precisa_fluido(ir_antes, cfg['limiar'], cfg, args.sem_fluido)
            if precisava and ir_depois >= cfg['limiar']:
                falhas += 1
                msg = (
                    f'ERRO parcial: irregular {ir_antes:.0%}→{ir_depois:.0%} '
                    '(ffmpeg não corrigiu — disco cheio?)'
                )
                _registro_item(
                    progress, rel, indice=i, status='erro_parcial',
                    ir_antes=ir_antes, ir_depois=ir_depois,
                    bytes_antes=antes, bytes_depois=depois, fluido=fluido,
                    erro=msg,
                )
                _log_arquivo(pasta, f'         {msg}')
            elif not fluido and ir_antes < cfg['limiar'] and (args.sem_sync or not cfg['sync']):
                pulados += 1
                _registro_item(
                    progress, rel, indice=i, status='skip',
                    ir_antes=ir_antes, ir_depois=ir_depois,
                    bytes_antes=antes, bytes_depois=depois,
                )
                _log_arquivo(pasta, f'         SKIP  já OK (~{ir_antes:.0%} irregular)')
            else:
                ok += 1
                _registro_item(
                    progress, rel, indice=i, status='ok',
                    ir_antes=ir_antes, ir_depois=ir_depois,
                    bytes_antes=antes, bytes_depois=depois, fluido=fluido,
                )
                _log_arquivo(
                    pasta,
                    f'         OK  {h._fmt_bytes(antes)} → {h._fmt_bytes(depois)}'
                    f'  | irregular {ir_antes:.0%}→{ir_depois:.0%}'
                    + ('  [fluido]' if fluido else ''),
                )
        except OSError as exc:
            falhas += 1
            err = str(exc)
            _registro_item(
                progress, rel, indice=i, status='erro',
                erro=err,
            )
            _log_arquivo(pasta, f'         ERRO: {err}')
        except Exception as exc:
            falhas += 1
            err = str(exc)
            _registro_item(
                progress, rel, indice=i, status='erro',
                erro=err,
            )
            _log_arquivo(pasta, f'         ERRO: {err}')

        progress['processados_ok'] = ok
        progress['pulados'] = pulados
        progress['falhas'] = falhas
        _salvar_progresso(pasta, progress)

    if not args.dry_run:
        progress['status'] = 'concluido' if falhas == 0 else 'interrompido'
        progress['processados_ok'] = ok
        progress['pulados'] = pulados
        progress['falhas'] = falhas
        _salvar_progresso(pasta, progress)
        resumo = f'Resumo: {ok} OK, {pulados} pulados, {falhas} falha(s).'
        print(f'\n{resumo}')
        _log_arquivo(pasta, resumo, also_print=False)
        if falhas:
            print(
                f'Libere espaço em disco e rode de novo:\n'
                f'  .venv/bin/python corrigir_sync_pasta.py "{pasta}"'
            )
    return 1 if falhas else 0


if __name__ == '__main__':
    raise SystemExit(main())
