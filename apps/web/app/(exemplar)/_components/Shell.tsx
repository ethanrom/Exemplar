'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { ReactNode } from 'react'
import { AppProvider, useApp } from '../_lib/app'
import { fmtCountdown } from '../_lib/format'
import { useNow } from '../_lib/hooks'
import { Badge } from './ui'
import { Icon } from './Icon'

const LINKS = [
  { href: '/connect', label: 'Connect' },
  { href: '/library', label: 'Library' },
  { href: '/teach', label: 'Teach' },
  { href: '/rule', label: 'Rule' },
  { href: '/live', label: 'Live' },
  { href: '/eval', label: 'Eval' },
]

function AuthChip() {
  const { auth } = useApp()
  const now = useNow(1000)
  if (!auth) return <Badge tone="neutral" icon="clock">Ring: checking</Badge>
  if (!auth.connected) {
    const expired = auth.expires_at_ms != null && auth.expires_at_ms <= now
    return (
      <Link href="/connect" className="rounded-full">
        <Badge tone={expired ? 'neg' : 'warn'}>{expired ? 'Ring token expired' : 'Ring not connected'}</Badge>
      </Link>
    )
  }
  if (auth.mode === 'oauth' || auth.expires_at_ms == null) {
    return <Link href="/connect" className="rounded-full"><Badge tone="pos">Ring connected (OAuth)</Badge></Link>
  }
  const left = auth.expires_at_ms - now
  return (
    <Link href="/connect" className="rounded-full" aria-label={`Ring Playground token, ${fmtCountdown(left)} left. Open Connect.`}>
      <Badge tone={left <= 5 * 60_000 ? 'warn' : 'pos'} icon={left <= 5 * 60_000 ? 'warning' : 'clock'}>
        Token <span className="font-mono tabular-nums">{fmtCountdown(left)}</span>
      </Badge>
    </Link>
  )
}

function EngineChip() {
  const { engineOk, engineVersion, isMock } = useApp()
  if (engineOk === false) return <Badge tone="neg" title="The engine did not answer /health">Engine offline</Badge>
  if (engineOk === null) return null
  return <Badge tone={isMock ? 'info' : 'pos'} icon={isMock ? 'info' : 'check'} title={`Engine ${engineVersion}`}>{isMock ? 'Mock engine' : 'Engine online'}</Badge>
}

function Nav() {
  const pathname = usePathname()
  return (
    <header className="sticky top-0 z-40 border-b border-ex-line bg-ex-bg/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2">
        <Link href="/" className="flex items-center gap-2 rounded-md py-1 pr-2" aria-label="Exemplar home">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-ex-accent text-slate-950">
            <Icon name="spark" className="h-5 w-5" />
          </span>
          <span className="text-lg font-semibold tracking-tight text-ex-ink">Exemplar</span>
        </Link>
        <nav aria-label="Primary" className="order-3 -mx-1 w-full overflow-x-auto sm:order-none sm:mx-0 sm:w-auto sm:flex-1">
          <ul className="flex items-center gap-1">
            {LINKS.map((l) => {
              const active = pathname === l.href || pathname.startsWith(`${l.href}/`)
              return (
                <li key={l.href}>
                  <Link
                    href={l.href}
                    aria-current={active ? 'page' : undefined}
                    className={`inline-flex min-h-[36px] items-center rounded-md px-3 text-sm font-medium transition-colors ${
                      active ? 'bg-ex-raised text-ex-ink shadow-[inset_0_-2px_0_0_#22d3ee]' : 'text-ex-ink2 hover:bg-ex-panel hover:text-ex-ink'
                    }`}
                  >
                    {l.label}
                  </Link>
                </li>
              )
            })}
          </ul>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <EngineChip />
          <AuthChip />
        </div>
      </div>
    </header>
  )
}

export function Shell({ children }: { children: ReactNode }) {
  return (
    <AppProvider>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-ex-accent focus:px-4 focus:py-2 focus:font-semibold focus:text-slate-950"
      >
        Skip to main content
      </a>
      <Nav />
      <main id="main" tabIndex={-1} className="mx-auto min-h-[calc(100vh-9rem)] max-w-[1400px] px-4 py-6 focus:outline-none">
        {children}
      </main>
      <footer className="mx-auto max-w-[1400px] border-t border-ex-line px-4 py-4 text-xs text-ex-ink3">
        <p>
          Exemplar teaches Ring cameras new detectors by example. No facial recognition. Built on the MIT-licensed{' '}
          <a className="underline" href="https://github.com/AmazonAppDev/ring-api-helloworld">ring-api-helloworld</a> sample.
          Upload footage: &ldquo;Thief stealing our package&rdquo; by frollard, CC BY 4.0. Evaluation data: MEVA, CC BY 4.0.
        </p>
      </footer>
    </AppProvider>
  )
}
