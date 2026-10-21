"""Fluxo principal: escolher o curso, definir o escopo e baixar as aulas."""

import glob
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .api import (
    _get_navigation_json,
    _get_page_json,
    _limpar_cache_paginas,
    _nomes_legados_pasta_curso,
    _obter_nome_curso,
)
from .caminhos import (
    _arquivo_pronto,
    _caminho_descricao_aula,
    _caminho_video_no_topico,
    _limpar_parcial,
)
from .config import _carregar_desempenho, _cursos_subdominios, _product_id_por_subdominio
from .console import _barra, _fmt_tempo, _print_seguro, loga
from .estrutura import _carregar_estrutura_aulas, _contar_aulas
from .externos import _baixar_video_externo, _listar_links_video_externo, _url_parece_video_externo
from .hls import baixar_video_hotmart
from .materiais import baixar_anexos_aula, baixar_gdrive_aula, salvar_links_aula
from .midia import _dimensoes_video_local, _duracao_mp4_local
from .migracao import _migrar_nomes_legados_topico, _migrar_pasta_legada
from .nomes import (
    _nome_arquivo_corresponde_aula,
    _nome_fiel,
    _nome_pasta_topico,
    _nome_pasta_topico_legado,
)
from .progresso import _carregar_progresso, _salvar_progresso
from .selecao import (
    _aula_apenas_videos,
    _escopo_de_progresso,
    _filtrar_plano_por_aulas_no_topico,
    _plano_aulas,
    _selecionar_escopo_aulas,
    _selecionar_modulos,
    _selecionar_qualidade,
    _serializar_videos_por_aula,
    _topicos_raw_de_config,
    _video_incluido_no_escopo,
)
from .verificacao import (
    _aula_ja_completa_na_pasta,
    _duracao_esperada_registro_video,
    _video_ja_baixado,
)

CHECK_TOKEN_URL = 'https://api-sec-vlc.hotmart.com/security/oauth/check_token'


class _GerenciadorDownloadsVideo:
    """Limita quantos ffmpeg rodam ao mesmo tempo."""

    def __init__(self, max_workers):
        self.max_workers = max(1, int(max_workers))
        self._executor = (
            ThreadPoolExecutor(max_workers=self.max_workers)
            if self.max_workers > 1 else None
        )
        self._futures = []

    def run(self, fn, *args, **kwargs):
        if self._executor is None:
            fn(*args, **kwargs)
            return
        self._futures.append(self._executor.submit(fn, *args, **kwargs))

    def aguardar(self):
        if not self._executor:
            return
        erros = []
        for fut in as_completed(self._futures):
            try:
                fut.result()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                erros.append(e)
        self._futures.clear()
        self._executor.shutdown(wait=True)
        self._executor = None
        if erros:
            raise erros[0]


@dataclass
class _Escopo:
    qualidade_video: int
    modulos_escolhidos: list
    aulas_selecionadas: set
    videos_por_aula: dict
    plano_filtrado: list


@dataclass
class _Download:
    """Estado compartilhado durante o download de um curso."""
    authMart: object
    nmcurso: str
    dominio: str
    first_folder: str
    desempenho: dict
    escopo: _Escopo
    hash_para_idx: dict
    gerenciador: _GerenciadorDownloadsVideo
    opts_video: dict
    videos_baixados: int = 0
    videos_pulados: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def paralelo(self):
        return self.desempenho['download_paralelo'] > 1

    @property
    def qualidade_video(self):
        return self.escopo.qualidade_video

    @property
    def videos_por_aula(self):
        return self.escopo.videos_por_aula

    def contar_baixado(self):
        with self._lock:
            self.videos_baixados += 1

    def salvar_progresso(self, status, **extra):
        modulos = self.escopo.modulos_escolhidos
        dados = {
            'status': status,
            'curso': self.nmcurso,
            'qualidade': self.qualidade_video,
            'module_orders': [m.get('moduleOrder') for m in modulos],
            'module_names': [re.sub(r'[<>:"/\\|?*]', '', m.get('name', '')).strip() for m in modulos],
            **extra,
            'aulas_indices': sorted(self.escopo.aulas_selecionadas),
            'videos_por_aula': _serializar_videos_por_aula(self.videos_por_aula),
        }
        _salvar_progresso(self.first_folder, dados)


