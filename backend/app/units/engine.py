"""SAFE formula-based unit conversion engine (brief §7.6).

A unit conversion is expressed as a tiny arithmetic formula over a single
placeholder name ``__value__`` — e.g. ``"__value__ * 62.4"`` (sg -> pcf) or
``"(__value__ - 32) * 5 / 9"`` (degF -> degC). Formulas are stored in the DB
(:class:`app.db.models.UnitDef`) and entered by operators, so they MUST be
evaluated without ever touching Python's ``eval``/``exec`` or any construct
that could reach the filesystem, import machinery, or attributes.

Design
------
* Evaluation is delegated to ``simpleeval.SimpleEval`` configured with a
  *closed* set of operators, functions and names. There is exactly ONE
  allowed name (``__value__``) and a short whitelist of math functions.
* Before evaluating (and during :func:`validate`) we additionally walk the
  parsed AST ourselves and reject any node type we do not explicitly allow —
  attribute access, subscripting, comprehensions, lambdas, calls to anything
  outside the whitelist, and any name other than ``__value__``. This is a
  belt-and-suspenders layer on top of simpleeval's own guards.
* ``**`` is supported but the exponent is bounded so a formula cannot be used
  to burn CPU/RAM with an enormous power (e.g. ``__value__ ** 1e9``).

Public API
----------
``convert(value, expression) -> float``
``validate(expression) -> (ok: bool, error: str | None)``
``UnitFormulaError`` — raised by :func:`convert` for anything unsafe/invalid.
"""

from __future__ import annotations

import ast
import math

import simpleeval

# The single placeholder substituted with the input magnitude at eval time.
VALUE_NAME = "__value__"

# Largest absolute exponent permitted in a ``**`` expression. Keeps formulas
# cheap to evaluate; well above anything a real UOM conversion needs.
MAX_EXPONENT = 64

# Whitelisted callables. Deliberately math-only and side-effect free.
ALLOWED_FUNCTIONS: dict[str, object] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "sqrt": math.sqrt,
    "abs": abs,
    "log": math.log,
    "exp": math.exp,
}

# Whitelisted bare names (constants). ``__value__`` is the only variable.
ALLOWED_CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
}

# Every name simpleeval is allowed to resolve. ``__value__`` is injected per
# call in :func:`convert`; here it is a harmless placeholder so :func:`validate`
# (which does not have a real value) can still compile-check formulas.
_ALLOWED_NAMES = frozenset({VALUE_NAME, *ALLOWED_CONSTANTS})

# AST node types permitted anywhere in a formula. Anything else (Attribute,
# Subscript, Call to non-whitelisted func, Lambda, comprehensions, names,
# assignments, ...) is rejected. ``Call`` and ``Name`` get extra checks below.
_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Call,
)


class UnitFormulaError(ValueError):
    """Raised when a conversion expression is unsafe, malformed, or fails."""


def _check_ast(tree: ast.AST) -> None:
    """Reject any node/name/call outside the safe whitelist.

    Raises :class:`UnitFormulaError` on the first violation found.
    """
    # Name nodes that are the *callee* of a Call are checked against the
    # function whitelist, not the value/constant whitelist. Collect them so the
    # generic Name pass below does not reject e.g. ``sin`` in ``sin(x)``.
    callee_nodes: set[int] = set()

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise UnitFormulaError(f"disallowed syntax: {type(node).__name__}")

        if isinstance(node, ast.Call):
            # Only direct calls to whitelisted functions, no kwargs/starargs.
            func = node.func
            if not isinstance(func, ast.Name):
                raise UnitFormulaError("only direct function calls are allowed")
            if func.id not in ALLOWED_FUNCTIONS:
                raise UnitFormulaError(f"unknown function: {func.id!r}")
            if node.keywords:
                raise UnitFormulaError("keyword arguments are not allowed")
            callee_nodes.add(id(func))

        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            _check_exponent(node.right)

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and id(node) not in callee_nodes:
            if node.id not in _ALLOWED_NAMES:
                raise UnitFormulaError(f"unknown name: {node.id!r}")


def _check_exponent(exp_node: ast.AST) -> None:
    """Bound ``**`` exponents to a literal/negated-literal within range.

    A non-constant exponent (e.g. ``__value__ ** __value__``) is rejected
    outright because we cannot bound it statically.
    """
    if isinstance(exp_node, ast.UnaryOp) and isinstance(exp_node.op, (ast.USub, ast.UAdd)):
        exp_node = exp_node.operand
    if not (isinstance(exp_node, ast.Constant) and isinstance(exp_node.value, (int, float))):
        raise UnitFormulaError("exponent must be a numeric literal")
    if abs(exp_node.value) > MAX_EXPONENT:
        raise UnitFormulaError(f"exponent magnitude exceeds {MAX_EXPONENT}")


def _build_evaluator(value: float) -> simpleeval.SimpleEval:
    names = dict(ALLOWED_CONSTANTS)
    names[VALUE_NAME] = value
    ev = simpleeval.SimpleEval(
        functions=dict(ALLOWED_FUNCTIONS),
        names=names,
    )
    # Tighten simpleeval's own power guard well below its default (4_000_000).
    ev.operators[ast.Pow] = _safe_pow
    return ev


def _safe_pow(a: float, b: float) -> float:
    if abs(b) > MAX_EXPONENT:
        raise UnitFormulaError(f"exponent magnitude exceeds {MAX_EXPONENT}")
    return a**b


def validate(expression: str) -> tuple[bool, str | None]:
    """Compile-check a formula without evaluating it.

    Returns ``(True, None)`` if the expression parses and uses only the safe
    operator/function/name set, otherwise ``(False, reason)``. Never raises.
    """
    if not isinstance(expression, str) or not expression.strip():
        return False, "expression is empty"
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        return False, f"syntax error: {exc.msg}"
    try:
        _check_ast(tree)
    except UnitFormulaError as exc:
        return False, str(exc)
    return True, None


def convert(value: float, expression: str) -> float:
    """Evaluate ``expression`` with ``__value__`` bound to ``value``.

    Raises :class:`UnitFormulaError` if the expression is unsafe, malformed,
    or fails at runtime (e.g. division by zero, math domain error). Arbitrary
    code is never executed — only the whitelisted arithmetic/functions run.
    """
    ok, reason = validate(expression)
    if not ok:
        raise UnitFormulaError(reason or "invalid expression")

    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise UnitFormulaError(f"value is not numeric: {value!r}") from exc

    # Re-parse and re-check the AST defensively right before evaluation.
    tree = ast.parse(expression, mode="eval")
    _check_ast(tree)

    evaluator = _build_evaluator(value)
    try:
        result = evaluator.eval(expression)
    except UnitFormulaError:
        raise
    except simpleeval.InvalidExpression as exc:
        raise UnitFormulaError(str(exc)) from exc
    except (
        ArithmeticError,
        ValueError,
        OverflowError,
    ) as exc:
        raise UnitFormulaError(f"evaluation failed: {exc}") from exc

    try:
        return float(result)
    except (TypeError, ValueError) as exc:
        raise UnitFormulaError(f"expression did not produce a number: {result!r}") from exc
