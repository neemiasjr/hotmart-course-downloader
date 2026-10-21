"""Renomeia downloads feitos por versões anteriores para o padrão atual."""

import os
import re

from .caminhos import _pasta_materiais_topico
from .console import _print_seguro, loga
from .nomes import _prefixo_aula, _prefixo_aula_legado


def _sufixo_legado_para_atual(resto):
    """Converte o que vem depois do prefixo antigo para o padrão atual."""
    m = re.fullmatch(r'-v(\d+)\.mp4', resto, re.I)
    if m:
        return f' (vídeo {m.group(1)}).mp4'
    if resto.startswith('.'):
        return resto
    if resto.startswith(('-', '_')):
        return f' - {resto[1:]}'
    return None


def _migrar_nomes_legados_topico(folder_topico, aulas_topico, first_folder):
    """
    Renomeia arquivos baixados por versões anteriores (ex.: 8.yakissoba.mp4)
    para o padrão atual (8 - Yakissoba.mp4), evitando baixar tudo de novo.
    """
    pastas = [
        folder_topico,
        os.path.join(folder_topico, 'descricoes'),
        _pasta_materiais_topico(folder_topico),
    ]
    arquivos = {}
    for pasta in pastas:
        try:
            arquivos[pasta] = [
                n for n in os.listdir(pasta)
                if not n.startswith('._') and os.path.isfile(os.path.join(pasta, n))
            ]
        except OSError:
            continue

    pares = []
    for aula in aulas_topico:
        antigo = _prefixo_aula_legado(aula[0], aula[1])
        novo = _prefixo_aula(aula[0], aula[1])
        if antigo != novo:
            pares.append((antigo, novo))
    # prefixos mais longos primeiro: "1.aula-extra" não pode ser capturado por "1.aula"
    pares.sort(key=lambda p: len(p[0]), reverse=True)

    renomeados = 0
    usados = set()
    for antigo, novo in pares:
        for pasta, nomes in arquivos.items():
            for nome in nomes:
                if (pasta, nome) in usados or '.part.' in nome.lower():
                    continue
                if not nome.lower().startswith(antigo) or len(nome) == len(antigo):
                    continue
                sufixo = _sufixo_legado_para_atual(nome[len(antigo):])
                if sufixo is None:
                    continue
                usados.add((pasta, nome))
                destino = os.path.join(pasta, novo + sufixo)
                if os.path.exists(destino):
                    continue
                try:
                    os.rename(os.path.join(pasta, nome), destino)
                    renomeados += 1
                except OSError as e:
                    loga(first_folder, "WARN", f"Não renomeou {nome}: {e}")
    if renomeados:
        loga(
            first_folder, "INFO",
            f"{renomeados} arquivo(s) renomeado(s) para o padrão atual em {folder_topico}",
        )
    return renomeados


def _migrar_pasta_legada(destino, candidatos_legados, first_folder):
    """Renomeia a pasta antiga (slug) para o nome atual, se só a antiga existir."""
    if os.path.isdir(destino):
        return False
    pai = os.path.dirname(destino)
    for nome in candidatos_legados:
        origem = os.path.join(pai, nome)
        if nome and os.path.normpath(origem) != os.path.normpath(destino) and os.path.isdir(origem):
            try:
                os.rename(origem, destino)
            except OSError as e:
                loga(first_folder, "WARN", f"Não renomeou a pasta {origem}: {e}")
                return False
            loga(first_folder, "INFO", f"Pasta renomeada: {origem} -> {destino}")
            _print_seguro(f"  Pasta renomeada para o novo padrão: {os.path.basename(destino)}")
            return True
    return False