# ---------------------------------------------------------------- cursos


def _produto(subdomain, product_id=None):
    resource = {'subdomain': subdomain, 'status': 'ACTIVE'}
    if product_id:
        resource['product_id'] = product_id
    return {'resource': resource, 'roles': ['STUDENT']}


def _produtos_check_token(authMart, params):
    """check_token rejeita tokens OIDC do Club; tenta mesmo assim."""
    try:
        resposta = authMart.get(CHECK_TOKEN_URL, params=params, timeout=30).json()
        with open("api_response_debug.json", "w", encoding="utf-8") as f:
            json.dump(resposta, f, indent=2, ensure_ascii=False)
        if resposta.get('error'):
            loga(
                ".", "WARN",
                f"check_token indisponível para este token "
                f"({resposta.get('error')}: {resposta.get('error_description')}). "
                f"Usando config_cursos.py.",
            )
            print("\nAVISO: check_token não lista cursos com token do Club (esperado).")
            print("Usando subdomínios de config_cursos.py.")
            return []
        loga(".", "DEBUG", "Resposta do check_token salva em api_response_debug.json")
        return resposta.get('resources', [])
    except Exception as e:
        loga(".", "WARN", f"Falha ao chamar check_token: {e}")
        print("\nAVISO: não foi possível listar cursos via check_token.")
        return []


def _produtos_de_config():
    subdominios = _cursos_subdominios()
    if not subdominios:
        print("\nAVISO: CURSOS_SUBDOMINIOS vazio ou config_cursos.py não encontrado.")
        return []
    print(f"\nEncontrados {len(subdominios)} curso(s) no arquivo config_cursos.py")
    loga(".", "INFO", f"Carregados {len(subdominios)} cursos do arquivo de configuração")
    return [_produto(s, _product_id_por_subdominio(s)) for s in subdominios]


def _produtos_digitados():
    print("\nPara encontrar o subdomínio do seu curso:")
    print("1. Acesse https://sun.hotmart.com/minhas-compras")
    print("2. Clique em 'Acessar' no curso desejado")
    print("3. Na URL você verá: https://hotmart.com/pt-br/club/SUBDOMAIN/...")
    print("4. O 'SUBDOMAIN' é o que você precisa informar")
    print("\nDica: Edite o arquivo 'config_cursos.py' para salvar os subdomínios permanentemente\n")

    subdominios = []
    while True:
        subdomain = input(
            "Digite o subdomínio do curso (ou pressione Enter para finalizar): "
        ).strip()
        if not subdomain:
            break
        subdominios.append(subdomain)
        print(f"Subdomínio '{subdomain}' adicionado\n")
    if not subdominios:
        print("AVISO: Nenhum curso adicionado. Finalizando...")
        sys.exit(0)
    loga(".", "INFO", f"Adicionados {len(subdominios)} cursos manualmente")
    return [_produto(s) for s in subdominios]


def _listar_produtos(authMart, params):
    produtos = _produtos_check_token(authMart, params)
    if not produtos:
        loga(".", "WARN", "Nenhum produto encontrado no check_token")
        print("\nAVISO: A API não retornou cursos automaticamente.")
        produtos = _produtos_de_config() or _produtos_digitados()
    loga(".", "INFO", "Listando produtos da conta.")
    loga(".", "DEBUG", f"Total de produtos encontrados: {len(produtos)}")
    return produtos


def _cursos_validos(authMart, produtos):
    """Produtos ativos em que a conta é aluna, já com o nome do curso."""
    cursos = []
    for idx, produto in enumerate(produtos):
        try:
            loga(
                ".", "DEBUG",
                f"Produto {idx + 1}: status={produto.get('resource', {}).get('status')}, "
                f"roles={produto.get('roles')}",
            )
            if produto['resource']['status'] != "ACTIVE" or "STUDENT" not in produto['roles']:
                loga(".", "DEBUG", f"Produto {idx + 1} não atende aos critérios (ACTIVE + STUDENT)")
                continue
            dominio = produto['resource']['subdomain']
            loga(".", "DEBUG", f"Produto válido encontrado. Domínio: {dominio}")
            produto["nome"] = _obter_nome_curso(
                authMart, dominio, produto['resource'].get('product_id'),
            )
            loga(".", "DEBUG", f"Nome do curso obtido: {produto['nome']}")
            cursos.append(produto)
        except KeyError as e:
            loga(".", "WARN", f"Produto presumido como inválido. Erro: {e}")
            loga(".", "WARN", f"{produto}")
        except Exception as e:
            loga(".", "ERROR", f"Erro ao processar produto: {e}")
            loga(".", "ERROR", f"{produto}")
    return cursos


