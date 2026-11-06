import bisect
import html
import os
import re
import sys
import textwrap
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import markdown
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

TABLE_MAX = 80  # tabela mais larga que isso vira lista (colunas alinhadas quebrariam na janela)
BR = "\x00"
H = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCKS = H | {"p", "ul", "ol", "pre", "blockquote", "table", "hr", "div"}

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEAD = re.compile(r"^#{1,6}")  # Python-Markdown não exige espaço depois do #
LIST = re.compile(r"^ {0,3}([-*+]|\d{1,9}[.)])\s+\S")
STASH = re.compile(r"\x02wzxhzdk:(\d+)\x03")
ESC = re.compile(r"\x02(\d+)\x03")


class _Capture(Treeprocessor):
    root = None

    def run(self, root):
        self.root = root


class _Ext(Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(_Capture(md), "capture", 15)  # depois do inline (20), antes do prettify (10)


class Result:
    def __init__(self, text, src_heads, prev_heads, src_total, prev_total):
        xs, ys = [0], [0]
        if len(src_heads) == len(prev_heads):  # shortcut: título setext (===) quebra o pareamento; cai no proporcional
            for x, y in zip(src_heads, prev_heads):
                if x > xs[-1] and y > ys[-1]:
                    xs.append(x)
                    ys.append(y)
        if src_total > xs[-1] and prev_total > ys[-1]:
            xs.append(src_total)
            ys.append(prev_total)
        if len(xs) < 2:
            xs, ys = [0, 1], [0, 1]
        self.text, self.xs, self.ys = text, xs, ys

    def to_prev(self, row):
        return interp(self.xs, self.ys, row)

    def to_src(self, row):
        return interp(self.ys, self.xs, row)


def interp(xs, ys, x):
    # interpolação linear por partes; fora do intervalo, extrapola o último trecho
    i = max(0, min(bisect.bisect_right(xs, x) - 1, len(xs) - 2))
    return ys[i] + (x - xs[i]) * (ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i])


def _clean(md, s):
    def raw(m):
        h = md.htmlStash.rawHtmlBlocks[int(m.group(1))]
        if re.match(r"<br\s*/?>", h, re.I):
            return BR
        return html.unescape(re.sub(r"<[^>]*>", "", h))

    return ESC.sub(lambda m: chr(int(m.group(1))), STASH.sub(raw, s))


def _code(md, c):
    # o Python-Markdown já escapou &, < e > dentro de código; volta ao texto cru
    return html.unescape(_clean(md, "".join(c.itertext())))


def _node(md, c):
    t = c.tag
    if t == "br":
        return BR
    if t == "code":
        return "`" + _code(md, c) + "`"
    if t == "a":
        txt, href = _inline(md, c), c.get("href") or ""
        return txt if not href or txt == href or href.startswith("#") else "%s (%s)" % (txt, href)
    if t == "img":
        return c.get("alt") or ""
    return _inline(md, c)


def _inline(md, el):
    s = _clean(md, el.text or "")
    for c in el:
        s += _node(md, c) + _clean(md, c.tail or "")
    return s


def _para(md, el):
    s = re.sub(r"[ \t]*\n[ \t]*", " ", _inline(md, el))
    return re.sub(r"[ \t]{2,}", " ", s).strip().replace(BR, "\n")


def _dw(s):
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def _pad(s, w):
    return s + " " * (w - _dw(s))


def _table(md, el, pad):
    rows = [[" ".join(_inline(md, c).replace(BR, " ").split()) for c in tr] for tr in el.iter("tr")]
    n = max(map(len, rows))
    for r in rows:
        r += [""] * (n - len(r))
    head, body = rows[0], rows[1:]
    w = [max(_dw(r[i]) for r in rows) for i in range(n)]
    if sum(w) + 3 * (n - 1) <= TABLE_MAX:
        line = lambda r: pad + " │ ".join(_pad(c, w[i]) for i, c in enumerate(r)).rstrip()
        return [line(head), pad + "─┼─".join("─" * x for x in w)] + [line(r) for r in body]
    out = []
    for r in body:
        out += [pad + "• " + r[0]] + [pad + "    %s: %s" % (head[i], r[i]) for i in range(1, n) if r[i]] + [""]
    return out[:-1]


