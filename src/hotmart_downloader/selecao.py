"""Seleção interativa de qualidade, tópicos, aulas e vídeos."""

import re

from .api import _get_page_json
from .config import valor
from .nomes import _nome_arquivo_seguro


_PENDENTE_ESCOLHA_VIDEO = '__escolher_video__'


def _selecionar_qualidade():
    """
    Pergunta a qualidade máxima dos vídeos.
    Retorna altura em pixels (0 = máxima disponível).
    Pode ser pré-definida em config_cursos.QUALIDADE_VIDEO.
    """
    opcoes = [
        (360, "360p — mais rápido, menor qualidade"),
        (480, "480p — rápido"),
        (720, "720p — equilibrado (recomendado)"),
        (1080, "1080p — alta qualidade"),
        (0, "Máxima disponível — mais lento"),
    ]

    cfg_qualidade = valor('QUALIDADE_VIDEO')
    if cfg_qualidade is not None:
        try:
            q = int(cfg_qualidade)
        except (TypeError, ValueError):
            q = None
        if q is not None and (q == 0 or q in {o[0] for o in opcoes if o[0]}):
            label = next((lbl for h, lbl in opcoes if h == q), f"{q}p")
            print(f"\nQualidade definida em config_cursos.py: {label}")
            return q
        if q is not None and q > 0:
            print(f"\nQualidade definida em config_cursos.py: até {q}p")
            return q

    print("\n=== Qualidade do vídeo ===")
    for i, (_, label) in enumerate(opcoes, start=1):
        print(f"{i}. {label}")
    print("\nQualidades menores = download mais rápido e menos espaço em disco.")

    raw = input("> ").strip().lower()
    if not raw or raw in ('3', '720', '720p'):
        print("Usando 720p.")
        return 720

    mapa_texto = {
        '1': 360, '360': 360, '360p': 360,
        '2': 480, '480': 480, '480p': 480,
        '3': 720, '720': 720, '720p': 720,
        '4': 1080, '1080': 1080, '1080p': 1080,
        '5': 0, 'max': 0, 'maxima': 0, 'máxima': 0, '0': 0,
    }
    if raw in mapa_texto:
        escolhida = mapa_texto[raw]
        label = next((lbl for h, lbl in opcoes if h == escolhida), f"{escolhida}p")
        print(f"Usando: {label}")
        return escolhida

    try:
        q = int(raw.replace('p', ''))
        if q > 0:
            print(f"Usando até {q}p.")
            return q
    except ValueError:
        pass

    print("Opção inválida. Usando 720p.")
    return 720


def _parse_selecao_numeros(raw, max_n, fallback_todos=True):
    """
    Interpreta seleção numérica: Enter/0/todos = todos; 2; 1,3; 2-4.
    Retorna set de índices 1..max_n ou set() se max_n==0.
    """
    if max_n <= 0:
        return set()

    raw = (raw or '').strip().lower()
    if not raw or raw in ('0', 'all', 'todos', '*'):
        return set(range(1, max_n + 1))

    escolhidos = set()
    for parte in raw.replace(' ', '').split(','):
        if not parte:
            continue
        if '-' in parte and ':' not in parte:
            a, b = parte.split('-', 1)
            try:
                inicio, fim = int(a), int(b)
            except ValueError:
                print(f"Ignorando trecho inválido: {parte}")
                continue
            for n in range(min(inicio, fim), max(inicio, fim) + 1):
                if 1 <= n <= max_n:
                    escolhidos.add(n)
        else:
            try:
                n = int(re.match(r'^(\d+)', parte).group(1))
            except (ValueError, AttributeError):
                print(f"Ignorando trecho inválido: {parte}")
                continue
            if 1 <= n <= max_n:
                escolhidos.add(n)

    if not escolhidos:
        if fallback_todos:
            print("Nenhuma opção válida. Usando todos.")
            return set(range(1, max_n + 1))
        return set()
    return escolhidos


