# Markdown Viewer V2

Prévia de Markdown em HTML escuro (paleta neon), ao lado do editor (Sublime Text 4).

## Instalar

Copie a pasta `MarkdownViewerV2` para `%APPDATA%\Sublime Text\Packages\`. Remova o `MarkdownViewer` (V1) dessa pasta: os dois usam o `Alt+M`.

## Uso

- Abrir um `.md` abre a prévia na direita. `Alt+M` (também dentro da prévia) abre/fecha.
- Rolar o editor rola a prévia, e rolar a prévia rola o editor (alinhado pelos títulos `#`).
- Copiar: link "copiar" em cada bloco de código/tabela, ou Ctrl+Shift+P → "Markdown Viewer: Copy Preview Text" (texto inteiro).
- Não dá para selecionar texto da prévia com o mouse (limite do Sublime com HTML).
- Fechar o arquivo ou a prévia volta para tela única.

## Arquivos

| Arquivo | Função |
|---|---|
| `markdown_viewer.py` | Plugin: aba da prévia (um phantom HTML por bloco), abertura/fechamento, atualização com atraso, sincronização de rolagem, copiar. |
| `render.py` | Markdown → blocos HTML (minihtml) e texto simples; mapa linha↔título para a rolagem. |
| `Neon.sublime-color-scheme` | Paleta neon, usada na prévia e disponível como esquema de cores do Sublime inteiro. |
| `vendor/markdown/` | Python-Markdown 3.7 embutido. |
| `Default.sublime-commands`, `Default (Windows).sublime-keymap` | Paleta de comandos e `Alt+M`. |
| `MarkdownViewerV2.sublime-settings` | `auto_open`, `delay_ms`. |
| `.python-version` | Força Python 3.8 no plugin host. |
