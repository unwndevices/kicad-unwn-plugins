"""Minimal KiCad-flavoured S-expression model, serialiser, and parser.

KiCad files (`.kicad_mod`, `.kicad_sym`, `.kicad_pcb`) are S-expressions. We model
a node as a Python ``list`` whose first element is the head token, followed by
child atoms and/or nested nodes.

Atom encoding (chosen so a built tree serialises exactly like KiCad's own output):

* :class:`Sym`   -> a bare, unquoted token (e.g. ``smd``, ``yes``, ``custom``)
* ``str``        -> a double-quoted string (e.g. layer names like ``"F.Cu"``)
* ``bool``       -> bare ``yes`` / ``no``
* ``int``        -> bare integer
* ``float``      -> bare decimal with trailing zeros trimmed

Formatting mirrors KiCad: tab indentation, leading atoms kept on the head line,
and one nested node per line. :func:`loads` is the inverse and preserves bare vs.
quoted tokens, so ``dumps(loads(text)) == text`` for any text we emit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

__all__ = ["Sym", "dumps", "loads", "head", "children", "find", "find_all"]

INDENT = "\t"


@dataclass(frozen=True)
class Sym:
    """A bare (unquoted) S-expression token."""

    name: str


Atom = Union[Sym, str, int, float, bool]
Node = Union[Atom, list]


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #
def _fmt_number(x: Union[int, float]) -> str:
    if isinstance(x, bool):  # bool is a subclass of int — handle first
        return "yes" if x else "no"
    if isinstance(x, int):
        return str(x)
    if x == int(x):
        return str(int(x))
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _atom(a: Atom) -> str:
    if isinstance(a, Sym):
        return a.name
    if isinstance(a, bool):
        return "yes" if a else "no"
    if isinstance(a, (int, float)):
        return _fmt_number(a)
    if isinstance(a, str):
        return _quote(a)
    raise TypeError(f"unsupported atom: {a!r}")


def _head_token(token: Union[Sym, str]) -> str:
    return token.name if isinstance(token, Sym) else str(token)


def dumps(node: Node, indent: int = 0) -> str:
    """Serialise *node* to KiCad-style S-expression text (no trailing newline)."""
    pad = INDENT * indent
    if not isinstance(node, list):
        return pad + _atom(node)
    if not node:
        raise ValueError("cannot serialise an empty node")

    head_str = _head_token(node[0])
    kids = node[1:]

    if not any(isinstance(c, list) for c in kids):
        # No nested nodes -> single line.
        return pad + "(" + " ".join([head_str, *(_atom(c) for c in kids)]) + ")"

    # Leading atoms stay on the head line; nested nodes each get their own line.
    lead: list[str] = []
    i = 0
    while i < len(kids) and not isinstance(kids[i], list):
        lead.append(_atom(kids[i]))
        i += 1

    lines = [pad + "(" + " ".join([head_str, *lead])]
    for c in kids[i:]:
        if isinstance(c, list):
            lines.append(dumps(c, indent + 1))
        else:
            lines.append(INDENT * (indent + 1) + _atom(c))
    lines.append(pad + ")")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Parsing (inverse of dumps; preserves bare vs. quoted tokens)
# --------------------------------------------------------------------------- #
def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "(":
            tokens.append(("lpar", ""))
            i += 1
        elif c == ")":
            tokens.append(("rpar", ""))
            i += 1
        elif c == '"':
            i += 1
            buf: list[str] = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            i += 1  # consume closing quote
            tokens.append(("str", "".join(buf)))
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            tokens.append(("bare", text[i:j]))
            i = j
    return tokens


def loads(text: str) -> Node:
    """Parse S-expression *text* into a node tree (the inverse of :func:`dumps`)."""
    tokens = _tokenize(text)
    pos = 0

    def parse() -> Node:
        nonlocal pos
        kind, value = tokens[pos]
        if kind == "lpar":
            pos += 1
            node: list = []
            while tokens[pos][0] != "rpar":
                node.append(parse())
            pos += 1  # consume rpar
            return node
        pos += 1
        return value if kind == "str" else Sym(value)

    if not tokens:
        raise ValueError("empty input")
    return parse()


# --------------------------------------------------------------------------- #
# Small query helpers
# --------------------------------------------------------------------------- #
def head(node: Node):
    """Return the head token name of *node*, or ``None`` if it is an atom."""
    if isinstance(node, list) and node:
        return _head_token(node[0])
    return None


def children(node: Node) -> list:
    return node[1:] if isinstance(node, list) else []


def find(node: Node, name: str):
    """Return the first child node whose head is *name*, else ``None``."""
    for c in children(node):
        if isinstance(c, list) and head(c) == name:
            return c
    return None


def find_all(node: Node, name: str) -> list:
    """Return all child nodes whose head is *name*."""
    return [c for c in children(node) if isinstance(c, list) and head(c) == name]