def _parse_selecao_topicos(raw, max_n):
    """
    Tópicos (módulos): 5 | 1,3 | 2-4 | 5:2 (só a 2ª aula do tópico 5) | 5:2,4 | 5:2-4
    Retorna (set índices de tópico 1..max_n, dict tópico -> set índices de aula no tópico).
    Chaves em aulas_por_topico só existem quando o usuário restringiu aulas daquele tópico.
    """
    if max_n <= 0:
        return set(), {}

    raw = (raw or '').strip().lower()
    if not raw or raw in ('0', 'all', 'todos', '*'):
        return set(range(1, max_n + 1)), {}

    topicos = set()
    aulas_por_topico = {}

    for parte in raw.replace(' ', '').split(','):
        if not parte:
            continue
        match = re.match(r'^(\d+)(?::([\d,\-*]+))?$', parte)
        if not match:
            print(f"Ignorando trecho inválido: {parte}")
            continue
        t_idx = int(match.group(1))
        if not (1 <= t_idx <= max_n):
            print(f"Ignorando tópico fora da lista: {t_idx}")
            continue
        topicos.add(t_idx)
        sufixo = match.group(2)
        if sufixo is None:
            continue
        aulas = _parse_selecao_numeros(sufixo, 9999, fallback_todos=False)
        if not aulas:
            print(f"Ignorando aulas inválidas em {parte}")
            continue
        aulas_por_topico[t_idx] = aulas

    if not topicos:
        print("Nenhum tópico válido. Usando todos.")
        return set(range(1, max_n + 1)), {}
    return topicos, aulas_por_topico


def _mapa_ordem_topicos(modulos):
    """moduleOrder -> índice 1-based na lista de módulos do curso."""
    ordenados = _modulos_ordenados(modulos)
    return {m.get('moduleOrder'): i + 1 for i, m in enumerate(ordenados)}


def _resolver_indice_aula_no_plano(n, plano):
    """
    Converte número digitado pelo usuário em idx do plano (1ª coluna da lista).
    Aceita idx direto, posição da aula no tópico ou pageOrder quando for único no plano.
    """
    if not plano:
        return None
    if any(p['idx'] == n for p in plano):
        return n
    por_pos = [p['idx'] for p in plano if p.get('lesson_in_topic_idx') == n]
    if len(por_pos) == 1:
        return por_pos[0]
    por_page = [p['idx'] for p in plano if p.get('page_order') == n]
    if len(por_page) == 1:
        return por_page[0]
    return None


def _filtrar_plano_por_aulas_no_topico(plano, aulas_por_topico):
    if not aulas_por_topico:
        return plano
    out = []
    for item in plano:
        t = item.get('topic_display_idx')
        restr = aulas_por_topico.get(t)
        if restr is None:
            out.append(item)
        elif item.get('lesson_in_topic_idx') in restr:
            out.append(item)
    return out


def _modulos_ordenados(modulos):
    return sorted(modulos, key=lambda m: m.get('moduleOrder', 0))


def _selecionar_modulos(modulos, raw=None):
    """
    Mostra a lista de módulos e deixa o usuário escolher quais baixar.
    Aceita: 0/all/enter=todos | 2 | 1,3,5 | 2-4 | 5:2 (só a 2ª aula do tópico 5)
    raw: seleção pré-definida (ex.: config_cursos.TOPICOS_INDICES como string "5" ou "5:2")
    Retorna (lista de módulos, dict opcional tópico -> aulas dentro do tópico).
    """
    ordenados = _modulos_ordenados(modulos)
    print(f"\n=== Módulos / tópicos ({len(ordenados)}) ===")
    for i, modulo in enumerate(ordenados, start=1):
        num_aulas = len(modulo.get('pages') or [])
        nome = _nome_arquivo_seguro(modulo.get('name', 'Sem nome'))
        print(f"{i}. {nome} ({num_aulas} aula(s))")

    if raw is None:
        raw = input(
            "\nQuais tópicos deseja baixar?\n"
            "  0 ou Enter = todos | ex: 2 | 1,3,5 | 2-4\n"
            "  Só algumas aulas de um tópico: 5:2 | 5:2,4 | 5:2-4\n"
            "> "
        )

    escolhidos, aulas_por_topico = _parse_selecao_topicos(raw, len(ordenados))
    if len(escolhidos) == len(ordenados) and not aulas_por_topico:
        print(f"Baixando todos os {len(ordenados)} tópico(s).")
        return ordenados, {}

    filtrados = [m for i, m in enumerate(ordenados, start=1) if i in escolhidos]
    print("Tópicos selecionados:")
    for m in filtrados:
        print(f" - {_nome_arquivo_seguro(m.get('name', ''))}")
    if aulas_por_topico:
        for t in sorted(aulas_por_topico):
            nums = ','.join(str(x) for x in sorted(aulas_por_topico[t]))
            print(f"   Tópico {t}: somente aula(s) {nums} (ordem dentro do tópico)")
    return filtrados, aulas_por_topico


