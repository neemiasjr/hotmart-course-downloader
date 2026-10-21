"""Autenticação: token Bearer do navegador ou e-mail/senha."""

import base64
import glob
import json
import os

import requests

from .api import USER_AGENT, _validar_token_club
from .config import _cursos_subdominios, _product_id_por_subdominio
from .console import loga


# Endpoint antigo (Sparkle) foi desligado/bloqueado no ELB e responde 403 HTML.
# Fluxo atual da Hotmart Club usa OIDC em sso.hotmart.com; login por senha
# via script costuma falhar por WAF/client secret. Preferir Bearer token do browser.
OAUTH_ENDPOINTS = [
    'https://sso.hotmart.com/oidc/accessToken',
    'https://api-sec-vlc.hotmart.com/security/oauth/token',
    'https://api.sparkleapp.com.br/oauth/token',
]


def _normalizar_token(token):
    if not token:
        return None
    token = token.strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    return token or None


def _verificar_jwt_local(token):
    """Detecta token truncado/corrompido antes de chamar a api-club."""
    parts = token.split('.')
    if len(parts) != 3:
        return False, (
            f"Token JWT inválido: esperadas 3 partes separadas por '.', "
            f"encontradas {len(parts)}."
        )
    if not all(parts):
        return False, "Token incompleto (parte vazia no JWT)."
    try:
        pad = '=' * (-len(parts[1]) % 4)
        json.loads(base64.urlsafe_b64decode(parts[1] + pad))
    except Exception:
        return False, (
            "O JWT colado não decodifica como JSON (cópia incompleta ou alterada).\n"
            "No Chrome: Rede > api-club > request navigation > Request Headers > "
            "Authorization > botão direito > Copy value.\n"
            "Cole direto no terminal (export HOTMART_TOKEN='...'), sem WhatsApp/chat."
        )
    return True, ''


def _sessao_com_token(access_token):
    authMart = requests.session()
    authMart.headers.clear()
    authMart.headers['user-agent'] = USER_AGENT
    authMart.headers['authorization'] = 'Bearer ' + access_token
    authMart.headers['accept'] = 'application/json, text/plain, */*'
    return authMart, {'token': access_token}


def _obter_token_por_senha(authMart, email, senha):
    data = {'username': email, 'password': senha, 'grant_type': 'password'}
    client_id = os.environ.get('HOTMART_CLIENT_ID', '').strip()
    client_secret = os.environ.get('HOTMART_CLIENT_SECRET', '').strip()
    if client_id:
        data['client_id'] = client_id
    if client_secret:
        data['client_secret'] = client_secret

    loga(".", "INFO", f"Tentando autenticar com email {email} (senha omitida do log)")

    ultimo_erro = None
    for url in OAUTH_ENDPOINTS:
        try:
            resp = authMart.post(url, data=data, timeout=30)
        except requests.RequestException as e:
            ultimo_erro = f"{url}: exceção {e}"
            loga(".", "ERROR", ultimo_erro)
            continue

        content_type = (resp.headers.get('content-type') or '').lower()
        if resp.status_code == 200 and 'json' in content_type:
            payload = resp.json()
            if payload.get('access_token'):
                loga(".", "INFO", f"Autenticação bem sucedida via {url}")
                return payload['access_token']
            ultimo_erro = f"{url}: 200 sem access_token"
            loga(".", "ERROR", ultimo_erro)
            continue

        body_preview = (resp.text or '')[:300].replace('\n', ' ')
        ultimo_erro = f"{url}: HTTP {resp.status_code} — {body_preview}"
        loga(".", "ERROR", f"Autenticação falhou em {url}. Código: {resp.status_code}")
        if '<html' in (resp.text or '').lower():
            loga(".", "ERROR", "Resposta HTML (endpoint bloqueado/desligado), não é erro de senha.")
        else:
            loga(".", "ERROR", body_preview)

    raise RuntimeError(ultimo_erro or "Falha ao autenticar")


