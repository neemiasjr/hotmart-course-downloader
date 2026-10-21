"""Anexos, PDFs do Google Drive e links de leitura complementar das aulas."""

import os
import time

import requests

from .api import CLUB_API, _get_page_json
from .caminhos import (
    _caminho_anexo_aula,
    _caminho_gdrive_aula,
    _caminho_links_aula,
    _pasta_aula_legada,
    _pasta_materiais_topico,
)
from .console import loga
from .externos import baixar_google_drive, extrair_google_drive_urls
from .verificacao import _anexo_ja_baixado

TENTATIVAS_ANEXO = 3


def _imprimir_resumo(titulo, baixados, pulados, falhos):
    print(f"\n  [RESUMO] {titulo}:")
    print(f"     Baixados: {baixados}")
    print(f"     Pulados: {pulados}")
    if falhos > 0:
        print(f"     Falhas: {falhos}")
    print()


def _conteudo_anexo(authMart, anexo_id):
    """Bytes do anexo pela API do Club (directDownloadUrl ou lambdaUrl)."""
    response = authMart.get(f'{CLUB_API}/attachment/{anexo_id}/download', timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Erro HTTP {response.status_code}: {response.text[:100]}")
    anexo_info = response.json()

    if 'directDownloadUrl' in anexo_info:
        print("      [DOWNLOAD] Baixando via directDownloadUrl...")
        anexo = requests.get(anexo_info['directDownloadUrl'], timeout=60)
        if anexo.status_code != 200:
            raise RuntimeError(f"Erro ao baixar: HTTP {anexo.status_code}")
    elif 'lambdaUrl' in anexo_info:
        print("      [DOWNLOAD] Baixando via lambdaUrl...")
        vrum = requests.session()
        vrum.headers.update(authMart.headers)
        vrum.headers['token'] = anexo_info.get('token', '')
        download_url = vrum.get(anexo_info['lambdaUrl'], timeout=30).text
        anexo = requests.get(download_url, timeout=60)
        if anexo.status_code != 200:
            raise RuntimeError(f"Erro ao baixar via lambda: HTTP {anexo.status_code}")
    else:
        raise RuntimeError("Nenhuma URL de download encontrada na resposta da API")

    if not anexo.content:
        raise RuntimeError("Conteúdo vazio recebido")
    return anexo.content


def _baixar_anexo(authMart, anexo_id, anexo_nome, destino, first_folder):
    """Baixa um anexo com até TENTATIVAS_ANEXO tentativas. True se deu certo."""
    for tentativa in range(1, TENTATIVAS_ANEXO + 1):
        try:
            if tentativa > 1:
                print(f"      [RETRY] Tentativa {tentativa}/{TENTATIVAS_ANEXO}...")
                time.sleep(2)
            loga(first_folder, "INFO", f"Baixando anexo {anexo_nome} (tentativa {tentativa})")

            conteudo = _conteudo_anexo(authMart, anexo_id)
            with open(destino, 'wb') as ann:
                ann.write(conteudo)
            if not os.path.exists(destino):
                raise RuntimeError("Arquivo não foi salvo")
            file_size = os.path.getsize(destino)
            if file_size == 0:
                raise RuntimeError("Arquivo salvo está vazio")

            print(f"      [OK] Baixado com sucesso ({file_size} bytes)")
            loga(first_folder, "INFO", f"Anexo baixado: {anexo_nome} ({file_size} bytes)")
            return True
        except Exception as e:
            erro_msg = str(e)
            loga(
                first_folder, "ERROR",
                f"Erro ao baixar anexo {anexo_nome} (tentativa {tentativa}): {erro_msg}",
            )
            if tentativa < TENTATIVAS_ANEXO:
                print(f"      [AVISO] Erro: {erro_msg}")
                continue
            print(f"      [ERRO] FALHA após {TENTATIVAS_ANEXO} tentativas: {erro_msg}")
            if os.path.exists(destino):
                try:
                    os.remove(destino)
                except OSError:
                    pass
    return False


def baixar_anexos_aula(authMart, aula, folder_path, first_folder):
    anexos = aula[4]['anexos']  # [id, nome]
    if not anexos:
        return
    page_order, lesson_name = aula[0], aula[1]
    print(f"\n{len(anexos)} anexo(s) encontrado(s) para a aula: {lesson_name}")
    pasta_materiais = _pasta_materiais_topico(folder_path)
    os.makedirs(pasta_materiais, exist_ok=True)
    loga(first_folder, "INFO", f"Materiais do tópico: {pasta_materiais}")

    baixados = pulados = falhos = 0
    for idx, (anexo_id, anexo_nome) in enumerate(anexos, 1):
        destino = _caminho_anexo_aula(folder_path, page_order, lesson_name, anexo_nome)
        legado = os.path.join(
            _pasta_aula_legada(folder_path, page_order, lesson_name), 'Materiais', anexo_nome,
        )
        print(f"  [{idx}/{len(anexos)}] {anexo_nome}")

        if _anexo_ja_baixado(destino):
            file_size = os.path.getsize(destino)
            print(f"      [OK] Já existe ({file_size} bytes) - pulando")
            loga(first_folder, "INFO", f"Anexo já existente: {anexo_nome} ({file_size} bytes)")
            pulados += 1
            continue
        if _anexo_ja_baixado(legado):
            file_size = os.path.getsize(legado)
            print(f"      [OK] Já existe no layout antigo ({file_size} bytes) - pulando")
            pulados += 1
            continue
        if os.path.isfile(destino):
            print("      [AVISO] Arquivo existe mas está vazio - rebaixando")
            loga(first_folder, "WARN", f"Anexo vazio detectado, rebaixando: {anexo_nome}")
            os.remove(destino)

        if _baixar_anexo(authMart, anexo_id, anexo_nome, destino, first_folder):
            baixados += 1
            time.sleep(0.5)
        else:
            falhos += 1

    _imprimir_resumo("Anexos", baixados, pulados, falhos)
    loga(
        first_folder, "INFO",
        f"Anexos processados - Baixados: {baixados}, Pulados: {pulados}, Falhas: {falhos}",
    )


def baixar_gdrive_aula(authMart, aula, folder_path, first_folder):
    """PDFs do Google Drive embutidos (iframes) no conteúdo da aula."""
    page_order, lesson_name = aula[0], aula[1]
    try:
        content_html = _get_page_json(authMart, aula[2]).get('content', '')
        arquivos = extrair_google_drive_urls(content_html) if content_html else []
        if not arquivos:
            return
        print(f"\n{len(arquivos)} arquivo(s) do Google Drive encontrado(s) no conteúdo")
        os.makedirs(_pasta_materiais_topico(folder_path), exist_ok=True)

        baixados = pulados = falhos = 0
        for idx, (file_id, _preview_url, download_url) in enumerate(arquivos, 1):
            output_path = _caminho_gdrive_aula(folder_path, page_order, lesson_name, file_id)
            file_name = os.path.basename(output_path)
            print(f"  [{idx}/{len(arquivos)}] {file_name}")

            if _anexo_ja_baixado(output_path):
                file_size = os.path.getsize(output_path)
                print(f"      [OK] Já existe ({file_size} bytes) - pulando")
                loga(first_folder, "INFO", f"Google Drive file já existente: {file_name}")
                pulados += 1
                continue
            if os.path.isfile(output_path):
                print("      [AVISO] Arquivo existe mas está vazio - rebaixando")
                os.remove(output_path)

            print("      [DOWNLOAD] Baixando do Google Drive...")
            if baixar_google_drive(file_id, download_url, output_path, first_folder):
                print("      [OK] Baixado com sucesso")
                baixados += 1
            else:
                print("      [ERRO] Falha no download")
                falhos += 1
            time.sleep(1)

        _imprimir_resumo("Arquivos do Google Drive", baixados, pulados, falhos)
        loga(
            first_folder, "INFO",
            f"Google Drive files - Baixados: {baixados}, Pulados: {pulados}, Falhas: {falhos}",
        )
    except Exception as e:
        loga(first_folder, "ERROR", f"Erro ao processar conteúdo Google Drive: {str(e)}")


def salvar_links_aula(aula, folder_path, first_folder):
    links = aula[5]['links']  # [nome, url]
    if not links:
        return
    page_order, lesson_name = aula[0], aula[1]
    os.makedirs(_pasta_materiais_topico(folder_path), exist_ok=True)
    links_path = _caminho_links_aula(folder_path, page_order, lesson_name)
    print(f"Salvando links encontrados para a aula\n\t {links_path}")
    loga(first_folder, "INFO", f"Links detectados para a aula {page_order}.{lesson_name}")
    with open(links_path, "a", encoding="utf-8") as linkz:
        for nome, url in links:
            linkz.write(f"{nome}: {url}\n")
    loga(first_folder, "INFO", "Links salvos")
