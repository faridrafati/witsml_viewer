"""Unit tests for the SAFE formula engine and UOM dictionary.

No network, no DB. Requires only ``simpleeval`` (plus the stdlib). The point of
this suite is twofold: prove that legitimate conversions compute correctly, and
prove that the engine REFUSES to execute arbitrary/unsafe code.
"""

from __future__ import annotations

import math

import pytest

from app.units import dictionary as uom
from app.units.engine import (
    MAX_EXPONENT,
    UnitFormulaError,
    convert,
    validate,
)


# ── valid conversions ────────────────────────────────────────────────────
def test_identity():
    assert convert(42.0, "__value__") == pytest.approx(42.0)


def test_sg_to_pcf():
    # density: sg -> pcf multiplies by 62.4
    assert convert(1.0, "__value__ * 62.4") == pytest.approx(62.4)
    assert convert(2.5, "__value__ * 62.4") == pytest.approx(156.0)


def test_percent_to_ppm():
    # fraction: percent -> ppm multiplies by 10000
    assert convert(1.0, "__value__ * 10000") == pytest.approx(10000.0)
    assert convert(0.05, "__value__ * 10000") == pytest.approx(500.0)


def test_parentheses_and_offset():
    # degF -> degC: (F - 32) * 5 / 9
    assert convert(212.0, "(__value__ - 32) * 5 / 9") == pytest.approx(100.0)
    assert convert(32.0, "(__value__ - 32) * 5 / 9") == pytest.approx(0.0)


def test_unary_minus():
    assert convert(5.0, "-__value__") == pytest.approx(-5.0)


def test_power():
    assert convert(3.0, "__value__ ** 2") == pytest.approx(9.0)


def test_functions_sin_cos():
    assert convert(0.0, "sin(__value__)") == pytest.approx(0.0)
    assert convert(0.0, "cos(__value__)") == pytest.approx(1.0)
    assert convert(math.pi / 2, "sin(__value__)") == pytest.approx(1.0)


def test_constants_pi_e_sqrt():
    assert convert(4.0, "sqrt(__value__)") == pytest.approx(2.0)
    assert convert(1.0, "__value__ * pi") == pytest.approx(math.pi)
    assert convert(1.0, "__value__ * e") == pytest.approx(math.e)


def test_abs_and_exp_log():
    assert convert(-3.0, "abs(__value__)") == pytest.approx(3.0)
    assert convert(0.0, "exp(__value__)") == pytest.approx(1.0)
    assert convert(1.0, "log(exp(__value__))") == pytest.approx(1.0)


# ── validate() accepts safe formulas ─────────────────────────────────────
@pytest.mark.parametrize(
    "expr",
    [
        "__value__",
        "__value__ * 62.4",
        "(__value__ - 32) * 5 / 9",
        "sin(__value__) + cos(__value__)",
        "__value__ ** 2",
        "sqrt(abs(__value__))",
        "__value__ * pi / e",
    ],
)
def test_validate_accepts(expr):
    ok, reason = validate(expr)
    assert ok is True
    assert reason is None


# ── INVALID / unsafe expressions are rejected ────────────────────────────
@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os')",
        "__import__('os').system('echo pwned')",
        "os.system('x')",
        "value + 1",  # missing underscores -> unknown name
        "x * 2",
        "__value__.real",  # attribute access
        "__value__.__class__",
        "().__class__.__bases__",
        "open('secret.txt')",
        "exec('x=1')",
        "eval('1+1')",
        "[__value__ for _ in range(10)]",  # comprehension
        "lambda: 1",
        "__value__ ; 1",  # multiple statements
        "__builtins__",
        "globals()",
        "__value__[0]",  # subscript
    ],
)
def test_validate_rejects(expr):
    ok, reason = validate(expr)
    assert ok is False
    assert reason


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo pwned')",
        "os.system('x')",
        "value + 1",
        "__value__.__class__",
        "open('x')",
        "().__class__.__bases__",
    ],
)
def test_convert_raises_on_unsafe(expr):
    with pytest.raises(UnitFormulaError):
        convert(1.0, expr)


def test_convert_never_executes_arbitrary_code(tmp_path):
    # If the engine ever executed the call, this file would be created.
    target = tmp_path / "should_not_exist.txt"
    payload = f"open({str(target)!r}, 'w')"
    with pytest.raises(UnitFormulaError):
        convert(1.0, payload)
    assert not target.exists()


def test_empty_expression_rejected():
    ok, reason = validate("")
    assert ok is False and reason
    ok, reason = validate("   ")
    assert ok is False and reason


def test_syntax_error_rejected():
    ok, reason = validate("__value__ *")
    assert ok is False
    with pytest.raises(UnitFormulaError):
        convert(1.0, "__value__ *")


# ── exponent guard ───────────────────────────────────────────────────────
def test_huge_exponent_literal_rejected():
    ok, reason = validate(f"__value__ ** {MAX_EXPONENT + 1}")
    assert ok is False
    with pytest.raises(UnitFormulaError):
        convert(2.0, f"__value__ ** {MAX_EXPONENT + 1}")


def test_non_literal_exponent_rejected():
    ok, _ = validate("__value__ ** __value__")
    assert ok is False
    with pytest.raises(UnitFormulaError):
        convert(2.0, "__value__ ** __value__")


def test_exponent_within_bound_ok():
    assert convert(2.0, f"__value__ ** {MAX_EXPONENT}") == pytest.approx(
        2.0**MAX_EXPONENT
    )


# ── runtime math errors surface as UnitFormulaError ──────────────────────
def test_division_by_zero():
    with pytest.raises(UnitFormulaError):
        convert(0.0, "1 / __value__")


def test_math_domain_error():
    with pytest.raises(UnitFormulaError):
        convert(-1.0, "sqrt(__value__)")


# ── dictionary normalization ─────────────────────────────────────────────
def test_dictionary_length():
    assert uom.to_canonical(100.0, "ft") == (pytest.approx(30.48), "m")
    assert uom.canonical_unit("FT") == "m"


def test_dictionary_pressure():
    val, canon = uom.to_canonical(1.0, "psi")
    assert canon == "kPa"
    assert val == pytest.approx(6.894757)


def test_dictionary_density_pcf_sg_roundtrip():
    # 1 sg == 62.4 pcf, so 62.4 pcf -> 1 sg
    val, canon = uom.to_canonical(62.4, "pcf")
    assert canon == "sg"
    assert val == pytest.approx(1.0)


def test_dictionary_fraction_ppm():
    assert uom.normalize(10000.0, "ppm") == pytest.approx(1.0)  # 1 percent
    assert uom.normalize(50.0, "%") == pytest.approx(50.0)


def test_dictionary_force_klbf():
    val, canon = uom.to_canonical(1.0, "klbf")
    assert canon == "N"
    assert val == pytest.approx(4448.2216)


def test_dictionary_unknown_unit():
    assert not uom.is_known("furlong")
    with pytest.raises(KeyError):
        uom.to_canonical(1.0, "furlong")


def test_dictionary_quantity_guard():
    with pytest.raises(ValueError):
        uom.normalize(1.0, "ft", "sg")
