# Changelog

Todas as mudanças relevantes deste projeto são documentadas neste arquivo.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto adota o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [1.2.0] - 2026-10-21

### Corrigido

- Nome do curso capturado errado: era montado com o subdomínio do club e os
  nomes dos dois primeiros módulos (ex.: `frazao-e-vini-comece-por-aqui-se-organize-com-o-metodo-certo`
  em vez de `Cozinhar é bom demais!`) ([#1]). Agora o nome vem da API de
  compras da Hotmart, o mesmo exibido no site.

### Alterado

- Pastas e arquivos com nomes fiéis ao título original, com acentos,
  maiúsculas e espaços ([#1]):
  - curso: `Cursos/Cozinhar é bom demais!`
  - tópico: `1 - Comece por aqui` (antes `1_comece-por-aqui`)
  - vídeo: `8 - Yakissoba.mp4` (antes `8.yakissoba.mp4`); aulas com vários
    vídeos: `8 - Yakissoba (vídeo 2).mp4`
  - descrição, anexos e links: `8 - Yakissoba.html`,
    `8 - Yakissoba - apostila.pdf`, `8 - Yakissoba - links.txt`
- Só caracteres que o sistema de arquivos não aceita são trocados: `|`, `/`,
  `\` e `:` viram ` - `; `<`, `>`, `"`, `?` e `*` são removidos. Nomes
  reservados do Windows (`CON`, `NUL`...) são evitados e nomes muito longos
  são encurtados para 120 caracteres.

### Adicionado

- Migração automática: pastas e arquivos baixados por versões anteriores são
  renomeados para o novo padrão na próxima execução, sem baixar nada de novo.
- Opção `CURSOS_NOMES` em `config_cursos.py` para definir manualmente o nome
  da pasta de um curso (por subdomínio ou product ID).

## [1.1.2] - 2026-10-21

### Corrigido

- Download de vídeo HLS travava indefinidamente, sem erro no `log.txt`, quando a
  conexão com a CDN parava de enviar dados; era preciso usar Ctrl+C duas vezes e
  reiniciar a ferramenta ([#2]).
  - Detector de travamento nos modos com barra de progresso e paralelo: se nem o
    tempo do vídeo nem o arquivo `.part.mp4` avançarem por 180 s, o FFmpeg é
    encerrado.
  - Até 3 novas tentativas automáticas, cada uma com uma URL HLS assinada nova.
  - FFmpeg sempre executado com `-rw_timeout` (30 s),
    `-reconnect_on_network_error` e `-nostdin`.
  - Leitura do progresso em thread separada: um único Ctrl+C interrompe o
    download.
  - O `.part.mp4` incompleto agora é removido corretamente entre tentativas.

### Adicionado

- Constantes `FFMPEG_TIMEOUT_INATIVO`, `FFMPEG_RW_TIMEOUT_US` e
  `FFMPEG_MAX_TENTATIVAS_TRAVAMENTO` para ajustar os limites acima.
- Aviso no log quando um travamento é detectado, com o ponto do vídeo em que o
  download parou e o número da tentativa.

## [1.1.1] - 2026-10-12

### Corrigido

- Seleção de aulas específicas (ex.: `5:2`, `9,10`) era ignorada e o módulo
  inteiro era baixado; o formato `tópico:aula` agora é interpretado
  corretamente.

### Alterado

- Sintaxe de seleção de aulas documentada no `config_cursos.py` de exemplo.

## [1.1.0] - 2026-10-09

### Adicionado

- Script `corrigir_sync_pasta.py` para corrigir a sincronia de áudio/vídeo em
  lote, com log e barra de progresso.
- Script `achatar_videos_modulo.py` para achatar as pastas de aulas de um
  módulo.
- Retomada de downloads em lote a partir de onde parou.

### Alterado

- Escolha da variante HLS correta, respeitando a qualidade de vídeo
  preferida.
- Correção de fluidez após o download (timestamps irregulares do HLS que
  deixavam o movimento "robótico").

## [1.0.2] - 2026-10-09

### Corrigido

- Áudio adiantado em relação ao vídeo nos arquivos baixados.

## [1.0.1] - 2026-10-08

### Corrigido

- `config_cursos.py` adicionado ao `.gitignore` para não versionar
  configurações pessoais.

## [1.0.0] - 2026-10-08

### Adicionado

- Versão inicial: download de cursos da Hotmart pela API Club (consumer), com
  autenticação Bearer e download por escopo (módulos, tópicos e aulas).
- Baseado no gist original de @juvenal, com melhorias locais.

[#1]: https://github.com/neemiasjr/hotmart-course-downloader/issues/1
[#2]: https://github.com/neemiasjr/hotmart-course-downloader/issues/2
[1.2.0]: https://github.com/neemiasjr/hotmart-course-downloader/compare/v1.1.2...v1.2.0
[1.1.2]: https://github.com/neemiasjr/hotmart-course-downloader/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/neemiasjr/hotmart-course-downloader/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/neemiasjr/hotmart-course-downloader/compare/v1.0.2...v1.1.0
[1.0.2]: https://github.com/neemiasjr/hotmart-course-downloader/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/neemiasjr/hotmart-course-downloader/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/neemiasjr/hotmart-course-downloader/releases/tag/v1.0.0