def _plano_aulas(modulos_escolhidos, todos_modulos=None):
    """Lista plana de aulas (1..N) nos tópicos escolhidos."""
    if todos_modulos is None:
        todos_modulos = modulos_escolhidos
    ordem_topico = _mapa_ordem_topicos(todos_modulos)
    plano = []
    idx = 0
    for modulo in _modulos_ordenados(modulos_escolhidos):
        pages = sorted(modulo.get('pages') or [], key=lambda p: p.get('pageOrder', 0))
        topic_display_idx = ordem_topico.get(modulo.get('moduleOrder'))
        for lesson_in_topic_idx, page in enumerate(pages, start=1):
            idx += 1
            plano.append({
                'idx': idx,
                'module': modulo,
                'page': page,
                'module_order': modulo.get('moduleOrder'),
                'module_name': _nome_arquivo_seguro(modulo.get('name', '')),
                'page_order': page.get('pageOrder'),
                'page_name': _nome_arquivo_seguro(page.get('name', '')),
                'hash': page.get('hash'),
                'topic_display_idx': topic_display_idx,
                'lesson_in_topic_idx': lesson_in_topic_idx,
            })
    return plano


def _parse_videos_de_texto(texto):
    """Ex.: '2', '1,3', '1-3' -> set de índices de vídeo (1-based)."""
    texto = (texto or '').strip().lower()
    if not texto or texto in ('0', '*', 'all', 'todos'):
        return None
    return _parse_selecao_numeros(texto, 9999)


def _parse_escopo_aulas(raw, num_aulas, plano=None):
    """
    Interpreta seleção de aulas/vídeos.
    Retorna (set índices de aula, dict aula_idx -> set vídeos ou None=todos).
    Valores especiais em videos_por_aula: chave com set() vazio = escolher vídeos depois.
    """
    raw = (raw or '').strip().lower()
    if not raw or raw in ('0', 'all', 'todos', '*'):
        return set(range(1, num_aulas + 1)), {}

    aulas = set()
    videos_por_aula = {}

    for parte in raw.replace(' ', '').split(','):
        if not parte:
            continue
        match_topico = re.match(r'^(\d+):(\d+)$', parte)
        if match_topico and plano:
            t_idx = int(match_topico.group(1))
            l_idx = int(match_topico.group(2))
            hits = [
                p['idx'] for p in plano
                if p.get('topic_display_idx') == t_idx
                and p.get('lesson_in_topic_idx') == l_idx
            ]
            if hits:
                aulas.update(hits)
                continue
        match = re.match(r'^(\d+)(?::v?([\d,\-*]*))?$', parte)
        if not match:
            print(f"Ignorando trecho inválido: {parte}")
            continue
        a_num = int(match.group(1))
        sufixo = match.group(2)
        if sufixo is None:
            a_idx = _resolver_indice_aula_no_plano(a_num, plano) if plano else None
            if a_idx is None and 1 <= a_num <= num_aulas:
                a_idx = a_num
            if a_idx is None:
                print(f"Ignorando aula fora da lista: {a_num}")
                continue
            aulas.add(a_idx)
            continue
        if sufixo == '':
            a_idx = _resolver_indice_aula_no_plano(a_num, plano) if plano else a_num
            if a_idx is None or not (1 <= a_idx <= num_aulas):
                print(f"Ignorando aula fora da lista: {a_num}")
                continue
            aulas.add(a_idx)
            videos_por_aula[a_idx] = _PENDENTE_ESCOLHA_VIDEO
        else:
            a_idx = _resolver_indice_aula_no_plano(a_num, plano) if plano else None
            if a_idx is None and 1 <= a_num <= num_aulas:
                a_idx = a_num
            if a_idx is None:
                print(f"Ignorando aula fora da lista: {a_num}")
                continue
            aulas.add(a_idx)
            vids = _parse_videos_de_texto(sufixo)
            if vids:
                videos_por_aula[a_idx] = vids

    if not aulas:
        return set(), {}

    return aulas, videos_por_aula


