"""Drilling-hydraulics formula engine (brief §7.7).

A small library of pre-defined formulas. Each input variable can be supplied
as a constant or bound to a live mnemonic (the API/UI feeds current values).
Evaluation is SAFE (simpleeval over the declared variable names only — never
eval). Reproduces the legacy Impact Force form:

    ImpactForce = (GPM * MW * JV) / 1932

with GPM a constant and MW / JV bindable to live curves.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from simpleeval import EvalWithCompoundTypes  # type: ignore


class FormulaError(ValueError):
    """Raised on an invalid expression or a failed/blocked evaluation."""


@dataclass(frozen=True)
class VarDef:
    name: str  # identifier used in the expression
    label: str
    default: float | None = None  # default constant
    unit: str | None = None
    #: suggested live mnemonic this input is typically bound to (UI hint).
    suggest_mnemonic: str | None = None


@dataclass(frozen=True)
class FormulaDef:
    key: str
    name: str
    expression: str
    variables: list[VarDef]
    result_unit: str
    description: str = ""

    @property
    def var_names(self) -> list[str]:
        return [v.name for v in self.variables]


# ── safe evaluation ─────────────────────────────────────────────────────
_ALLOWED_FUNCS = {
    "sqrt": lambda x: x**0.5,
    "abs": abs,
    "min": min,
    "max": max,
    "pow": pow,
}
# AST node types permitted in a formula expression.
_ALLOWED_NODES = (
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
_MAX_EXPONENT = 8


def _validate_ast(expression: str, allowed_names: set[str]) -> None:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"invalid expression syntax: {exc}") from exc

    call_func_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
                raise FormulaError("only sqrt/abs/min/max/pow calls are allowed")
            if node.keywords:
                raise FormulaError("keyword arguments are not allowed")
            call_func_nodes.add(id(node.func))
        if isinstance(node, ast.Pow):
            pass  # exponent bound checked below
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and id(node) not in call_func_nodes:
            if node.id not in allowed_names:
                raise FormulaError(f"unknown name '{node.id}' in expression")
        elif not isinstance(node, _ALLOWED_NODES) and id(node) not in call_func_nodes:
            raise FormulaError(f"disallowed expression element: {type(node).__name__}")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exp = node.right
            if isinstance(exp, ast.Constant) and isinstance(exp.value, (int, float)):
                if abs(exp.value) > _MAX_EXPONENT:
                    raise FormulaError("exponent too large")
            else:
                raise FormulaError("exponent must be a small numeric literal")


def safe_eval(expression: str, values: dict[str, float]) -> float:
    """Evaluate `expression` with `values` bound to names. Safe (no eval)."""
    _validate_ast(expression, set(values) | set(_ALLOWED_FUNCS))
    evaluator = EvalWithCompoundTypes(names=dict(values), functions=dict(_ALLOWED_FUNCS))
    try:
        result = evaluator.eval(expression)
    except ZeroDivisionError as exc:
        raise FormulaError("division by zero") from exc
    except Exception as exc:  # noqa: BLE001 — surface as a domain error
        raise FormulaError(f"evaluation failed: {exc}") from exc
    try:
        return float(result)
    except (TypeError, ValueError) as exc:
        raise FormulaError("expression did not produce a number") from exc


# ── formula library (field units) ──────────────────────────────────────
FORMULAS: list[FormulaDef] = [
    FormulaDef(
        key="annular_velocity",
        name="Annular Velocity",
        expression="(24.5 * Q) / (Dh**2 - Dp**2)",
        result_unit="ft/min",
        description="Mud velocity in the annulus.",
        variables=[
            VarDef("Q", "Flow rate", 600.0, "gpm", "FLOWIN"),
            VarDef("Dh", "Hole diameter", 8.5, "in"),
            VarDef("Dp", "Pipe OD", 5.0, "in"),
        ],
    ),
    FormulaDef(
        key="ecd",
        name="Equivalent Circulating Density (ECD)",
        expression="MW + (Pann / (0.052 * TVD))",
        result_unit="ppg",
        description="Effective density including annular pressure loss.",
        variables=[
            VarDef("MW", "Mud weight", 9.5, "ppg", "MW"),
            VarDef("Pann", "Annular pressure loss", 250.0, "psi"),
            VarDef("TVD", "True vertical depth", 10000.0, "ft", "DEPTH"),
        ],
    ),
    FormulaDef(
        key="critical_velocity",
        name="Critical Velocity",
        expression="(1.08 * PV + 1.08 * sqrt(PV**2 + 9.3 * MW * Dh**2 * YP)) / (MW * Dh)",
        result_unit="ft/min",
        description="Velocity at the laminar/turbulent transition (approx).",
        variables=[
            VarDef("PV", "Plastic viscosity", 20.0, "cP"),
            VarDef("YP", "Yield point", 15.0, "lbf/100ft2"),
            VarDef("MW", "Mud weight", 9.5, "ppg", "MW"),
            VarDef("Dh", "Hole diameter", 8.5, "in"),
        ],
    ),
    FormulaDef(
        key="bit_pressure_drop",
        name="Pressure Drop Across Bit",
        expression="(Q**2 * MW) / (12031 * TFA**2)",
        result_unit="psi",
        description="Pressure loss across the bit nozzles.",
        variables=[
            VarDef("Q", "Flow rate", 600.0, "gpm", "FLOWIN"),
            VarDef("MW", "Mud weight", 9.5, "ppg", "MW"),
            VarDef("TFA", "Total flow area", 0.5, "in2"),
        ],
    ),
    FormulaDef(
        key="total_hydraulic_hp",
        name="Total Hydraulic Horsepower",
        expression="(P * Q) / 1714",
        result_unit="hhp",
        description="System hydraulic horsepower.",
        variables=[
            VarDef("P", "Standpipe pressure", 3000.0, "psi", "SPP"),
            VarDef("Q", "Flow rate", 600.0, "gpm", "FLOWIN"),
        ],
    ),
    FormulaDef(
        key="hsi",
        name="HSI (Horsepower per Square Inch)",
        expression="(1.27 * HHPbit) / Dbit**2",
        result_unit="hp/in2",
        description="Bit hydraulic horsepower per square inch of hole.",
        variables=[
            VarDef("HHPbit", "Bit hydraulic HP", 800.0, "hhp"),
            VarDef("Dbit", "Bit diameter", 8.5, "in"),
        ],
    ),
    FormulaDef(
        key="pct_hhp_bit",
        name="% HHP at Bit",
        expression="(Pbit / P) * 100",
        result_unit="%",
        description="Share of hydraulic horsepower expended at the bit.",
        variables=[
            VarDef("Pbit", "Bit pressure drop", 1500.0, "psi"),
            VarDef("P", "Standpipe pressure", 3000.0, "psi", "SPP"),
        ],
    ),
    FormulaDef(
        key="impact_force",
        name="Impact Force",
        # Legacy mudlogging form: (GPM * MW * JV) / 1932.
        expression="(GPM * MW * JV) / 1932",
        result_unit="lbf",
        description="Jet impact force at the bit (legacy form).",
        variables=[
            VarDef("GPM", "Flow rate", 120.0, "gpm", None),
            VarDef("MW", "Mud weight", 9.5, "ppg", "MW"),
            VarDef("JV", "Jet velocity", 250.0, "ft/s", "SPARE"),
        ],
    ),
]

FORMULAS_BY_KEY: dict[str, FormulaDef] = {f.key: f for f in FORMULAS}


def compute(formula_key: str, values: dict[str, float]) -> float:
    """Compute a registered formula. Missing variables fall back to defaults."""
    fdef = FORMULAS_BY_KEY.get(formula_key)
    if fdef is None:
        raise FormulaError(f"unknown formula '{formula_key}'")
    resolved: dict[str, float] = {}
    for var in fdef.variables:
        if var.name in values and values[var.name] is not None:
            resolved[var.name] = float(values[var.name])
        elif var.default is not None:
            resolved[var.name] = float(var.default)
        else:
            raise FormulaError(f"missing value for '{var.name}'")
    return safe_eval(fdef.expression, resolved)
