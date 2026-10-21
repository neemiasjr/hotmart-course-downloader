"""Chamadas às APIs da Hotmart (Club, consumption-gateway e compras)."""

import threading

import requests

from .config import _club_locale, _nome_curso_configurado, _product_id_por_subdominio
from .console import loga
from .nomes import _sanitizar_nome_curso, slugify


_page_cache = {}


_page_cache_lock = threading.Lock()


def _limpar_cache_paginas():
    with _page_cache_lock:
        _page_cache.clear()


def _get_page_json(authMart, page_hash):
    with _page_cache_lock:
        if page_hash in _page_cache:
            return _page_cache[page_hash]
    product_id = getattr(authMart, 'hotmart_product_id', None)
    subdomain = getattr(authMart, 'hotmart_subdomain', None)
    headers_salvos = dict(authMart.headers)
    if product_id:
        _aplicar_headers_consumidor(authMart, product_id, subdomain)
    try:
        resp = authMart.get(
            f'{CLUB_API}/page/{page_hash}',
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    finally:
        authMart.headers.clear()
        authMart.headers.update(headers_salvos)
    with _page_cache_lock:
        _page_cache[page_hash] = data
    return data


USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
)


CLUB_API = 'https://api-club.hotmart.com/hot-club-api/rest/v3'


PURCHASE_API = 'https://api-hub.cb.hotmart.com/club-drive-api/rest/v2/purchase/'


CLUB_CONSUMER_GW = (
    'https://api-club-course-consumption-gateway-ga.cb.hotmart.com'
)


CLUB_CONSUMER_APP = '@hotmart/app-club-consumer_v1.366.4'


CLUB_CONSUMER_HTTP = 'APP_CLUB_CONSUMER_API_COURSE_CONSUMPTION_GATEWAY_INSTANCE'


def _referer_club(subdomain):
    locale = _club_locale()
    return f'https://hotmart.com/{locale}/club/{subdomain}/'


def _aplicar_headers_club(session, subdomain):
    """Club novo abre em hotmart.com/pt-br/club/SUBDOMAIN (não só *.club.hotmart.com)."""
    session.headers['club'] = subdomain
    session.headers['origin'] = 'https://hotmart.com'
    session.headers['referer'] = _referer_club(subdomain)


def _aplicar_headers_consumidor(session, product_id, subdomain=None):
    """App Club novo (consumption-gateway + page v3 com x-product-id)."""
    session.headers['x-product-id'] = str(product_id)
    session.headers['x-app-name'] = CLUB_CONSUMER_APP
    session.headers['x-hot-club-http'] = CLUB_CONSUMER_HTTP
    session.headers.pop('club', None)
    session.headers['origin'] = 'https://hotmart.com'
    if subdomain:
        base = _referer_club(subdomain).rstrip('/')
        session.headers['referer'] = f'{base}/products/{product_id}/'


def _normalizar_modulos_gateway(data):
    for i, modulo in enumerate(data.get('modules') or [], start=1):
        modulo['moduleOrder'] = i
        for j, page in enumerate(modulo.get('pages') or [], start=1):
            page.setdefault('pageOrder', j)
    return data


def _get_navigation_json(session, subdomain, product_id=None):
    product_id = product_id or _product_id_por_subdominio(subdomain)
    if product_id:
        _aplicar_headers_consumidor(session, product_id, subdomain)
        resp = session.get(
            f'{CLUB_CONSUMER_GW}/v1/navigation?productId={product_id}',
            timeout=30,
        )
        resp.raise_for_status()
        return _normalizar_modulos_gateway(resp.json())
    _aplicar_headers_club(session, subdomain)
    resp = session.get(f'{CLUB_API}/navigation', timeout=30)
    if resp.status_code == 403:
        raise RuntimeError(
            "A API antiga do Club (navigation) retornou 403. "
            "Cursos em hotmart.com/pt-br/club/.../products/ID precisam do ID "
            "em config_cursos.py → CURSOS_PRODUCT_IDS."
        )
    resp.raise_for_status()
    return resp.json()


def _listar_compras(session):
    """Produtos comprados (id, name, hotmartClub.slug); cache por sessão."""
    cache = getattr(session, '_hotmart_compras', None)
    if cache is not None:
        return cache
    produtos = []
    try:
        resp = requests.get(
            PURCHASE_API,
            params={'archived': 'UNARCHIVED'},
            headers={
                'authorization': session.headers.get('authorization', ''),
                'user-agent': USER_AGENT,
                'accept': 'application/json, text/plain, */*',
                'origin': 'https://consumer.hotmart.com',
                'referer': 'https://consumer.hotmart.com/',
            },
            timeout=30,
        )
        if resp.status_code == 200:
            for compra in resp.json().get('data') or []:
                produto = compra.get('product') or {}
                if produto.get('id') and produto.get('name'):
                    produtos.append(produto)
        else:
            loga(".", "DEBUG", f"API de compras respondeu HTTP {resp.status_code}")
    except Exception as e:
        loga(".", "DEBUG", f"API de compras indisponível: {e}")
    session._hotmart_compras = produtos
    return produtos


