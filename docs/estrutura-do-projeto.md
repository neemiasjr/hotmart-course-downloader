# Estrutura do projeto

**Português** | [English](estrutura-do-projeto.en.md)

```
hotmark.py                 ponto de entrada (python hotmark.py)
iniciar.sh / .command / .bat
config_cursos.py           configuração do usuário
requirements.txt
src/hotmart_downloader/    código do programa
scripts/                   utilitários avulsos
tests/                     testes automatizados
docs/                      documentação
```

O `hotmark.py` da raiz só coloca `src/` no caminho de importação e chama
`hotmart_downloader.cli.main()`. Os scripts `iniciar.*` continuam rodando o
`hotmark.py`, então o jeito de usar não mudou.

## Módulos (`src/hotmart_downloader/`)

O fluxo começa em `cli.py`, que autentica (`auth.py`) e chama `listacursos` em
`curso.py`. Lá ficam as etapas do download: escolher o curso, definir o escopo,
montar a estrutura de aulas e processar cada aula.

| Módulo | Responsabilidade |
|---|---|
| `cli.py` | `main()`: login e mensagem ao interromper com Ctrl+C |
| `auth.py` | token Bearer do navegador ou e-mail/senha |
| `curso.py` | fluxo principal e processamento de cada aula |
| `selecao.py` | perguntas e parsing de qualidade, tópicos, aulas e vídeos |
| `estrutura.py` | metadados das aulas (vídeos, anexos, links) em paralelo |
| `api.py` | chamadas às APIs do Club, navegação, nome do curso e cache de páginas |
| `hls.py` | escolha da variante HLS e download de vídeo da Hotmart |
| `ffmpeg.py` | execução do ffmpeg com barra de progresso e detecção de travamento |
| `midia.py` | ffprobe, duração, correção de sincronia e de fluidez |
| `externos.py` | YouTube/Vimeo (youtube_dl) e PDFs do Google Drive |
| `materiais.py` | anexos, PDFs do Google Drive e links de cada aula |
| `verificacao.py` | decide se vídeo, anexo ou aula já estão completos na pasta |
| `caminhos.py` | caminhos de saída e arquivos `.part` |
| `nomes.py` | nomes fiéis ao site e o padrão antigo em slug |
| `migracao.py` | renomeia pastas e arquivos de versões anteriores |
| `progresso.py` | `.progress.json` para retomar downloads |
| `config.py` | leitura do `config_cursos.py` com valores padrão |
| `console.py` | log em arquivo e saída no terminal |

## Utilitários (`scripts/`)

Rodam a partir da raiz do projeto:

- `python scripts/corrigir_sync_pasta.py Cursos` corrige sincronia de áudio e
  fluidez de vídeos já baixados (`--dry-run` só lista).
- `python scripts/achatar_videos_modulo.py <pasta do módulo>` move vídeos de
  subpastas de aula (layout antigo) para a pasta do módulo.

## Testes

```bash
python -m unittest
```
