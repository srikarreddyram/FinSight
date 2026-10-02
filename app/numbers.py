"""Numbers are handled in Python, never by the LLM: parsing figures out of filing text, checking an
extracted figure really appears in its cited source, scaling units, doing the arithmetic, and
formatting results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SCALES = {"units": 1.0, "thousands": 1e3, "lakh": 1e5, "millions": 1e6, "crore": 1e7, "billions": 1e9}
SCALE_WORDS = {
    "units": "",
    "thousands": " thousand",
    "lakh": " lakh",
    "millions": " million",
    "crore": " crore",
    "billions": " billion",
}
CURRENCY_SYMBOLS = {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£", "JPY": "¥"}

# 1,234  1,23,456 (Indian grouping)  1234.5  (1,234)  -1,234  12.5%
_NUM = re.compile(r"(?<![\w.])\(?-?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\)?|(?<![\w.])\(?-?\d+(?:\.\d+)?\)?")


def _tokens(text: str) -> list[tuple[float, int]]:
    """(absolute value, decimals printed) for every number in a piece of filing text."""
    out = []
    for m in _NUM.finditer(text):
        tok = m.group(0).strip("()").replace(",", "").lstrip("-")
        try:
            out.append((abs(float(tok)), len(tok.split(".")[1]) if "." in tok else 0))
        except ValueError:
            continue
    return out


def numbers_in(text: str) -> list[float]:
    return [v for v, _ in _tokens(text)]


def appears_in(value: float, text: str) -> bool:
    """Is `value` (as the LLM transcribed it, before any scaling) printed in the source text?

    A match is within half a unit of the last digit the filing printed, so 1577 matches "1,577",
    32.765 matches "32.8" and 13.2 matches "13.2 %". Signs are ignored: filings print outflows as (1,577).
    """
    v = abs(value)
    return any(abs(n - v) <= 0.5 * 10 ** (-dec) + 1e-9 for n, dec in _tokens(text))


@dataclass
class Quantity:
    value: float  # as printed in the filing (already signed)
    unit: str = "currency"  # currency | percent | count | ratio | per_share | other
    currency: str = ""
    scale: str = "units"

    @property
    def base(self) -> float:
        return self.value * SCALES.get(self.scale, 1.0)


def fmt_number(x: float, decimals: int | None = None) -> str:
    """Thousands separators; by default keep the precision the value carries (max 2 decimals)."""
    if decimals is None:
        frac = f"{abs(x):.6f}".rstrip("0").split(".")[1]
        decimals = min(2, len(frac))
    s = f"{abs(x):,.{decimals}f}"
    if decimals and "." in s:
        s = s.rstrip("0").rstrip(".")
    return ("-" if x < 0 else "") + s


def fmt_quantity(q: Quantity) -> str:
    if q.unit == "percent":
        return f"{fmt_number(q.value, 2 if abs(q.value) < 100 else 1)}%"
    if q.unit == "ratio":
        return f"{fmt_number(q.value, 2)}x"
    sym = CURRENCY_SYMBOLS.get(q.currency.upper(), f"{q.currency} " if q.currency else "")
    sign = "-" if q.value < 0 else ""
    body = fmt_number(abs(q.value))
    if q.unit in ("currency", "per_share") and sym:
        return f"{sign}{sym}{body}{SCALE_WORDS.get(q.scale, '')}"
    return f"{sign}{body}{SCALE_WORDS.get(q.scale, '')}"


class CalcError(ValueError):
    pass


def _same_units(qs: list[Quantity]) -> None:
    kinds = {q.unit for q in qs}
    if len(kinds) > 1:
        raise CalcError(f"mixed units {sorted(kinds)}")
    cur = {q.currency.upper() for q in qs if q.currency}
    if len(cur) > 1:
        raise CalcError(f"mixed currencies {sorted(cur)}")


def _rescale(base: float, like: Quantity) -> Quantity:
    return Quantity(value=base / SCALES.get(like.scale, 1.0), unit=like.unit, currency=like.currency, scale=like.scale)


def calculate(op: str, inputs: list[Quantity], periods: int = 0, factor: float | None = None) -> Quantity:
    """Deterministic financial arithmetic. Inputs are in the order the operation names them."""
    if not inputs:
        raise CalcError("no inputs")
    if op == "growth":  # [old, new] -> % change
        _need(inputs, 2)
        _same_units(inputs)
        old, new = inputs[0].base, inputs[1].base
        if old == 0:
            raise CalcError("growth from zero")
        return Quantity((new - old) / abs(old) * 100, unit="percent")
    if op == "cagr":  # [start, end], periods = number of years between them
        _need(inputs, 2)
        _same_units(inputs)
        start, end = inputs[0].base, inputs[1].base
        if periods <= 0:
            raise CalcError("cagr needs periods > 0")
        if start <= 0 or end <= 0:
            raise CalcError("cagr needs positive values")
        return Quantity(((end / start) ** (1 / periods) - 1) * 100, unit="percent")
    if op in ("subtract", "change", "difference"):
        # subtract [a, b] -> a - b ("current assets less current liabilities");
        # change [old, new] -> new - old ("the change from 2017 to 2018"). Percent inputs -> percentage points.
        # "difference" is the old name for change, kept so earlier eval rows can be re-scored.
        _need(inputs, 2)
        _same_units(inputs)
        first, second = inputs if op == "subtract" else inputs[::-1]
        if first.unit == "percent":
            return Quantity(first.value - second.value, unit="other", scale="units")
        return _rescale(first.base - second.base, inputs[0])
    if op in ("margin", "share"):  # [part, whole] -> %
        _need(inputs, 2)
        part, whole = inputs
        if whole.base == 0:
            raise CalcError("division by zero")
        if part.unit == "currency" and whole.unit == "currency":
            _same_units(inputs)
        return Quantity(part.base / whole.base * 100, unit="percent")
    if op == "ratio":  # [numerator, denominator] -> x
        _need(inputs, 2)
        num, den = inputs
        if den.base == 0:
            raise CalcError("division by zero")
        if num.unit == den.unit == "currency":
            _same_units(inputs)
        return Quantity(num.base / den.base, unit="ratio")
    if op == "multiply":  # [x] * factor, for definitions like "365 * payables / COGS"
        _need(inputs, 1)
        if not factor:
            raise CalcError("multiply needs a factor")
        x = inputs[0]
        unit = "other" if x.unit == "ratio" else x.unit
        return Quantity(x.value * factor, unit=unit, currency=x.currency, scale=x.scale)
    if op == "sum":
        _same_units(inputs)
        return _rescale(sum(q.base for q in inputs), inputs[0])
    if op == "average":
        _same_units(inputs)
        return _rescale(sum(q.base for q in inputs) / len(inputs), inputs[0])
    raise CalcError(f"unknown operation {op!r}")


def _need(inputs: list[Quantity], n: int) -> None:
    if len(inputs) != n:
        raise CalcError(f"expected {n} inputs, got {len(inputs)}")


def fmt_calc(op: str, q: Quantity) -> str:
    if op in ("subtract", "change", "difference") and q.unit == "other":
        return f"{fmt_number(q.value, 2)} percentage points"
    if op == "multiply" and q.unit == "other":
        return fmt_number(q.value, 2)
    return fmt_quantity(q)