def _escolher_curso(cursos):
    print(f"\n=== Cursos disponíveis ({len(cursos)} encontrado(s)) ===")
    for i, curso in enumerate(cursos, start=1):
        print(f"{i}. {curso['nome']}")
    opcao = int(input('Qual curso deseja baixar?\n')) - 1
    return cursos[opcao]


def _abrir_pasta_curso(authMart, curso):
    """Nome, navegação e pasta do curso (renomeia a pasta de versões antigas)."""
    nmcurso = _nome_fiel(curso['nome']) or 'Curso'
    loga(".", "INFO", f"Iniciando download do curso {nmcurso}")
    loga(".", "INFO", f"{curso}")
    dominio = curso['resource']['subdomain']
    product_id = curso['resource'].get('product_id')
    authMart.hotmart_subdomain = dominio
    authMart.hotmart_product_id = product_id or _product_id_por_subdominio(dominio)
    navegacao = _get_navigation_json(authMart, dominio, authMart.hotmart_product_id)

    first_folder = os.path.join('Cursos', nmcurso)
    _migrar_pasta_legada(
        first_folder, _nomes_legados_pasta_curso(dominio, curso['nome'], navegacao), '.',
    )
    os.makedirs(first_folder, exist_ok=True)
    return nmcurso, dominio, first_folder, navegacao


# ---------------------------------------------------------------- escopo


def _perguntar_retomada(progresso, nmcurso):
    if not progresso or progresso.get('status') != 'em_andamento':
        return False
    q = progresso.get('qualidade')
    qlabel = f"{q}p" if q else "máxima"
    feitas = progresso.get('aulas_feitas')
    total = progresso.get('aulas_total')
    progresso_aulas = f"\n  Aulas: {feitas}/{total}" if feitas is not None and total else ""
    print(
        f"\n=== Download incompleto encontrado ===\n"
        f"  Curso: {nmcurso}\n"
        f"  Qualidade: {qlabel}\n"
        f"  Tópicos salvos: {len(progresso.get('module_orders') or [])}"
        f"{progresso_aulas}\n"
        f"  Arquivos já baixados serão pulados."
    )
    resposta = input("Continuar de onde parou? [S/n]\n> ").strip().lower()
    return resposta in ('', 's', 'sim', 'y', 'yes')


def _definir_escopo(authMart, navegacao, progresso, retomar, first_folder):
    """Qualidade, tópicos e aulas a baixar (do progresso salvo ou perguntando)."""
    aulas_por_topico = {}
    todos_modulos = navegacao.get('modules') or []
    modulos_escolhidos = []
    if retomar:
        qualidade_video = int(progresso.get('qualidade') or 0)
        orders = set(progresso.get('module_orders') or [])
        todos = sorted(todos_modulos, key=lambda m: m.get('moduleOrder', 0))
        modulos_escolhidos = [m for m in todos if m.get('moduleOrder') in orders]
        if modulos_escolhidos:
            qlabel = f"{qualidade_video}p" if qualidade_video else "qualidade máxima"
            print(f"Retomando {len(modulos_escolhidos)} tópico(s) — {qlabel}.")
            loga(first_folder, "INFO", f"Retomando download (qualidade={qualidade_video})")
        else:
            print("Progresso inválido (tópicos não encontrados). Seleção manual.")
            retomar = False
            qualidade_video = _selecionar_qualidade()
            modulos_escolhidos, aulas_por_topico = _selecionar_modulos(todos_modulos)
    else:
        qualidade_video = _selecionar_qualidade()
        modulos_escolhidos, aulas_por_topico = _selecionar_modulos(
            todos_modulos, raw=_topicos_raw_de_config(),
        )

    plano = _plano_aulas(modulos_escolhidos, todos_modulos=todos_modulos)
    if aulas_por_topico:
        plano = _filtrar_plano_por_aulas_no_topico(plano, aulas_por_topico)
    if retomar:
        aulas_selecionadas, videos_por_aula = _escopo_de_progresso(progresso, plano, authMart)
    else:
        aulas_selecionadas, videos_por_aula = _selecionar_escopo_aulas(
            plano, authMart, aulas_ja_filtradas=bool(aulas_por_topico),
        )
    return _Escopo(
        qualidade_video=qualidade_video,
        modulos_escolhidos=modulos_escolhidos,
        aulas_selecionadas=aulas_selecionadas,
        videos_por_aula=videos_por_aula,
        plano_filtrado=[p for p in plano if p['idx'] in aulas_selecionadas],
    )


