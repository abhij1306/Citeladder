export type FrontendPolicy = {
  format_version: number;
  roots: string[];
  defaults: {
    max_function_cc: number;
    max_production_loc: number;
    max_test_loc: number;
  };
  exceptions: {
    functions: Record<string, number>;
    modules: Record<string, number>;
  };
};

export type FunctionMeasurement = { name: string; cc: number; line: number };
export type ModuleMeasurement = {
  loc: number;
  test: boolean;
  functions: FunctionMeasurement[];
};

export function measure(file: string): ModuleMeasurement;
export function validatePolicy(policy: FrontendPolicy): FrontendPolicy;
export function failuresFor(
  measurements: Record<string, ModuleMeasurement>,
  policy: FrontendPolicy,
): string[];
export function staleExceptionFailures(
  measurements: Record<string, ModuleMeasurement>,
  policy: FrontendPolicy,
): string[];
export function policyDiffFailures(base: FrontendPolicy, current: FrontendPolicy): string[];
