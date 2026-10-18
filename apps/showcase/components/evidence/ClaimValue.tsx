import { TextLink } from '@/components/index.ts'
import { claim } from './claims.ts'
import { blob } from './repo.ts'

/** A published figure, rendered exactly as published. `data-src` names the claim it came from. */
export function ClaimValue({ id, className }: { id: string; className?: string }) {
  const c = claim(id)
  return <span data-src={`claims:${c.id}`} className={className}>{c.display}</span>
}

/** "docs/DEVPOST.md, line 93" as a link to that line in the repository. */
export function ClaimSource({ id }: { id: string }) {
  const { source } = claim(id)
  return <TextLink href={blob(source.path, source.line)}>{source.path}{source.line ? `, line ${source.line}` : ''}</TextLink>
}