def _listar_videos_da_pagina(authMart, page_hash):
    """Retorna lista de nomes de vídeo Hotmart na página (ordem da API)."""
    try:
        payload = _get_page_json(authMart, page_hash)
    except Exception:
        return []
    nomes = []
    for video in payload.get('mediasSrc') or []:
        nomes.append(_nome_arquivo_seguro(video.get('mediaName', 'Vídeo')))
    return nomes


def _resolver_videos_pendentes(videos_por_aula, plano, authMart):
    """Completa seleção quando o usuário usou N:v (escolher vídeo interativamente)."""
    out = {}
    for a_idx, filtro in videos_por_aula.items():
        if filtro is not _PENDENTE_ESCOLHA_VIDEO:
            out[a_idx] = filtro
            continue
        item = plano[a_idx - 1]
        nomes = _listar_videos_da_pagina(authMart, item['hash'])
        print(f"\n=== Vídeos da aula {a_idx}: {item['page_name']} ===")
        if not nomes:
            print("  (nenhum vídeo Hotmart na API — serão tentados embeds externos)")
            out[a_idx] = None
            continue
        for vi, nome in enumerate(nomes, start=1):
            print(f"  v{vi}. {nome}")
        raw_v = input(
            "Qual(is) vídeo(s)? Enter = todos | ex: 2 | 1,3\n> "
        ).strip().lower()
        escolha = _parse_videos_de_texto(raw_v.replace('v', ''))
        out[a_idx] = escolha

    return out


def _escopo_aulas_de_config(plano):
    """Lê AULAS_INDICES / AULA_VIDEO de config_cursos.py, se definidos."""
    AULAS_INDICES = valor('AULAS_INDICES')
    AULA_VIDEO = valor('AULA_VIDEO')
    if AULAS_INDICES is None and AULA_VIDEO is None:
        return None

    n = len(plano)
    if AULAS_INDICES is not None:
        raw = _indices_config_para_raw(AULAS_INDICES, 'AULAS_INDICES')
        aulas, videos = _parse_escopo_aulas(raw, n, plano)
    else:
        aulas = set(range(1, n + 1))
        videos = {}

    if AULA_VIDEO is not None:
        if isinstance(AULA_VIDEO, dict):
            for key, val in AULA_VIDEO.items():
                a_idx = int(key)
                aulas.add(a_idx)
                if isinstance(val, (list, tuple, set)):
                    videos[a_idx] = {int(v) for v in val}
                else:
                    videos[a_idx] = {int(val)}
        else:
            extra_aulas, extra_v = _parse_escopo_aulas(str(AULA_VIDEO), n, plano)
            if AULAS_INDICES is None:
                aulas = extra_aulas
            else:
                aulas &= extra_aulas
                if not aulas:
                    aulas = extra_aulas
            videos.update(extra_v)

    print("\nEscopo de aulas definido em config_cursos.py")
    return aulas, videos


