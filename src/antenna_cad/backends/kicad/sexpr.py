"""Minimal S-expression writer for KiCad files.

Write-only by design: the compiler emits a controlled subset of the board format and
never parses KiCad files back, which is what keeps the format-version risk contained
(see the project plan). Expressions are plain nested lists; atoms are strings, ints,
floats, or ``Sym`` for unquoted tokens.
"""

from __future__ import annotations


class Sym(str):
    """An unquoted symbol token, e.g. ``smd`` or ``yes`` (plain str subclass)."""

    __slots__ = ()


SExpr = Sym | str | int | float | list["SExpr"]


def fmt_mm(value: float) -> Sym:
    """Format a millimeter coordinate the way KiCad does: up to 6 decimals, trimmed.

    Examples
    --------
    >>> from antenna_cad.backends.kicad.sexpr import fmt_mm
    >>> str(fmt_mm(1.5)), str(fmt_mm(2.0)), str(fmt_mm(-0.0))
    ('1.5', '2', '0')
    """
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return Sym(text)


def _atom(value: SExpr) -> str:
    if isinstance(value, Sym):
        return str(value)
    if isinstance(value, bool):
        raise TypeError("write booleans as Sym('yes')/Sym('no')")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(fmt_mm(value))
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise TypeError(f"cannot serialize {type(value).__name__} in an S-expression")


def dumps(expr: SExpr, indent: int = 0) -> str:
    """Serialize an expression tree to KiCad-style indented text."""
    pad = "\t" * indent
    if not isinstance(expr, list):
        return pad + _atom(expr)
    if not expr:
        raise ValueError("empty S-expression list")
    head = expr[0]
    if not isinstance(head, Sym | str) or (isinstance(head, str) and not head):
        raise ValueError(f"S-expression head must be a nonempty token, got {head!r}")
    parts = [str(head)]
    children: list[str] = []
    inline = True
    for item in expr[1:]:
        if isinstance(item, list) and any(isinstance(sub, list) for sub in item):
            inline = False
    for item in expr[1:]:
        if inline:
            parts.append(dumps(item, 0).lstrip("\t") if isinstance(item, list) else _atom(item))
        else:
            children.append(dumps(item, indent + 1))
    if inline:
        return pad + "(" + " ".join(parts) + ")"
    return pad + "(" + str(head) + "\n" + "\n".join(children) + "\n" + pad + ")"