def _mostrar_dicas_desempenho(desempenho):
    if desempenho['download_paralelo'] > 1:
        print(
            f"\nDesempenho: até {desempenho['download_paralelo']} vídeos Hotmart em paralelo "
            f"(ajuste DOWNLOAD_PARALELO em config_cursos.py)."
        )
    if not desempenho['medir_duracao']:
        print(
            "Dica: ffprobe desligado por padrão (mais rápido). "
            "MEDIR_DURACAO_VIDEO = True para barra de % mais precisa.\n"
        )


def _opcoes_video(desempenho):
    return {
        'medir_duracao': desempenho['medir_duracao'],
        'mostrar_progresso': desempenho['download_paralelo'] <= 1,
        'corrigir_sync_av': desempenho['corrigir_sync_av'],
        'corrigir_fluidao': desempenho['corrigir_fluidao'],
        'fluidao_crf': desempenho['fluidao_crf'],
        'fluidao_preset': desempenho['fluidao_preset'],
        'fluidao_limiar': desempenho['fluidao_limiar'],
        'verificar_completo': desempenho['verificar_video_completo'],
        'fracao_duracao_minima': desempenho['fracao_duracao_minima'],
    }


def _montar_estrutura(authMart, plano_filtrado, api_paralelo):
    """{moduleOrder: {nome do módulo: [registro da aula, ...]}} na ordem do plano."""
    print(f"Carregando metadados de {len(plano_filtrado)} aula(s)...")
    estrutura = {}
    pares = _carregar_estrutura_aulas(authMart, plano_filtrado, api_paralelo)
    for x, (item, registro) in enumerate(pares, start=1):
        modulo = item['module']
        mod_name = (modulo.get('name') or '').strip()
        estrutura.setdefault(modulo['moduleOrder'], {}).setdefault(mod_name, []).append(registro)
        print(f"Aulas contabilizadas: {x}/{len(plano_filtrado)}")
    return estrutura


# ---------------------------------------------------------------- aulas


def _preparar_pasta_topico(ctx, module_order, nome_modulo, aulas):
    folder_path = os.path.join(ctx.first_folder, _nome_pasta_topico(module_order, nome_modulo))
    _migrar_pasta_legada(
        folder_path, [_nome_pasta_topico_legado(module_order, nome_modulo)], ctx.first_folder,
    )
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        loga(ctx.first_folder, "INFO", f"Criada a pasta do módulo {module_order}.{nome_modulo}")
    _migrar_nomes_legados_topico(folder_path, aulas, ctx.first_folder)
    return folder_path


def _salvar_descricao(ctx, aula, folder_path):
    page_order, lesson_name = aula[0], aula[1]
    descricao_path = _caminho_descricao_aula(folder_path, page_order, lesson_name)
    if _arquivo_pronto(descricao_path, min_bytes=32):
        print("  [OK] descrição já presente, pulando")
        loga(ctx.first_folder, "INFO", f"Descrição já existente: {descricao_path}")
        return
    try:
        desct = _get_page_json(ctx.authMart, aula[2])['content']
        os.makedirs(os.path.dirname(descricao_path), exist_ok=True)
        with open(descricao_path, 'w', encoding='utf-8') as dd:
            dd.write(str(desct))
        loga(
            ctx.first_folder, "INFO",
            f"Descrição salva com sucesso, aula {page_order}.{lesson_name}",
        )
    except KeyError:
        print("Aula sem descrição/não textual")
    except Exception:
        print("Erro ao salvar descrição, churrasque-se")
        loga(
            ctx.first_folder, "ERROR",
            f"Falha ao salvar a descrição da aula {aula[0]}. {aula[1]}",
        )


