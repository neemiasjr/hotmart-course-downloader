"""Leitura do config_cursos.py com valores padrão."""


def valor(nome, padrao=None):
    """config_cursos.NOME, ou `padrao` se o arquivo ou a variável não existir."""
    try:
        import config_cursos
    except ImportError:
        return padrao
    return getattr(config_cursos, nome, padrao)


def _numero(nome, conversor, padrao, minimo=None, maximo=None):
    bruto = valor(nome)
    if bruto is None:
        return padrao
    try:
        numero = conversor(bruto)
    except (TypeError, ValueError):
        return padrao
    if minimo is not None:
        numero = max(minimo, numero)
    if maximo is not None:
        numero = min(maximo, numero)
    return numero


def _booleano(nome, padrao):
    bruto = valor(nome)
    return padrao if bruto is None else bool(bruto)


def _carregar_desempenho():
    """Opções de velocidade e pós-processamento (config_cursos.py ou padrões)."""
    return {
        'pausa_entre_videos': _numero('PAUSA_ENTRE_VIDEOS', float, 0.0, minimo=0.0),
        'medir_duracao': _booleano('MEDIR_DURACAO_VIDEO', False),
        'download_paralelo': _numero('DOWNLOAD_PARALELO', int, 1, 1, 4),
        'api_paralelo': _numero('API_PARALELO', int, 6, 1, 16),
        'corrigir_sync_av': _booleano('CORRIGIR_SYNC_AV', True),
        'corrigir_fluidao': _booleano('CORRIGIR_FLUIDAO_VIDEO', True),
        'fluidao_crf': _numero('FLUIDAO_CRF', int, 20, 0, 51),
        'fluidao_preset': str(valor('FLUIDAO_PRESET') or 'faster'),
        'fluidao_limiar': _numero('FLUIDAO_LIMIAR_IRREGULAR', float, 0.08),
        'verificar_video_completo': _booleano('VERIFICAR_VIDEO_COMPLETO', True),
        'fracao_duracao_minima': _numero('FRACAO_DURACAO_MINIMA', float, 0.90, 0.5, 1.0),
    }


def _cursos_subdominios():
    return [
        str(s).strip() for s in (valor('CURSOS_SUBDOMINIOS') or [])
        if s and str(s).strip()
    ]


def _product_id_por_subdominio(subdomain):
    subdomain = (subdomain or '').strip()
    ids = valor('CURSOS_PRODUCT_IDS')
    if isinstance(ids, dict) and ids.get(subdomain):
        return str(ids[subdomain]).strip()
    unico = valor('HOTMART_PRODUCT_ID')
    if unico:
        return str(unico).strip()
    return None


def _club_locale():
    locale = valor('CLUB_LOCALE')
    return str(locale).strip().lower() if locale else 'pt-br'


def _nome_curso_configurado(subdomain, product_id=None):
    nomes = valor('CURSOS_NOMES')
    if not isinstance(nomes, dict):
        return None
    for chave in (product_id, str(product_id) if product_id else None, subdomain):
        if chave and nomes.get(chave):
            return str(nomes[chave]).strip()
    return None