def _blocks(md, el, pad):
    out = []
    for c in el:
        ls = _block(md, c, pad)
        if ls:
            out += ([""] if out else []) + ls
    return out


def _list(md, el, pad):
    start = int(el.get("start", 1)) if el.tag == "ol" else 0
    out = []
    for i, li in enumerate(el.findall("li")):
        mark = "%d. " % (start + i) if el.tag == "ol" else "• "
        head, rest = _clean(md, li.text or ""), []
        for c in li:
            if c.tag in BLOCKS:
                rest.append(c)
            else:
                head += _node(md, c) + _clean(md, c.tail or "")
        head = re.sub(r"[ \t]{2,}", " ", re.sub(r"[ \t]*\n[ \t]*", " ", head)).strip().replace(BR, "\n")
        if not head and rest and rest[0].tag == "p":
            head = _para(md, rest.pop(0))
        first, *more = head.split("\n")
        out.append(pad + mark + first)
        out += [pad + " " * len(mark) + m for m in more]
        for c in rest:
            out += _block(md, c, pad + " " * len(mark))
    return out


def _block(md, el, pad):
    t = el.tag
    if t in H:
        return [pad + {"h1": "■", "h2": "▪"}.get(t, "›") + " " + _para(md, el)]
    if t == "p":
        return [pad + l for l in _para(md, el).split("\n")]
    if t in ("ul", "ol"):
        return _list(md, el, pad)
    if t == "pre":
        return [pad + "│ " + l for l in _code(md, el).rstrip("\n").split("\n")]
    if t == "blockquote":
        return [pad + ("┃ " + l if l else "┃") for l in _blocks(md, el, "")]
    if t == "hr":
        return [pad + "─" * 40]
    if t == "table":
        return _table(md, el, pad)
    return [pad + l for l in _para(md, el).split("\n") if l.strip()]


def _fix(lines):
    # o Python-Markdown exige linha em branco antes de tabela e de lista; o editor costuma omitir
    out = []
    for l in lines:
        if "|" in l and "---" in l and not l.strip(" \t|:-") and len(out) > 1 \
                and "|" in out[-1] and out[-2].strip() and "|" not in out[-2]:
            out.insert(len(out) - 1, "")
        elif LIST.match(l) and out and out[-1].strip() and not LIST.match(out[-1]) \
                and not out[-1].startswith((" ", "\t")):
            out.append("")
        out.append(l)
    return out


def _segments(lines):
    segs, cur, start, fence = [], [], 0, None
    for i, l in enumerate(lines):
        m = FENCE.match(l)
        if fence is None and m:
            segs.append(("md", cur, start))
            cur, start, fence = [], i + 1, m.group(1)
        elif fence and re.match(r"^ {0,3}%s{%d,}\s*$" % (re.escape(fence[0]), len(fence)), l):
            segs.append(("code", cur, start))
            cur, start, fence = [], i + 1, None
        else:
            cur.append(l)
    segs.append(("code" if fence else "md", cur, start))
    return segs


def render(src):
    lines = src.split("\n")
    out, src_heads, prev_heads = [], [], []
    for kind, seg, start in _segments(lines):
        if not seg:
            continue
        if kind == "code":
            out += ([""] if out and out[-1] else []) + ["│ " + l for l in seg]
            continue
        src_heads += [start + j for j, l in enumerate(seg) if HEAD.match(l)]
        md = markdown.Markdown(extensions=["markdown.extensions.tables", "markdown.extensions.sane_lists", _Ext()])
        md.convert("\n".join(_fix(seg)))
        root = md.treeprocessors["capture"].root
        for c in root:
            ls = _block(md, c, "")
            if not ls:
                continue
            if out and out[-1]:
                out.append("")
            if c.tag in H:
                prev_heads.append(len(out))
            out += ls
    return Result("\n".join(out), src_heads, prev_heads, len(lines), len(out))


