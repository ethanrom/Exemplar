// Published claims, each with the document and line it was copied from (data/claims.json, from stream/sh-data).
// Pages render `display` verbatim and never reformat it. Server code only: the loader reads files at build time.
import { loadClaims } from '../../lib/data/load.ts'
import type { Claim } from '../../lib/data/types.ts'
import { EXTRA_CLAIMS } from './extra-claims.ts'

export type { Claim } from '../../lib/data/types.ts'

// The data file wins when both define an id.
const byId = new Map<string, Claim>()
for (const c of EXTRA_CLAIMS) byId.set(c.id, c)
for (const c of loadClaims().claims) byId.set(c.id, c)

/** A claim by id. Throws when it is missing, so a typo fails the build instead of rendering an empty slot. */
export function claim(id: string): Claim {
  const found = byId.get(id)
  if (!found) throw new Error(`unknown claim ${JSON.stringify(id)}`)
  return found
}
