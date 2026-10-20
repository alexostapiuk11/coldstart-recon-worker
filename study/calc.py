"""The practice page's calculator: a tiny expression language, in Python and in JavaScript.

Grammar (no implicit multiplication, no other characters):

    expr   := term (("+" | "-") term)*
    term   := unary (("*" | "/") unary)*
    unary  := ("-" | "+") unary | power
    power  := atom ("^" unary)?              right associative: 2^3^2 = 2^9; -2^2 = -4
    atom   := NUMBER | NAME | NAME "(" expr ("," expr)* ")" | "(" expr ")"

NUMBER is `12`, `1.5`, `.5` or any of those with an exponent (`1.5e3`). NAME is an input id.
Functions: ceil floor abs sqrt log2 log10 (one argument) and min max (two or more).

Python (study.practice validates every expression, and renders the defaults for the brief
and the page's no-JavaScript fallback) and the page's script (CALC_JS, which never calls
eval or builds a Function) implement the same rules; tests run both and compare the text
they print. Every operation must give a finite number: a division by zero, the square root
of a negative, a log of zero or an overflow is an error, which the page shows as "n/a".
"""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal, localcontext

MAX_EXPR = 200
MAX_DEPTH = 32
FUNCTIONS = {"ceil": (1, 1), "floor": (1, 1), "abs": (1, 1), "sqrt": (1, 1), "log2": (1, 1),
             "log10": (1, 1), "min": (2, None), "max": (2, None)}
EXPONENT_FROM = 1e15  # at or above this a number prints in exponent form

_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)"
                    r"|([A-Za-z_][A-Za-z0-9_]*)|(.))")


class CalcError(ValueError):
    """An expression does not parse, or does not evaluate to a finite number."""


