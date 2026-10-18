// Pure helpers for the cost table (safe to import from client components).

export type CostRow = {
  /** Rules deployed, 1 to 10. */
  rules: number
  /** Dollar amounts and the ratio as published, for example "$0.00179", "$0.0133", "7x". */
  exemplar: string
  zeroShot: string
  ratio: string
}

export const dollars = (s: string): number => Number(s.replace('$', ''))
