"""Drilling-hydraulics formula REST API.

Exposes the pre-defined formula library (:mod:`app.formulas.hydraulics`) and a
per-formula compute endpoint. Each input variable can be resolved three ways
(in priority order): bound to the LATEST live value of a mnemonic in the warm
store (when ``bindings[var]`` and ``wellUid`` are supplied), an explicit
constant in ``values[var]``, or the variable's declared default.

Mounted by the spine under ``/api`` (this router carries its own
``/formulas`` prefix), so the effective paths are ``/api/formulas`` etc.
Read-only and import-clean — no work runs at import.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.formulas import hydraulics
from app.formulas.hydraulics import FormulaError
from app.ingestion.store import get_store

router = APIRouter(prefix="/formulas", tags=["formulas"])


# ── schemas ──────────────────────────────────────────────────────────────
class VariableOut(BaseModel):
    name: str
    label: str
    default: float | None = None
    unit: str | None = None
    suggest_mnemonic: str | None = None


class FormulaOut(BaseModel):
    key: str
    name: str
    description: str
    result_unit: str
    variables: list[VariableOut]


class ComputeRequest(BaseModel):
    values: dict[str, float] | None = None
    wellUid: str | None = None
    bindings: dict[str, str] | None = None


class ComputeResponse(BaseModel):
    key: str
    result: float
    result_unit: str
    used: dict[str, float]


# ── endpoints ────────────────────────────────────────────────────────────
@router.get("/", response_model=list[FormulaOut])
def list_formulas() -> list[FormulaOut]:
    """List the formula library with each formula's input variables."""
    return [
        FormulaOut(
            key=f.key,
            name=f.name,
            description=f.description,
            result_unit=f.result_unit,
            variables=[
                VariableOut(
                    name=v.name,
                    label=v.label,
                    default=v.default,
                    unit=v.unit,
                    suggest_mnemonic=v.suggest_mnemonic,
                )
                for v in f.variables
            ],
        )
        for f in hydraulics.FORMULAS
    ]


def _live_value(well_uid: str, mnemonic: str) -> float | None:
    """Latest numeric value for `mnemonic` in the warm store, or None."""
    recent = get_store().get_recent(well_uid, [mnemonic], limit=1)
    samples = recent.get(mnemonic)
    if not samples:
        return None
    return samples[-1].value


@router.post("/{key}/compute", response_model=ComputeResponse)
def compute_formula(key: str, payload: ComputeRequest) -> ComputeResponse:
    """Resolve each variable (binding > value > default) and compute the formula."""
    fdef = hydraulics.FORMULAS_BY_KEY.get(key)
    if fdef is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown formula '{key}'"
        )

    values = payload.values or {}
    bindings = payload.bindings or {}

    resolved: dict[str, float] = {}
    for var in fdef.variables:
        live: float | None = None
        mnemonic = bindings.get(var.name)
        if mnemonic and payload.wellUid:
            live = _live_value(payload.wellUid, mnemonic)

        if live is not None:
            resolved[var.name] = float(live)
        elif var.name in values and values[var.name] is not None:
            resolved[var.name] = float(values[var.name])
        elif var.default is not None:
            resolved[var.name] = float(var.default)
        # else: leave unresolved — compute() will raise FormulaError.

    try:
        result = hydraulics.compute(key, resolved)
    except FormulaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return ComputeResponse(
        key=key,
        result=result,
        result_unit=fdef.result_unit,
        used=resolved,
    )