def _nome_produto_por_compras(session, subdomain, product_id=None):
    produtos = _listar_compras(session)
    if product_id:
        for produto in produtos:
            if str(produto.get('id')) == str(product_id):
                return produto['name'].strip()
    por_slug = [
        p for p in produtos
        if (p.get('hotmartClub') or {}).get('slug') == subdomain
    ]
    if len(por_slug) == 1:
        return por_slug[0]['name'].strip()
    if len(por_slug) > 1:
        loga(
            ".", "WARN",
            f"Club '{subdomain}' tem {len(por_slug)} produtos; defina o ID em "
            "CURSOS_PRODUCT_IDS para usar o nome correto.",
        )
    return None


def _nomes_legados_pasta_curso(subdomain, nome_atual, navegacao=None):
    """Nomes de pasta (slug) gerados por versões anteriores para o mesmo curso."""
    candidatos = [slugify(nome_atual), slugify(subdomain), slugify(subdomain.replace('-', ' '))]
    mods = (navegacao or {}).get('modules') or []
    rotulo = ' / '.join(
        _sanitizar_nome_curso(m.get('name', '')) for m in mods[:2] if m.get('name')
    )
    if rotulo:
        candidatos.append(slugify(_sanitizar_nome_curso(
            f"{subdomain.replace('-', ' ')} ({rotulo[:80]})"
        )))
    vistos = []
    for c in candidatos:
        if c and c not in vistos:
            vistos.append(c)
    return vistos


def _obter_nome_curso(session, subdomain, product_id=None):
    product_id = product_id or _product_id_por_subdominio(subdomain)
    nome = _nome_curso_configurado(subdomain, product_id)
    if nome:
        return nome
    nome = _nome_produto_por_compras(session, subdomain, product_id)
    if nome:
        return nome

    _aplicar_headers_club(session, subdomain)
    for url in (
        f'{CLUB_API}/membership?attach_token=false',
        f'{CLUB_API}/navigation',
    ):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code != 200:
                continue
            data = resp.json()
            for key in ('name', 'title', 'productName', 'clubName', 'productTitle'):
                val = data.get(key)
                if val:
                    return str(val).strip()
        except Exception as e:
            loga(".", "DEBUG", f"Nome do curso via {url}: {e}")
    fallback = subdomain.replace('-', ' ')
    loga(".", "WARN", f"Nome do curso não veio da API; usando '{fallback}'")
    return fallback


def _validar_token_club(session, subdomain, product_id=None):
    product_id = product_id or _product_id_por_subdominio(subdomain)
    if product_id:
        _aplicar_headers_consumidor(session, product_id, subdomain)
        probe = session.get(
            f'{CLUB_CONSUMER_GW}/v1/user/{product_id}/status',
            timeout=30,
        )
        if probe.status_code in (401, 403):
            return False, probe.status_code, (probe.text or '')[:200]
        if probe.status_code == 200:
            try:
                if probe.json().get('active'):
                    return True, probe.status_code, ''
            except Exception:
                pass
        nav = session.get(
            f'{CLUB_CONSUMER_GW}/v1/navigation?productId={product_id}',
            timeout=30,
        )
        if nav.status_code in (401, 403):
            return False, nav.status_code, (nav.text or '')[:200]
        if nav.status_code == 200 and (nav.json().get('modules') is not None):
            return True, nav.status_code, ''
        return False, nav.status_code, (nav.text or '')[:200]

    _aplicar_headers_club(session, subdomain)
    probe = session.get(f'{CLUB_API}/navigation', timeout=30)
    if probe.status_code in (401, 403):
        return False, probe.status_code, probe.text[:200]
    try:
        payload = probe.json()
        if payload.get('error') == 'invalid_token':
            desc = payload.get('error_description') or payload.get('error')
            return False, probe.status_code, str(desc)
        if probe.status_code == 200 and payload.get('modules') is not None:
            return True, probe.status_code, ''
    except Exception:
        pass
    if probe.status_code != 200:
        return False, probe.status_code, (probe.text or '')[:200]
    return True, probe.status_code, ''