# ---------- HTML para phantoms (minihtml: sem <table>, CSS limitado) ----------

# paleta "neon": mesma do Neon.sublime-color-scheme
CSS = """
body{background-color:#0d0f14;color:#e6e6e6;padding:0.1rem 1.4rem}
a{color:#40c4ff}
b{color:#ffd740}
i{color:#b388ff}
code{color:#ffd740;background-color:#171b24}
.h1{color:#00e5ff;font-size:1.9rem;font-weight:bold;padding-top:0.5rem}
.h2{color:#ff4081;font-size:1.45rem;font-weight:bold;padding-top:0.4rem}
.h3{color:#c6ff00;font-size:1.2rem;font-weight:bold;padding-top:0.3rem}
.h4{color:#ffd740;font-size:1.05rem;font-weight:bold;padding-top:0.2rem}
.p{padding:0.15rem 0}
.li{padding:0.08rem 0}
.bl{color:#ff4081;font-weight:bold}
.q{background-color:#1c1730;color:#d9c8ff;padding:0.35rem 1rem;margin:0.2rem 0}
.c{background-color:#171b24;padding:0.15rem 1rem 0.45rem;margin:0.2rem 0}
.ch{color:#7d8590;font-size:0.8rem;padding-bottom:0.2rem}
.tb{margin:0.3rem 0;border:1px solid #2a3140}
.tr,.trh{font-size:0.1rem}
.trh{background-color:#1c2230;color:#00e5ff;font-weight:bold}
.td{display:inline-block;font-size:1rem;padding:0.3rem 0.5rem;border-bottom:1px solid #2a3140}
.tl{border-left:1px solid #2a3140}
pre{color:#ffd740}
.hr{color:#2a3140}
"""


def _esc(s):
    return html.escape(s, quote=False)


def _wrap(h):
    return '<body id="mv"><style>%s</style>%s</body>' % (CSS, h)


def _norm(s):
    return " ".join(s.split()).replace(BR, "<br>")


def _inode(md, c):
    t = c.tag
    if t == "br":
        return BR
    if t == "code":
        return "<code>" + _esc(_code(md, c)) + "</code>"
    if t in ("strong", "b"):
        return "<b>" + _ihtml(md, c) + "</b>"
    if t in ("em", "i"):
        return "<i>" + _ihtml(md, c) + "</i>"
    if t == "a":
        href = (c.get("href") or "").strip()
        # só http(s)/mailto: um href "subl:..." num documento rodaria comandos do Sublime ao clicar
        if href.lower().startswith(("http://", "https://", "mailto:")):
            return '<a href="%s">%s</a>' % (html.escape(href), _ihtml(md, c))
        return _ihtml(md, c)
    if t == "img":
        return _esc(c.get("alt") or "")
    return _ihtml(md, c)


def _ihtml(md, el):
    s = _esc(_clean(md, el.text or ""))
    for c in el:
        s += _inode(md, c) + _esc(_clean(md, c.tail or ""))
    return s


def _panel(label, inner, copies, text, cols):
    copies.append(text)
    # shortcut: sem float/flex no minihtml, o "copiar" vai para a direita com &nbsp; calculados pela largura estimada (cols)
    gap = max(1, int(cols / 0.8) - len(label) - 6)  # 0.8 = font-size do cabeçalho
    return '<div class="c"><div class="ch">%s%s<a href="c:%d">copiar</a></div>%s</div>' % (
        label, "&nbsp;" * gap, len(copies) - 1, inner)


def code_html(lines, copies, cols):
    return _panel("código", "<pre>%s</pre>" % _esc("\n".join(lines)), copies, "\n".join(lines), cols)


def _cols_of(md):
    return getattr(md, "mv_cols", 90)


