import { useMutation, useQuery } from '@tanstack/react-query';
import { http } from './http';

/**
 * API layer for the drilling-hydraulics formula engine (brief §7.7).
 *
 *   useFormulas()        -> GET  /api/formulas
 *   useComputeFormula()  -> POST /api/formulas/{key}/compute
 *
 * The wire shapes mirror the backend FormulaDef / VarDef dataclasses
 * (app/formulas/hydraulics.py), which FastAPI serializes with their snake_case
 * attribute names. Nothing is requested at module-evaluation time; all network
 * access is lazy inside the hooks.
 */

/** One input variable of a formula (mirrors VarDef). */
export interface FormulaVariable {
  name: string;
  label: string;
  /** Default constant value, if the variable has one. */
  default?: number | null;
  unit?: string | null;
  /** Suggested live mnemonic this input is typically bound to (UI hint). */
  suggest_mnemonic?: string | null;
}

/** A registered formula (mirrors FormulaDef). */
export interface FormulaDef {
  key: string;
  name: string;
  expression: string;
  variables: FormulaVariable[];
  result_unit: string;
  description?: string;
}

/** Request body for POST /api/formulas/{key}/compute. */
export interface ComputeRequest {
  /** Variable name -> value. Missing names fall back to the formula default. */
  values: Record<string, number>;
}

/** Response of POST /api/formulas/{key}/compute. */
export interface ComputeResponse {
  key: string;
  result: number;
  result_unit: string;
}

/** Fetch the formula library. Cached aggressively — it rarely changes. */
export function useFormulas() {
  return useQuery<FormulaDef[]>({
    queryKey: ['formulas'],
    queryFn: async () => {
      const { data } = await http.get<FormulaDef[]>('/formulas');
      return data;
    },
    staleTime: 5 * 60_000,
  });
}

/**
 * Compute one formula. Exposed as a mutation so the page can fire it on demand
 * (input change, poll tick, or an explicit refresh button) and read isPending /
 * error state without it being tied to a stable query key.
 */
export function useComputeFormula() {
  return useMutation<
    ComputeResponse,
    Error,
    { key: string; values: Record<string, number> }
  >({
    mutationFn: async ({ key, values }) => {
      const body: ComputeRequest = { values };
      const { data } = await http.post<ComputeResponse>(
        `/formulas/${encodeURIComponent(key)}/compute`,
        body,
      );
      return data;
    },
  });
}