def _tokens(src: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    src = src.rstrip()
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        number, name, other = m.groups()
        if number is not None:
            out.append(("num", number))
        elif name is not None:
            out.append(("name", name))
        elif other in "+-*/^(),":
            out.append(("op", other))
        else:
            raise CalcError(f"unexpected character '{other}'")
        pos = m.end()
    return out


class _Parser:
    def __init__(self, tokens):
        self.t, self.i, self.depth = tokens, 0, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else ("end", "")

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def fail(self, tok):
        kind, text = tok
        if kind == "end":
            raise CalcError("unexpected end of the expression")
        if kind == "num":
            raise CalcError("unexpected number")
        if kind == "name":
            raise CalcError(f"unexpected name '{text}'")
        raise CalcError(f"unexpected '{text}'")

    def op(self, *ops):
        kind, text = self.peek()
        return kind == "op" and text in ops

    def expr(self):
        node = self.term()
        while self.op("+", "-"):
            node = ("bin", self.take()[1], node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.op("*", "/"):
            node = ("bin", self.take()[1], node, self.unary())
        return node

    def unary(self):
        if self.op("-", "+"):
            sign = self.take()[1]
            inner = self.unary()
            return ("neg", inner) if sign == "-" else inner
        return self.power()

    def power(self):
        base = self.atom()
        if self.op("^"):
            self.take()
            return ("bin", "^", base, self.unary())
        return base

    def atom(self):
        kind, text = self.take()
        if kind == "num":
            return ("num", float(text))
        if kind == "name":
            if not self.op("("):
                return ("var", text)
            if text not in FUNCTIONS:
                raise CalcError(f"unknown function '{text}'")
            self.take()
            self.enter()
            args = [self.expr()]
            while self.op(","):
                self.take()
                args.append(self.expr())
            if not self.op(")"):
                if self.peek()[0] == "end":
                    raise CalcError("missing ')'")
                self.fail(self.peek())
            self.take()
            self.depth -= 1
            lo, hi = FUNCTIONS[text]
            if len(args) < lo or (hi is not None and len(args) > hi):
                if hi is None:
                    raise CalcError(f"{text} needs at least {lo} arguments")
                raise CalcError(f"{text} takes {hi} argument{'s' if hi != 1 else ''}")
            return ("call", text, args)
        if kind == "op" and text == "(":
            self.enter()
            node = self.expr()
            if not self.op(")"):
                if self.peek()[0] == "end":
                    raise CalcError("missing ')'")
                self.fail(self.peek())
            self.take()
            self.depth -= 1
            return node
        self.fail((kind, text))

    def enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise CalcError(f"nested deeper than {MAX_DEPTH} levels")


def parse(src: str) -> tuple:
    """The expression's syntax tree; raise CalcError (naming the problem) if it is not valid."""
    if not src.strip():
        raise CalcError("the expression is empty")
    if len(src) > MAX_EXPR:
        raise CalcError(f"the expression is longer than {MAX_EXPR} characters")
    parser = _Parser(_tokens(src))
    node = parser.expr()
    if parser.peek()[0] != "end":
        parser.fail(parser.peek())
    return node


def names(node: tuple) -> set[str]:
    """The input ids (variable names) an expression reads."""
    kind = node[0]
    if kind == "var":
        return {node[1]}
    if kind == "neg":
        return names(node[1])
    if kind == "bin":
        return names(node[2]) | names(node[3])
    if kind == "call":
        return set().union(*(names(a) for a in node[2]))
    return set()


def _finite(v: float) -> float:
    if not math.isfinite(v):
        raise CalcError("the result is not a finite number")
    return v


def _call(name: str, a: list[float]) -> float:
    if name in ("min", "max"):
        return min(a) if name == "min" else max(a)
    x = a[0]
    if name == "ceil":
        return float(math.ceil(x))
    if name == "floor":
        return float(math.floor(x))
    if name == "abs":
        return abs(x)
    if name == "sqrt":
        if x < 0:
            raise CalcError("sqrt of a negative number")
        return math.sqrt(x)
    if x <= 0:
        raise CalcError(f"{name} of a non-positive number")
    return math.log2(x) if name == "log2" else math.log10(x)


def evaluate(node: tuple, env: dict[str, float]) -> float:
    """The expression's value for the input values `env`; CalcError unless it is finite."""
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "var":
        if node[1] not in env:
            raise CalcError(f"no value for '{node[1]}'")
        return float(env[node[1]])
    if kind == "neg":
        return -evaluate(node[1], env)
    if kind == "call":
        return _finite(_call(node[1], [evaluate(a, env) for a in node[2]]))
    op, a, b = node[1], evaluate(node[2], env), evaluate(node[3], env)
    if op == "+":
        return _finite(a + b)
    if op == "-":
        return _finite(a - b)
    if op == "*":
        return _finite(a * b)
    if op == "/":
        if b == 0:
            raise CalcError("division by zero")
        return _finite(a / b)
    try:
        return _finite(math.pow(a, b))
    except (ValueError, OverflowError, ZeroDivisionError):
        raise CalcError("the result is not a finite number") from None


def _group(digits: str) -> str:
    """'1234567' -> '1,234,567'."""
    return re.sub(r"\B(?=(\d{3})+$)", ",", digits)


def fmt_number(v: float, digits: int) -> str:
    """`v` with `digits` decimals and thousands commas ('1,234.50'); from 1e15 up, in
    exponent form ('1.00e+15'). Halves round away from zero and a negative that rounds to
    zero prints without a sign; JavaScript's toFixed gives the same text (CALC_JS)."""
    exact = Decimal(v)
    with localcontext() as ctx:
        ctx.rounding = ROUND_HALF_UP
        ctx.prec = 60
        if abs(v) >= EXPONENT_FROM:
            return format(exact, f".{digits}e").lower()
        text = format(exact.quantize(Decimal(1).scaleb(-digits)), "f")
    sign = "-" if text.startswith("-") else ""
    whole, _, frac = text.lstrip("-").partition(".")
    out = _group(whole) + ("." + frac if frac else "")
    if not out.replace(",", "").replace(".", "").strip("0"):
        sign = ""
    return sign + out


# The same language for the page. calcParse(src) -> tree (throws Error); calcEval(tree, vars)
# -> number (throws Error unless finite); calcFmt(number, digits) -> text. The tree is built
# from arrays like the Python one; nothing is ever passed to eval or Function.
CALC_JS = r"""
const CALC_FUNCTIONS = {ceil: [1, 1], floor: [1, 1], abs: [1, 1], sqrt: [1, 1], log2: [1, 1],
  log10: [1, 1], min: [2, Infinity], max: [2, Infinity]};
function calcParse(src) {
  if (!src.trim()) throw new Error('the expression is empty');
  if (src.length > 200) throw new Error('the expression is too long');
  const re = /\s*(?:(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|(.))/y;
  const text = src.replace(/\s+$/, ''), toks = [];
  while (re.lastIndex < text.length) {
    const m = re.exec(text);
    if (m[1] !== undefined) toks.push(['num', m[1]]);
    else if (m[2] !== undefined) toks.push(['name', m[2]]);
    else if ('+-*/^(),'.includes(m[3])) toks.push(['op', m[3]]);
    else throw new Error("unexpected character '" + m[3] + "'");
  }
  let i = 0, depth = 0;
  const peek = () => (i < toks.length ? toks[i] : ['end', '']);
  const isOp = (...ops) => { const t = peek(); return t[0] === 'op' && ops.includes(t[1]); };
  const fail = () => { throw new Error('unexpected ' + peek()[0] + ' ' + peek()[1]); };
  const enter = () => { if (++depth > 32) throw new Error('nested too deep'); };
  const close = () => { if (!isOp(')')) fail(); i++; depth--; };
  function expr() {
    let n = term();
    while (isOp('+', '-')) { const o = toks[i++][1]; n = ['bin', o, n, term()]; }
    return n;
  }
  function term() {
    let n = unary();
    while (isOp('*', '/')) { const o = toks[i++][1]; n = ['bin', o, n, unary()]; }
    return n;
  }
  function unary() {
    if (isOp('-', '+')) { const s = toks[i++][1], n = unary(); return s === '-' ? ['neg', n] : n; }
    return power();
  }
  function power() {
    const base = atom();
    if (isOp('^')) { i++; return ['bin', '^', base, unary()]; }
    return base;
  }
  function atom() {
    const t = peek();
    if (t[0] === 'num') { i++; return ['num', parseFloat(t[1])]; }
    if (t[0] === 'name') {
      i++;
      if (!isOp('(')) return ['var', t[1]];
      if (!(t[1] in CALC_FUNCTIONS)) throw new Error('unknown function ' + t[1]);
      i++; enter();
      const args = [expr()];
      while (isOp(',')) { i++; args.push(expr()); }
      close();
      const [lo, hi] = CALC_FUNCTIONS[t[1]];
      if (args.length < lo || args.length > hi) throw new Error('wrong number of arguments to ' + t[1]);
      return ['call', t[1], args];
    }
    if (t[0] === 'op' && t[1] === '(') { i++; enter(); const n = expr(); close(); return n; }
    return fail();
  }
  const tree = expr();
  if (peek()[0] !== 'end') fail();
  return tree;
}
function calcFinite(v) {
  if (!Number.isFinite(v)) throw new Error('not a finite number');
  return v;
}
function calcEval(n, vars) {
  switch (n[0]) {
    case 'num': return n[1];
    case 'var':
      if (!(n[1] in vars)) throw new Error('no value for ' + n[1]);
      return calcFinite(vars[n[1]]);
    case 'neg': return -calcEval(n[1], vars);
    case 'call': {
      const a = n[2].map(x => calcEval(x, vars)), x = a[0];
      switch (n[1]) {
        case 'min': return calcFinite(Math.min(...a));
        case 'max': return calcFinite(Math.max(...a));
        case 'ceil': return calcFinite(Math.ceil(x));
        case 'floor': return calcFinite(Math.floor(x));
        case 'abs': return calcFinite(Math.abs(x));
        case 'sqrt': if (x < 0) throw new Error('sqrt of a negative number');
          return calcFinite(Math.sqrt(x));
        default: if (x <= 0) throw new Error('log of a non-positive number');
          return calcFinite(n[1] === 'log2' ? Math.log2(x) : Math.log10(x));
      }
    }
    default: {
      const a = calcEval(n[2], vars), b = calcEval(n[3], vars);
      switch (n[1]) {
        case '+': return calcFinite(a + b);
        case '-': return calcFinite(a - b);
        case '*': return calcFinite(a * b);
        case '/': if (b === 0) throw new Error('division by zero');
          return calcFinite(a / b);
        default: return calcFinite(Math.pow(a, b));
      }
    }
  }
}
function calcFmt(v, digits) {
  if (Math.abs(v) >= 1e15) return v.toExponential(digits);
  const t = Math.abs(v).toFixed(digits), p = t.split('.');
  const out = p[0].replace(/\B(?=(\d{3})+$)/g, ',') + (p[1] ? '.' + p[1] : '');
  return (v < 0 && /[1-9]/.test(t) ? '-' : '') + out;
}
"""
