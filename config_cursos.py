# Configuração de cursos Hotmart
# Se a API não conseguir listar seus cursos automaticamente, adicione-os aqui
#
# Para encontrar o subdomínio do seu curso:
# 1. Acesse https://sun.hotmart.com/minhas-compras
# 2. Clique em "Acessar" no curso desejado
# 3. Na URL você verá: https://hotmart.com/pt-br/club/SUBDOMAIN/...
# 4. O "SUBDOMAIN" é o que você deve adicionar abaixo
#
# Exemplo: https://hotmart.com/pt-br/club/punchneedlelucrativo/products/123456
#          → subdomínio: punchneedlelucrativo | product ID: 123456

CURSOS_SUBDOMINIOS = [
    "punchneedlelucrativo",  # substitua pelo seu subdomínio
]

# Club novo (hotmart.com/pt-br/club/.../products/ID): ID numérico da URL do produto
CURSOS_PRODUCT_IDS = {
    # "seu-subdominio": "123456",
}

# Qualidade máxima dos vídeos (altura em pixels).
# Exemplos: 360, 480, 720, 1080 | 0 = máxima disponível | None = perguntar ao rodar
QUALIDADE_VIDEO = None

# Escopo opcional (None = perguntar ao rodar o script)
TOPICOS_INDICES = None
AULAS_INDICES = None
AULA_VIDEO = None

# Velocidade (opcional)
PAUSA_ENTRE_VIDEOS = 0
MEDIR_DURACAO_VIDEO = False
DOWNLOAD_PARALELO = 1
API_PARALELO = 6