def autenticacao(**kwargs):
    if not os.path.exists('temp'):
        os.makedirs('temp')
    for f in glob.glob("temp/*"):
        os.remove(f)

    authMart = requests.session()
    authMart.headers['user-agent'] = USER_AGENT
    authMart.headers['accept'] = 'application/json, text/plain, */*'

    # 1) Token já obtido no navegador (recomendado)
    token = _normalizar_token(
        kwargs.get('token')
        or os.environ.get('HOTMART_TOKEN')
        or os.environ.get('HOTMART_ACCESS_TOKEN')
    )

    if not token:
        print(
            "\nA autenticação por email/senha do endpoint antigo (Sparkle) está bloqueada (403).\n"
            "Opção mais confiável: colar o Bearer token da sessão do Club no navegador.\n"
            "\nComo pegar o token:\n"
            "  1. Abra o curso (ex.: hotmart.com/pt-br/club/SEU-SUBDOMAIN/products/...)\n"
            "  2. DevTools (F12) > Rede; recarregue a página (F5)\n"
            "  3. Filtre por 'consumption-gateway' ou 'api-club' (ex.: .../status ou navigation)\n"
            "  4. Copie o Authorization inteiro (JWT com duas pontos; sem quebra de linha)\n"
            "\nOu exporte: export HOTMART_TOKEN='cole_só_o_jwt_ou_Bearer_jwt'\n"
        )
        token_input = input(
            "Cole o Bearer token (ou pressione Enter para tentar email/senha):\n"
        ).strip()
        token = _normalizar_token(token_input)

    if token:
        ok_jwt, msg_jwt = _verificar_jwt_local(token)
        if not ok_jwt:
            print(msg_jwt)
            loga(".", "ERROR", msg_jwt.replace('\n', ' '))
            exit(13)
        loga(".", "INFO", "Autenticando com Bearer token fornecido")
        session, params = _sessao_com_token(token)
        # Tokens do Club (client b432cdd3-...) são rejeitados pelo check_token antigo.
        # Valida direto na API do Club, que é o que o download usa.
        subdominios = _cursos_subdominios()
        if not subdominios:
            print(
                "Configure CURSOS_SUBDOMINIOS em config_cursos.py "
                "para validar o Bearer token."
            )
            loga(".", "ERROR", "CURSOS_SUBDOMINIOS vazio — não foi possível validar token")
            exit(13)
        ok = False
        status = 0
        detalhe = ''
        for subdomain in subdominios:
            product_id = _product_id_por_subdominio(subdomain)
            ok, status, detalhe = _validar_token_club(session, subdomain, product_id)
            if ok:
                break
        if not ok:
            print(
                "Token inválido, incompleto ou expirado.\n"
                "Com o curso aberto em hotmart.com/pt-br/club/..., copie de novo o "
                "Authorization (consumption-gateway ou api-club).\n"
                f"Detalhe: HTTP {status}" + (f" — {detalhe}" if detalhe else "")
            )
            loga(".", "ERROR", f"Token rejeitado na api-club: HTTP {status} {detalhe}")
            exit(13)
        loga(".", "INFO", "Token aceito pela api-club")
        return session, params

    # 2) Fallback: email/senha nos endpoints atuais
    email = kwargs.get("email", None)
    if email is None:
        email = str(input("Qual o email de login?\n"))
    senha = kwargs.get("senha", None)
    if senha is None:
        senha = str(input("Qual a senha de login?\n"))

    try:
        access_token = _obter_token_por_senha(authMart, email, senha)
    except RuntimeError as e:
        print(
            "\nNão foi possível autenticar com email/senha.\n"
            "Isso é esperado: o endpoint Sparkle retorna 403 e o SSO novo usa WAF/OIDC.\n"
            "Rode de novo e cole o Bearer token do navegador (veja as instruções acima).\n"
            f"Detalhe técnico: {e}\n"
        )
        loga(".", "ERROR", f"Autenticação por senha esgotou endpoints: {e}")
        exit(13)

    return _sessao_com_token(access_token)