def _grid(rows, cols):
    """Tabela com bordas: colunas encolhem até caber em `cols` e o texto de cada célula quebra em várias linhas."""
    n = len(rows[0])
    w = [max(_dw(r[i]) for r in rows) for i in range(n)]
    avail = cols - (3 * n + 1)
    while sum(w) > avail and max(w) > 8:
        w[w.index(max(w))] -= 1
    bar = lambda l, m, r: l + m.join("─" * (x + 2) for x in w) + r
    out, nh = [bar("┌", "┬", "┐")], 0
    for k, row in enumerate(rows):
        cells = [textwrap.wrap(c, max(1, w[i]), break_long_words=True, break_on_hyphens=False) or [""]
                 for i, c in enumerate(row)]
        for j in range(max(map(len, cells))):
            out.append("│ " + " │ ".join(_pad(c[j] if j < len(c) else "", w[i]) for i, c in enumerate(cells)) + " │")
        if k == 0:
            nh = len(out) - 1
        out.append(bar("├", "┼", "┤") if k < len(rows) - 1 else bar("└", "┴", "┘"))
    return out, nh


CW = 0.69  # rem reservado por caractere: fonte monoespaçada ~0.6 + 15% de folga, para a célula nunca alargar em qualquer zoom
COMPACT = 14  # colunas com texto até esse tamanho (chars) nunca encolhem
CELL_PAD = 1.1  # padding horizontal + borda da célula, em rem


def _widths(texts, avail):
    """Largura (chars) de cada coluna: natural se couber; senão colunas compactas ficam inteiras e as de texto dividem o resto."""
    nat = [min(max(len(t) for t in col), 200) for col in texts]
    mn = [min(max((len(w) for t in col for w in t.split()), default=1), 8) for col in texts]
    if sum(nat) <= avail:
        return nat
    w = [n if n <= COMPACT else None for n in nat]
    rest = avail - sum(x for x in w if x is not None)
    todo = sorted((i for i, x in enumerate(w) if x is None), key=lambda i: nat[i])
    if not todo or rest < sum(mn[i] for i in todo):
        return [max(3, int(m * avail / sum(mn))) for m in mn]
    for j, i in enumerate(todo):
        w[i] = int(min(nat[i], max(mn[i], rest / (len(todo) - j))))
        rest -= w[i]
    return w


def _toks(md, el, st=""):
    """Texto inline como lista de (palavra, estilo): o texto é quebrado por mim, em chars, e não pelo minihtml."""
    out = []
    def add(s, st):
        out.extend((w, st) for w in html.unescape(_clean(md, s)).replace(BR, " ").split())
    add(el.text or "", st)
    for c in el:
        t = c.tag
        if t == "code":
            add("".join(c.itertext()), "code")
        elif t in ("strong", "b"):
            out += _toks(md, c, "b")
        elif t in ("em", "i"):
            out += _toks(md, c, "i")
        elif t == "img":
            add(c.get("alt") or "", st)
        else:
            out += _toks(md, c, st)
        add(c.tail or "", st)
    return out


def _wrapw(words, n):
    lines, cur, size = [], [], 0
    for w, st in words:
        while len(w) > n:  # palavra maior que a coluna: quebra forçada
            if cur:
                lines.append(cur)
                cur, size = [], 0
            lines.append([(w[:n], st)])
            w = w[n:]
        if cur and size + 1 + len(w) > n:
            lines.append(cur)
            cur, size = [], 0
        size += len(w) + (1 if cur else 0)
        cur.append((w, st))
    return lines + [cur] if cur else lines or [[]]


TAG = {"b": "b", "i": "i", "code": "code"}


def _line_html(line):
    return " ".join("<%s>%s</%s>" % (TAG[st], _esc(w), TAG[st]) if st else _esc(w) for w, st in line) or "&nbsp;"