def _baixar_videos_externos(ctx, links, folder_path, page_order, lesson_name, aula_idx, inicio, total_vids):
    """YouTube/Vimeo da aula, numerados depois dos vídeos Hotmart."""
    first_folder = ctx.first_folder
    for x, link in enumerate(links, start=inicio):
        if not _video_incluido_no_escopo(aula_idx, x, ctx.videos_por_aula):
            continue
        loga(first_folder, "INFO", f"Vídeo externo (YouTube/Vimeo): {link}")
        destino_video = _caminho_video_no_topico(
            folder_path, page_order, lesson_name, x, total_videos=total_vids,
        )
        pronto, existente = _video_ja_baixado(
            folder_path, page_order, lesson_name, x, total_videos=total_vids,
            verificar_completo=ctx.desempenho['verificar_video_completo'],
            qualidade_desejada=ctx.qualidade_video,
        )
        if pronto:
            print(f"  [OK] Vídeo externo {x}/{total_vids} já presente ({existente}), pulando")
            loga(first_folder, "INFO", f"Vídeo externo já presente: {existente}")
            ctx.videos_pulados += 1
            continue
        print(f"  Baixando vídeo externo {x}/{total_vids} (YouTube/Vimeo)\n\t {destino_video}")
        try:
            _baixar_video_externo(
                link, destino_video, first_folder, ctx.qualidade_video, ctx.dominio,
                mostrar_progresso=ctx.opts_video['mostrar_progresso'],
            )
            loga(first_folder, "INFO", "Vídeo externo baixado com sucesso.")
        except KeyboardInterrupt:
            _limpar_parcial(destino_video)
            raise
        except Exception as ext_err:
            _limpar_parcial(destino_video)
            print(f"  Falha no vídeo externo: {ext_err}")
            loga(first_folder, "ERROR", f"Vídeo externo: {ext_err}")
            continue
        if _arquivo_pronto(destino_video):
            ctx.contar_baixado()
            vw, vh = _dimensoes_video_local(destino_video)
            if vw and vh:
                _print_seguro(f"  Resolução real: {vw}x{vh}")
        else:
            _limpar_parcial(destino_video)
            print("  Vídeo externo incompleto — será tentado de novo na próxima execução")
            loga(first_folder, "WARN", "Vídeo externo incompleto após download")


def _avisar_video_incompleto(ctx, folder_path, page_order, lesson_name, duracao_esp):
    for path in glob.glob(os.path.join(folder_path, '*.mp4')):
        if _nome_arquivo_corresponde_aula(os.path.basename(path), page_order, lesson_name):
            loc = _duracao_mp4_local(path)
            print(f"  Vídeo incompleto ({_fmt_tempo(loc or 0)} / {_fmt_tempo(duracao_esp)}): {path}")
            loga(ctx.first_folder, "WARN", f"Vídeo incompleto, re-download: {path}")
            return


def _agendar_video_hotmart(ctx, video, destino_video, duracao_esp):
    """Baixa já (sequencial) ou enfileira (DOWNLOAD_PARALELO > 1)."""
    def _baixar():
        baixar_video_hotmart(
            video[2], video[1], destino_video, ctx.first_folder,
            qualidade=ctx.qualidade_video,
            duracao_esperada=duracao_esp,
            **ctx.opts_video,
        )
        ctx.contar_baixado()

    try:
        ctx.gerenciador.run(_baixar)
    except KeyboardInterrupt:
        _limpar_parcial(destino_video)
        raise
    except FileNotFoundError:
        msg = "ffmpeg não encontrado no PATH. Instale com: brew install ffmpeg"
        print(f"  {msg}")
        loga(ctx.first_folder, "ERROR", msg)
    except Exception as e:
        _limpar_parcial(destino_video)
        loga(ctx.first_folder, "ERROR", f"Erro ao baixar vídeo Hotmart: {e}")
        print(f"  {e}")


