# Hotmart Downloader

Script pra baixar cursos da Hotmart. Baixa vídeos, PDFs e anexos embutidos.

## Origem

Baseado no gist do [@juvenal](https://gist.github.com/juvenal/2d9a822325769d30c45c635fbf388c1b) com melhorias pra downloads de PDFs embutidos do Google Drive.

## Por que precisa de subdomínio manual?

A API da Hotmart mudou (2026) e agora o endpoint `check_token` retorna `resources: []` vazio, mesmo quando você tem cursos comprados. Por isso o script precisa que você informe manualmente o subdomínio dos cursos no arquivo `config_cursos.py`. É um workaround até acharem outra forma de listar os cursos automaticamente.

## Requisitos

- Python 3.6+
- FFMPEG (precisa estar no PATH do sistema)
- Conexão estável se for baixar vídeos

## Como usar

1. Instale as dependências:
```bash
pip install -r requirements.txt
```

2. Edite `config_cursos.py` com subdomínio e, no Club novo, o ID do produto na URL:
```python
CURSOS_SUBDOMINIOS = ["seu-subdominio"]
CURSOS_PRODUCT_IDS = {
    "seu-subdominio": "123456",  # .../products/123456
}
```

**Como achar subdomínio e product ID:**
1. Vai em https://sun.hotmart.com/minhas-compras
2. Clica em "Acessar" no curso
3. Na URL: `https://hotmart.com/pt-BR/club/SEU-SUBDOMAIN/products/123456`
4. Subdomínio = `SEU-SUBDOMAIN` | Product ID = `123456`

3. Autenticação (Bearer token do navegador — login por senha no script costuma falhar):
```bash
export HOTMART_TOKEN='cole_o_JWT_copiado_do_DevTools'
python hotmark.py
```

No Chrome: abra o curso → F12 → Rede → F5 → filtre `consumption-gateway` ou `api-club` → request `status` ou `navigation` → copie **Authorization** (JWT inteiro, sem quebrar linha). **Não** cole o token em chat/e-mail.

4. Roda o script (se não exportou o token, ele pede na hora):
```bash
python hotmark.py
```

## O que baixa

- Vídeos (Hotmart, Vimeo, YouTube)
- Anexos normais (PDFs, arquivos zip, etc)
- PDFs embutidos do Google Drive (esses ficavam escondidos antes)
- Links de leitura complementar
- Descrições das aulas

Tudo organizado por **tópico (módulo)**: vídeos na pasta do tópico (`2.nome-da-aula.mp4`), descrições em `descricoes/` e anexos em `Materiais/`.

## Baixar só um tópico, aula ou vídeo

Depois de escolher o curso, o script pergunta:

1. **Tópicos (módulos)** — `Enter` = todos; `5` = só o 5º; `1,3` ou `2-4`
2. **Aulas** — lista numerada dentro dos tópicos escolhidos; mesma sintaxe (`3`, `1,5`, `2-4`)
3. **Um vídeo só** — na pergunta das aulas: `5:v2` (aula 5, 2º vídeo) ou `5:v` (mostra a lista de vídeos)

Dá para fixar no `config_cursos.py` sem perguntar:

```python
TOPICOS_INDICES = 5          # ou [1, 3] ou "2-4"
AULAS_INDICES = [2, 5]       # opcional
AULA_VIDEO = "5:v2"          # ou {5: 2}
```

## Por que demora?

O tempo quase sempre é **tamanho do vídeo × qualidade × velocidade da internet**. O script baixa o stream HLS com ffmpeg (um vídeo por vez por padrão), e antes havia pausa de 1s e ffprobe em cada aula.

Para ir **mais rápido**:

1. **Qualidade menor** — o maior ganho: `QUALIDADE_VIDEO = 480` ou `720` no `config_cursos.py`
2. **Paralelo** — `DOWNLOAD_PARALELO = 2` (ou `3` se a rede aguentar; não exagere para evitar bloqueio)
3. **Sem ffprobe** — já é o padrão (`MEDIR_DURACAO_VIDEO = False`); ligue só se quiser barra de % mais exata
4. **Menos escopo** — baixe só um tópico/aula (`TOPICOS_INDICES`, `AULAS_INDICES`)

## Qualidade do vídeo

Na hora de baixar, o script pergunta a qualidade máxima (360p, 480p, 720p, 1080p ou máxima). Qualidades menores baixam mais rápido e ocupam menos disco.

Para pular a pergunta, defina em `config_cursos.py`:
```python
QUALIDADE_VIDEO = 720  # ou 360, 480, 1080, 0 (máxima)
DOWNLOAD_PARALELO = 2  # opcional: 2–3 downloads Hotmart simultâneos
```

## Alguns detalhes

- Se der erro baixando anexo, tenta 3 vezes antes de desistir
- PDFs do Google Drive são salvos como `gdrive_xxxxx.pdf` na pasta Materiais
- Se já baixou antes, não baixa de novo (economiza tempo)
- Pode interromper com Ctrl+C e continuar depois: o script salva o progresso e pergunta se quer retomar
- Mostra progresso geral das aulas e barra ao vivo de cada vídeo (%, tempo e tamanho)
- Vídeos incompletos (`.part.mp4`) são refeitos; só arquivos prontos são pulados
- Cria log de tudo que faz pra você poder acompanhar

## Avisos

- Use só pra cursos que você comprou
- Alguns cursos são pesados, vai demorar
- Precisa de bastante espaço em disco

## Problemas?

Se não funcionar:
1. Confere se o FFMPEG tá instalado (`ffmpeg -version` no terminal)
2. Vê se o email/senha tá certo
3. Olha o arquivo `log.txt` pra ver o erro

---

Projeto educacional. Use com responsabilidade.