def _htable(md, el, copies):
    trs = list(el.iter("tr"))
    n = max(len(tr) for tr in trs)
    toks = [[_toks(md, c) for c in tr] + [[]] * (n - len(tr)) for tr in trs]
    texts = [[" ".join(w for w, _ in c) for c in r] for r in toks]
    avail = _cols_of(md) * 0.6 * 0.9 / CW - n * CELL_PAD / CW  # 0.6 = em_width/font_size; 0.9 = folga na largura da linha
    w = _widths([[r[i] for r in texts] for i in range(n)], max(avail, 3 * n))
    out = []
    for k, row in enumerate(toks):
        cells = [_wrapw(c, w[i]) for i, c in enumerate(row)]
        top = max(map(len, cells))
        tds = ""
        for i, ls in enumerate(cells):
            lead = (top - len(ls)) // 2
            # +1 linha em branco em cima e embaixo: o padding vertical do minihtml não separa o texto das bordas
            body = ["&nbsp;"] * (lead + 1) + [_line_html(l) for l in ls] + ["&nbsp;"] * (top - len(ls) - lead + 1)
            tds += '<div class="td%s" style="width:%.2frem">%s</div>' % (" tl" if i else "", w[i] * CW, "<br>".join(body))
        out.append('<div class="%s">%s</div>' % ("trh" if k == 0 else "tr", tds))
    return '<div class="tb">%s</div>' % "".join(out)



def _hlist(md, el, depth, copies):
    start = int(el.get("start", 1)) if el.tag == "ol" else 0
    out = []
    for i, li in enumerate(el.findall("li")):
        mark = "%d." % (start + i) if el.tag == "ol" else "•"
        head, rest = _esc(_clean(md, li.text or "")), []
        for c in li:
            if c.tag in BLOCKS:
                rest.append(c)
            else:
                head += _inode(md, c) + _esc(_clean(md, c.tail or ""))
        head = _norm(head)
        if not head and rest and rest[0].tag == "p":
            head = _norm(_ihtml(md, rest.pop(0)))
        out.append('<div class="li" style="margin-left:%.1frem"><span class="bl">%s</span>&nbsp;&nbsp;%s</div>'
                   % (depth * 1.5, mark, head))
        for c in rest:
            if c.tag in ("ul", "ol"):
                out.append(_hlist(md, c, depth + 1, copies))
            else:
                out.append('<div style="margin-left:%.1frem">%s</div>' % ((depth + 1) * 1.5, _hblock(md, c, copies)))
    return "".join(out)


def _hblock(md, el, copies):
    t = el.tag
    if t in H:
        return '<div class="h%d">%s</div>' % (min(int(t[1]), 4), _norm(_ihtml(md, el)))
    if t == "p":
        return '<div class="p">%s</div>' % _norm(_ihtml(md, el))
    if t in ("ul", "ol"):
        return _hlist(md, el, 0, copies)
    if t == "pre":
        return code_html(_code(md, el).rstrip("\n").split("\n"), copies, _cols_of(md))
    if t == "blockquote":
        return '<div class="q">%s</div>' % "".join(_hblock(md, c, copies) for c in el)
    if t == "hr":
        return '<div class="hr">%s</div>' % ("─" * 60)
    if t == "table":
        return _htable(md, el, copies)
    return '<div class="p">%s</div>' % _norm(_ihtml(md, el)) if "".join(el.itertext()).strip() else ""


class HtmlResult:
    def __init__(self, blocks, prev_heads, src_heads, src_total, copies):
        self.blocks, self.copies, self.src_total = blocks, copies, src_total
        paired = len(src_heads) == len(prev_heads)  # shortcut: título setext (===) quebra o pareamento
        self.src_heads, self.prev_heads = (src_heads, prev_heads) if paired else ([], [])


def render_html(src, cols=90):
    lines = src.split("\n")
    blocks, src_heads, prev_heads, copies = [], [], [], []
    for kind, seg, start in _segments(lines):
        if not seg:
            continue
        if kind == "code":
            blocks.append(_wrap(code_html(seg, copies, cols)))
            continue
        src_heads += [start + j for j, l in enumerate(seg) if HEAD.match(l)]
        md = markdown.Markdown(extensions=["markdown.extensions.tables", "markdown.extensions.sane_lists", _Ext()])
        md.mv_cols = cols
        md.convert("\n".join(_fix(seg)))
        for c in md.treeprocessors["capture"].root:
            h = _hblock(md, c, copies)
            if not h:
                continue
            if c.tag in H:
                prev_heads.append(len(blocks))
            blocks.append(_wrap(h))
    res = HtmlResult(blocks, prev_heads, src_heads, len(lines), copies)
    res.cols = cols
    return res
