import { Badge, Card, CodeBlock, TextLink } from '@/components/index.ts'
import { ClaimSource, ClaimValue } from './ClaimValue.tsx'
import { blob } from './repo.ts'

export type VerificationRowData = {
  id: string
  title: string
  claims: string[]
  also?: string[]
  establishes: string
  how: string[]
  commands: string[]
  runtime?: string
  files: { path: string; what: string }[]
}

/**
 * One verification row: the claim and its published number on the left; how it was measured, the exact command and
 * the source files on the right. Stacks on a phone.
 */
export function VerificationRow({ row }: { row: VerificationRowData }) {
  const headingId = `row-${row.id}`
  return (
    <Card as="li" id={row.id} className="scroll-mt-20" padding="lg">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:gap-10">
        <div className="min-w-0">
          <h3 id={headingId} className="text-md font-semibold leading-6 tracking-tight text-ex-ink">{row.title}</h3>
          {row.claims.length > 0 && (
            <ul className="mt-3 space-y-2" aria-label="Published numbers">
              {row.claims.map((id) => (
                <li key={id}>
                  <p className="text-lg font-semibold tracking-tight text-ex-ink"><ClaimValue id={id} /></p>
                  <p className="mt-0.5 text-xs text-ex-ink3">Published in <ClaimSource id={id} /></p>
                </li>
              ))}
            </ul>
          )}
          {row.claims.length === 0 && (
            <p className="mt-3"><Badge tone="info" icon="check">Property tests</Badge></p>
          )}
          {row.also && row.also.length > 0 && (
            <ul className="mt-3 space-y-1.5 text-sm text-ex-ink2" aria-label="Related published figures">
              {row.also.map((id) => (
                <li key={id}><ClaimValue id={id} /> <span className="text-xs text-ex-ink3">(<ClaimSource id={id} />)</span></li>
              ))}
            </ul>
          )}
          <p className="mt-4 text-sm text-ex-ink2">{row.establishes}</p>
        </div>

        <div className="min-w-0 space-y-4">
          <div>
            <h4 className="label">How it was measured</h4>
            <div className="mt-1 space-y-2 text-sm text-ex-ink2">
              {row.how.map((p) => <p key={p}>{p}</p>)}
            </div>
          </div>
          <div>
            <h4 className="label">
              Reproduce it{row.runtime ? <span className="font-normal"> ({row.runtime.toLowerCase()})</span> : null}
            </h4>
            <CodeBlock className="mt-1 text-xs sm:text-[13px]" label={`Commands to reproduce: ${row.title}`}>{row.commands.join('\n')}</CodeBlock>
          </div>
          <div>
            <h4 className="label">Source files</h4>
            <ul className="mt-1 space-y-1 text-sm text-ex-ink2">
              {row.files.map((f) => (
                <li key={f.path} className="min-w-0">
                  <TextLink href={blob(f.path)} className="break-all font-mono text-xs">{f.path}</TextLink>
                  <span className="text-ex-ink3"> &mdash; {f.what}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </Card>
  )
}
