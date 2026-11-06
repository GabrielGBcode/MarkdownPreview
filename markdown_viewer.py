import math
import re

import sublime
import sublime_plugin

from .render import interp, render, render_html

SETTINGS = "MarkdownViewerV2.sublime-settings"
SCHEME = "Packages/%s/Neon.sublime-color-scheme" % __package__
ONE_COL = {"cols": [0, 1], "rows": [0, 1], "cells": [[0, 0, 1, 1]]}
TWO_COL = {"cols": [0, 0.5, 1], "rows": [0, 1], "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]}
POLL_MS = 100
PREVIEW_SETTINGS = {
    "mdv2_preview": True, "color_scheme": SCHEME, "word_wrap": True, "wrap_width": 0, "gutter": False,
    "line_numbers": False, "highlight_line": False, "draw_indent_guides": False, "scroll_past_end": False,
    "auto_indent": False, "rulers": [], "fold_buttons": False, "spell_check": False, "draw_white_space": "none",
}


class _P:
    """Prévia de uma view: aba somente leitura com um phantom HTML por bloco do documento."""

    def __init__(self, src, pv):
        self.src, self.pv = src, pv
        self.ps = sublime.PhantomSet(pv, "mdv2")
        self.data, self.n = None, 0
        self.e, self.p, self.last = None, 0, "e"  # topo do editor (linha), topo da prévia (px), quem rolou por último
        self.axs, self.ays, self.ext = [0, 1], [0, 1], None  # âncoras linha-do-editor <-> pixel-da-prévia

    def nav(self, href):
        if href.startswith("c:"):
            sublime.set_clipboard(self.data.copies[int(href[2:])])
            sublime.status_message("Copiado")
        elif href.startswith(("http://", "https://", "mailto:")):
            sublime.run_command("open_url", {"url": href})


_prev = {}  # id da view de origem -> _P
_src_of = {}  # id da view da prévia -> _P
_ticks = {}  # id da view -> contador do debounce
_auto = set()  # ids de views que já tiveram abertura automática
_wins = set()  # ids de janelas em que o plugin usou a coluna da direita
_busy = set()  # ids de janelas montando a prévia (a coluna nova ainda está vazia)


def is_md(view):
    return view.match_selector(0, "text.html.markdown")


def _state(view):
    st = _prev.get(view.id())
    if st and st.pv.window() is None:  # aba da prévia já fechada
        _prev.pop(view.id(), None)
        _src_of.pop(st.pv.id(), None)
        return None
    return st


def _name(view):
    return "Preview: " + (view.name() or (view.file_name() or "untitled").replace("\\", "/").split("/")[-1])


def _src(view):
    return view.substr(sublime.Region(0, view.size()))


def _cols(pv):
    """Largura útil da prévia em caracteres: tabelas e o 'copiar' se ajustam a ela."""
    # shortcut: o recuo do HTML (body + painel) foi medido na prática, ~11,5x o tamanho da fonte; ajustar se a grade quebrar
    pad = 11.5 * pv.settings().get("font_size", 12)
    return max(40, int((pv.viewport_extent()[0] - pad) / (pv.em_width() or 8)) - 2)


def _y(v, row):
    return v.text_to_layout(v.text_point(row, 0))[1]


def _frow(v):
    """Linha do topo da janela, fracionária (a fração vem da posição dentro da linha, mesmo com quebra)."""
    y = v.viewport_position()[1]
    r = v.rowcol(v.layout_to_text((0, y)))[0]
    y0, y1 = _y(v, r), _y(v, r + 1)
    return r + (min(1.0, max(0.0, (y - y0) / (y1 - y0))) if y1 > y0 else 0.0)


def _set_frow(v, row):
    r = int(math.floor(max(0, row)))
    y0, y1 = _y(v, r), _y(v, r + 1)
    v.set_viewport_position((0, y0 + (row - r) * (y1 - y0)), False)


def _anchors(st):
    """Recalcula os pixels dos títulos quando a altura da prévia muda (o layout dos phantoms é assíncrono)."""
    h = st.pv.layout_extent()[1]
    if h == st.ext:
        return False
    d, off = st.data, st.pv.line_height()  # o phantom fica logo abaixo da linha vazia do bloco
    xs, ys = [0], [0.0]
    for sx, pr in zip(d.src_heads, d.prev_heads):
        y = _y(st.pv, pr) + off
        if sx > xs[-1] and y > ys[-1]:
            xs.append(sx)
            ys.append(y)
    if d.src_total > xs[-1] and h > ys[-1]:
        xs.append(d.src_total)
        ys.append(h)
    st.axs, st.ays = (xs, ys) if len(xs) > 1 else ([0, 1], [0, 1])
    st.ext = h
    return True


def _go_prev(st, e):
    st.last = "e"
    st.pv.set_viewport_position((0, interp(st.axs, st.ays, e)), False)
    st.e, st.p = e, st.pv.viewport_position()[1]


def _go_src(st, py):
    st.last = "p"
    _set_frow(st.src, interp(st.ays, st.axs, py))
    st.p, st.e = py, _frow(st.src)


def _apply(st, data):
    st.data = data
    n = max(1, len(data.blocks))
    if st.n != n:  # uma linha vazia por bloco: o phantom do bloco i fica na linha i
        st.pv.run_command("markdown_viewer_v2_set_text", {"text": "\n" * n})
        st.n = n
    st.ps.update([sublime.Phantom(sublime.Region(i, i), h, sublime.LAYOUT_BLOCK, st.nav)
                  for i, h in enumerate(data.blocks)])
    st.ext, st.e = None, None  # força recalcular âncoras e ressincronizar no próximo tick


def _tick(st):
    if _prev.get(st.src.id()) is not st or st.pv.window() is None or st.src.window() is None:
        return
    if abs(_cols(st.pv) - st.data.cols) >= 4:  # janela redimensionada (ou ainda sem layout na abertura)
        _apply(st, render_html(_src(st.src), _cols(st.pv)))
    if _anchors(st) and st.last == "e":
        st.e = None
    e, py = _frow(st.src), st.pv.viewport_position()[1]
    if st.e is None or abs(e - st.e) > 0.02:  # rolou o editor: a prévia acompanha
        _go_prev(st, e)
    elif abs(py - st.p) > 1:  # rolou a prévia: o editor acompanha
        _go_src(st, py)
    sublime.set_timeout(lambda: _tick(st), POLL_MS)


def _collapse(w):
    # volta a tela única quando a coluna da direita fica vazia
    if w.id() in _wins and w.id() not in _busy and w.num_groups() == 2 and not w.sheets_in_group(1):
        _wins.discard(w.id())
        w.set_layout(ONE_COL)


def _is_preview(v):
    return bool(v.settings().get("mdv2_preview"))


# shortcut: fecha qualquer aba com a marca da prévia que não seja nossa (sobra da sessão anterior)
def _drop_orphans(w):
    if w.id() in _busy:
        return False
    mine = {st.pv.id() for st in _prev.values()}
    orphans = [v for v in w.views() if v.id() not in mine and _is_preview(v)]
    for v in orphans:
        v.set_scratch(True)
        v.close()
    return bool(orphans)


def open_preview(view):
    w = view.window()
    if not w or _state(view):
        return
    _drop_orphans(w)
    _wins.add(w.id())
    _busy.add(w.id())
    if w.num_groups() < 2:
        w.set_layout(TWO_COL)
    sublime.set_timeout(lambda: _place(view), 50)  # o novo grupo só existe depois do layout


def _place(view):
    w = view.window()
    try:
        if not w or _state(view):
            return
        last = w.num_groups() - 1
        if w.get_view_index(view)[0] == last:  # prévia sempre na direita: arquivo vai para a esquerda
            w.set_view_index(view, 0, len(w.views_in_group(0)))
        pv = w.new_file()
        pv.set_scratch(True)
        pv.set_name(_name(view))
        for k, v in PREVIEW_SETTINGS.items():
            pv.settings().set(k, v)
        w.set_view_index(pv, last, 0)
        st = _prev[view.id()] = _src_of[pv.id()] = _P(view, pv)
        _apply(st, render_html(_src(view), _cols(pv)))
        w.focus_view(view)
        _tick(st)
    finally:
        if w:
            _busy.discard(w.id())


def close_preview(view):
    st = _prev.pop(view.id(), None)
    if not st:
        return
    _src_of.pop(st.pv.id(), None)
    w = st.pv.window()
    st.pv.close()
    if w:
        sublime.set_timeout(lambda: _collapse(w), 50)


class MarkdownViewerV2SetTextCommand(sublime_plugin.TextCommand):
    def run(self, edit, text):
        self.view.set_read_only(False)
        self.view.replace(edit, sublime.Region(0, self.view.size()), text)
        self.view.set_read_only(True)


class MarkdownViewerV2ToggleCommand(sublime_plugin.TextCommand):
    def is_enabled(self):
        return is_md(self.view) or self.view.id() in _src_of

    def run(self, edit):
        st = _src_of.get(self.view.id())
        if st:  # Alt+M dentro da prévia também fecha
            close_preview(st.src)
        elif _state(self.view):
            close_preview(self.view)
        else:
            open_preview(self.view)


class MarkdownViewerV2CopyCommand(sublime_plugin.TextCommand):
    def is_enabled(self):
        return is_md(self.view) or self.view.id() in _src_of

    def run(self, edit):
        st = _src_of.get(self.view.id())
        text = render(_src(st.src if st else self.view)).text
        sublime.set_clipboard(re.sub(r"(?m)^[■▪›] ", "", text))  # tira os marcadores de título
        sublime.status_message("Texto da prévia copiado")


class MarkdownViewerV2Listener(sublime_plugin.EventListener):
    def on_activated_async(self, view):
        w = view.window()
        if not w:
            return
        # prévia restaurada de uma sessão anterior (o Sublime não avisa o plugin ao sair do app)
        if _drop_orphans(w):
            _wins.add(w.id())
        _collapse(w)
        if view.id() in _auto or not is_md(view):
            return
        _auto.add(view.id())  # uma vez por arquivo: fechar a prévia não a reabre
        if sublime.load_settings(SETTINGS).get("auto_open", True):
            open_preview(view)

    def on_modified_async(self, view):
        st = _state(view)
        if not st:
            return
        tick = _ticks[view.id()] = _ticks.get(view.id(), 0) + 1
        delay = sublime.load_settings(SETTINGS).get("delay_ms", 300)

        def update():
            if _ticks.get(view.id()) != tick or _prev.get(view.id()) is not st:
                return
            data = render_html(_src(view), _cols(st.pv))
            sublime.set_timeout(lambda: _prev.get(view.id()) is st and _apply(st, data), 0)

        sublime.set_timeout_async(update, delay)

    def on_pre_close_window(self, window):
        for v in window.views():
            close_preview(v)

    def on_pre_close(self, view):
        st = _src_of.pop(view.id(), None)
        if st:  # usuário fechou a aba da prévia pelo X
            _prev.pop(st.src.id(), None)
            w = view.window()
            if w:
                sublime.set_timeout(lambda: _collapse(w), 50)
        else:
            close_preview(view)
        _ticks.pop(view.id(), None)
        _auto.discard(view.id())