def _baixar_videos_hotmart(ctx, videos, folder_path, page_order, lesson_name, aula_idx, total_vids):
    """videos: [nome, id, link, duração?]"""
    for x, video in enumerate(videos, start=1):
        if not _video_incluido_no_escopo(aula_idx, x, ctx.videos_por_aula):
            continue
        destino_video = _caminho_video_no_topico(
            folder_path, page_order, lesson_name, x, total_videos=total_vids,
        )
        duracao_esp = _duracao_esperada_registro_video(video)
        pronto, existente = _video_ja_baixado(
            folder_path, page_order, lesson_name, x, video[0],
            total_videos=total_vids,
            verificar_completo=ctx.desempenho['verificar_video_completo'],
            duracao_esperada=duracao_esp,
            fracao_duracao_minima=ctx.desempenho['fracao_duracao_minima'],
            qualidade_desejada=ctx.qualidade_video,
        )
        if pronto:
            print(f"  [OK] Vídeo {x}/{total_vids} já presente ({existente}), pulando")
            loga(ctx.first_folder, "INFO", f"Vídeo já presente: {existente}")
            ctx.videos_pulados += 1
            continue

        if existente is None and duracao_esp:
            _avisar_video_incompleto(ctx, folder_path, page_order, lesson_name, duracao_esp)
        _limpar_parcial(destino_video)
        print(f"  Baixando vídeo {x}/{total_vids}: {destino_video}")
        loga(ctx.first_folder, "INFO", f"Tentando baixar a aula {x} ({lesson_name})")
        _agendar_video_hotmart(ctx, video, destino_video, duracao_esp)

        pausa = ctx.desempenho['pausa_entre_videos']
        if pausa and not ctx.paralelo:
            time.sleep(pausa)


def _processar_aula(ctx, aula, folder_path, aula_atual, total_aulas):
    aula_idx = ctx.hash_para_idx.get(aula[2])
    page_order, lesson_name = aula[0], aula[1]
    pct_geral = int(100 * aula_atual / total_aulas)
    so_videos = _aula_apenas_videos(aula_idx, ctx.videos_por_aula)
    print(f"\n[{aula_atual}/{total_aulas}] {_barra(pct_geral)} {pct_geral}%  {page_order}. {lesson_name}")
    print(f"  Tópico: {folder_path}")
    ctx.salvar_progresso(
        'em_andamento',
        aulas_feitas=aula_atual - 1,
        aulas_total=total_aulas,
        aula_atual=f"{page_order}. {lesson_name}",
    )

    if not so_videos and _aula_ja_completa_na_pasta(
        folder_path, aula, ctx.desempenho['verificar_video_completo'],
    ):
        ctx.videos_pulados += len(aula[3]['videos'])
        print("  [OK] Arquivos da aula já estão na pasta — pulando para a próxima")
        loga(ctx.first_folder, "INFO", f"Aula completa na pasta, pulada: {page_order}. {lesson_name}")
        return

    if so_videos:
        print("  Modo vídeo específico — pulando descrição/anexos desta aula")
    else:
        _salvar_descricao(ctx, aula, folder_path)

    page_content_html = ''
    try:
        page_content_html = _get_page_json(ctx.authMart, aula[2]).get('content') or ''
    except Exception:
        pass
    videos_api = aula[3]['videos'] or []
    hotmart_videos = [
        v for v in videos_api
        if not (len(v) > 2 and _url_parece_video_externo(v[2]))
    ]
    links_externos = _listar_links_video_externo(page_content_html, videos_api, ctx.dominio)
    total_vids = len(hotmart_videos) + len(links_externos)
    if not total_vids:
        loga(
            ctx.first_folder, "WARN",
            "Aula sem vídeo Hotmart na API e sem embed YouTube/Vimeo no conteúdo",
        )
    if hotmart_videos:
        _baixar_videos_hotmart(
            ctx, hotmart_videos, folder_path, page_order, lesson_name, aula_idx, total_vids,
        )
    _baixar_videos_externos(
        ctx, links_externos, folder_path, page_order, lesson_name, aula_idx,
        inicio=len(hotmart_videos) + 1, total_vids=total_vids,
    )

    if so_videos:
        return
    baixar_anexos_aula(ctx.authMart, aula, folder_path, ctx.first_folder)
    baixar_gdrive_aula(ctx.authMart, aula, folder_path, ctx.first_folder)
    salvar_links_aula(aula, folder_path, ctx.first_folder)