def _selecionar_escopo_aulas(plano, authMart, raw=None, aulas_ja_filtradas=False):
    """
    Escolhe quais aulas (e opcionalmente vídeos) baixar.
    Ex.: 3 | 1,5 | 5:v2 (só vídeo 2 da aula 5) | 5:v (lista vídeos) | 5:2 (tópico 5, 2ª aula)
    """
    if not plano:
        return set(), {}

    if aulas_ja_filtradas:
        aulas = {p['idx'] for p in plano}
        videos_por_aula = {}
        print(f"\nUsando {len(aulas)} aula(s) já filtradas na seleção de tópicos.")
    else:
        cfg = None if raw is not None else _escopo_aulas_de_config(plano)
        if cfg is not None:
            aulas, videos_por_aula = cfg
            if not aulas:
                print("AVISO: AULAS_INDICES / AULA_VIDEO no config não selecionou nenhuma aula.")
        else:
            print(f"\n=== Aulas nos tópicos selecionados ({len(plano)}) ===")
            for item in plano:
                print(
                    f"{item['idx']}. [{item['module_name']}] "
                    f"({item['lesson_in_topic_idx']}) {item['page_order']}. {item['page_name']}"
                )
            aulas = set()
            videos_por_aula = {}
            prompt_aulas = (
                "\nQuais aulas baixar?\n"
                "  Enter ou 0 = todas\n"
                "  ex: 3 | 1,5,10 | 2-4 | 9,10 (nº no tópico, se único)\n"
                "  Tópico:aula: 5:2 | Um vídeo: 5:v2 ou 5:2 (se não existir 5:2 como tópico)\n"
                "> "
            )
            while not aulas:
                if raw is None:
                    raw = input(prompt_aulas)
                r = (raw or '').strip().lower()
                if r in ('0', 'all', 'todos', '*', ''):
                    aulas = set(range(1, len(plano) + 1))
                    videos_por_aula = {}
                    break
                aulas, videos_por_aula = _parse_escopo_aulas(raw, len(plano), plano)
                if aulas:
                    break
                print(
                    "Nenhuma aula válida. Use o número à esquerda (ex.: 3), "
                    "número da aula no tópico se for único (ex.: 9,10), "
                    "tópico:aula (5:2) ou vídeo (5:v2)."
                )
                raw = None

    if any(v is _PENDENTE_ESCOLHA_VIDEO for v in videos_por_aula.values()):
        videos_por_aula = _resolver_videos_pendentes(videos_por_aula, plano, authMart)

    videos_por_aula = {
        k: v for k, v in videos_por_aula.items()
        if v is not None and v is not _PENDENTE_ESCOLHA_VIDEO
    }

    print(f"\nBaixando {len(aulas)} aula(s) de {len(plano)}.")
    if videos_por_aula:
        for a_idx, vids in sorted(videos_por_aula.items()):
            nomes = ','.join(f'v{v}' for v in sorted(vids))
            print(f"  Aula {a_idx}: somente {nomes}")
    return aulas, videos_por_aula


def _indices_config_para_raw(bruto, nome_cfg='INDICES'):
    """
    Converte TOPICOS_INDICES / AULAS_INDICES do config para string de seleção.
    Aceita: "1-2", [1, 2], 5 | int único | None
    """
    if bruto is None:
        return None
    if isinstance(bruto, str):
        return bruto.strip()
    if isinstance(bruto, int):
        if bruto < 0:
            print(
                f"\nAVISO: {nome_cfg}={bruto} parece subtração (ex.: 1-2 sem aspas vira -1).\n"
                f"Use string \"1-2\" ou lista [1, 2] em config_cursos.py.\n"
            )
        return str(bruto)
    if isinstance(bruto, (list, tuple, set)):
        return ','.join(str(x) for x in bruto)
    return str(bruto)


def _topicos_raw_de_config():
    return _indices_config_para_raw(valor('TOPICOS_INDICES'), 'TOPICOS_INDICES')


def _escopo_de_progresso(progresso, plano, authMart):
    indices = progresso.get('aulas_indices')
    if not indices:
        return _selecionar_escopo_aulas(plano, authMart)
    aulas = set(int(i) for i in indices)
    videos_por_aula = {}
    for key, vals in (progresso.get('videos_por_aula') or {}).items():
        videos_por_aula[int(key)] = set(int(v) for v in vals)
    print(f"\nRetomando escopo salvo: {len(aulas)} aula(s).")
    return aulas, videos_por_aula


def _serializar_videos_por_aula(videos_por_aula):
    return {
        str(k): sorted(videos_por_aula[k])
        for k in videos_por_aula
    }


def _video_incluido_no_escopo(aula_idx, video_idx, videos_por_aula):
    """True se este vídeo deve ser baixado (1-based)."""
    if aula_idx is None or aula_idx not in videos_por_aula:
        return True
    return video_idx in videos_por_aula[aula_idx]


def _aula_apenas_videos(aula_idx, videos_por_aula):
    """True se o usuário pediu só alguns vídeos (sem anexos/descrição completa)."""
    if aula_idx is None:
        return False
    return aula_idx in videos_por_aula