# ---------------------------------------------------------------- fluxo


def listacursos(authMart, params):
    curso = _escolher_curso(_cursos_validos(authMart, _listar_produtos(authMart, params)))
    desempenho = _carregar_desempenho()
    _limpar_cache_paginas()
    nmcurso, dominio, first_folder, navegacao = _abrir_pasta_curso(authMart, curso)

    progresso = _carregar_progresso(first_folder)
    retomar = _perguntar_retomada(progresso, nmcurso)
    escopo = _definir_escopo(authMart, navegacao, progresso, retomar, first_folder)
    _mostrar_dicas_desempenho(desempenho)

    ctx = _Download(
        authMart=authMart,
        nmcurso=nmcurso,
        dominio=dominio,
        first_folder=first_folder,
        desempenho=desempenho,
        escopo=escopo,
        hash_para_idx={p['hash']: p['idx'] for p in escopo.plano_filtrado},
        gerenciador=_GerenciadorDownloadsVideo(desempenho['download_paralelo']),
        opts_video=_opcoes_video(desempenho),
    )
    ctx.salvar_progresso('em_andamento')

    loga(first_folder, "INFO", "Estrutura obtida com sucesso, criando dicionário")
    loga(
        first_folder, "INFO",
        f"Módulos selecionados: {[m.get('name') for m in escopo.modulos_escolhidos]}",
    )
    loga(
        first_folder, "INFO",
        f"Aulas selecionadas: {sorted(escopo.aulas_selecionadas)} | "
        f"vídeos filtrados: {escopo.videos_por_aula}",
    )
    estrutura = _montar_estrutura(authMart, escopo.plano_filtrado, desempenho['api_paralelo'])
    total_aulas = _contar_aulas(estrutura)

    # dump para diagnóstico: o usuário pode enviar este arquivo ao relatar problemas
    with open(os.path.join(first_folder, 'debug.txt'), 'a', encoding='utf-8') as debug:
        debug.write(str(escopo.modulos_escolhidos) + '\n\n\n' + str(estrutura))
    loga(first_folder, "INFO", "Dicionário criado com sucesso, dumpado como debug.txt")
    loga(first_folder, "INFO", f"Total de aulas no curso {nmcurso} {total_aulas}")

    print(
        "\nDica: pode interromper (Ctrl+C) e rodar de novo — "
        "arquivos prontos serão pulados e o download continua de onde parou.\n"
    )
    if desempenho['verificar_video_completo']:
        pct = int(desempenho['fracao_duracao_minima'] * 100)
        print(
            'Verificação de vídeo: ffprobe + duração da aula — completos serão pulados; '
            f'incompletos (<{pct}% do tempo no site) serão baixados de novo.\n'
        )

    total_aulas = total_aulas or 1
    aula_atual = 0
    for module_order, modulos in estrutura.items():
        for nome_modulo, aulas in modulos.items():
            folder_path = _preparar_pasta_topico(ctx, module_order, nome_modulo, aulas)
            for aula in aulas:
                aula_atual += 1
                _processar_aula(ctx, aula, folder_path, aula_atual, total_aulas)

    ctx.gerenciador.aguardar()
    ctx.salvar_progresso('concluido', aulas_feitas=total_aulas, aulas_total=total_aulas)
    print(f"\n[{total_aulas}/{total_aulas}] {_barra(100)} 100%")
    print(f"[RESUMO] Vídeos — baixados: {ctx.videos_baixados} | já existiam: {ctx.videos_pulados}")
    loga(
        first_folder, "INFO",
        f"Download concluído. Vídeos novos: {ctx.videos_baixados}, pulados: {ctx.videos_pulados}",
    )
