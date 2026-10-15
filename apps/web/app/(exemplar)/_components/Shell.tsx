'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { ReactNode } from 'react'
import { AppProvider, useApp } from '../_lib/app'
import { fmtCountdown } from '../_lib/format'
import { useNow } from '../_lib/hooks'
import { StatusDot, cx, type Tone } from './ui'

const LINKS = [
  { href: '/library', label: 'Library' },
  { href: '/teach', label: 'Teach' },
  { href: '/rule', label: 'Rule' },
  { href: '/live', label: 'Live' },
  { href: '/eval', label: 'Eval' },
]

/** The product mark: three staggered bars, a miniature witness timeline. */
export function Mark({ className = 'h-6 w-6' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#2A6BE0" />
      <rect x="7" y="8" width="10" height="4" rx="2" fill="#fff" />
      <rect x="12" y="14" width="13" height="4" rx="2" fill="#fff" opacity=".85" />
      <rect x="9" y="20" width="9" height="4" rx="2" fill="#fff" opacity=".65" />
    </svg>
  )
}

function EngineStatus() {
  const { engineOk, engineVersion, isMock } = useApp()
  if (engineOk === null) return null
  const tone: Tone = engineOk === false ? 'neg' : isMock ? 'info' : 'pos'
  const text = engineOk === false ? 'Engine offline' : isMock ? 'Mock engine' : 'Engine online'
  return (
    <span className="inline-flex items-center text-xs text-ex-ink2" title={engineOk === false ? 'The engine did not answer /health' : `Engine ${engineVersion}`}>
      <StatusDot tone={tone} pulse={engineOk === false}>
        <span className="sr-only md:not-sr-only">{text}</span>
      </StatusDot>
    </span>
  )
}

function RingStatus() {
  const { auth } = useApp()
  const pathname = usePathname()
  const now = useNow(1000)
  const here = pathname === '/connect' ? 'page' : undefined
  const base = 'inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-ex-ink2 transition-colors hover:bg-ex-hover hover:text-ex-ink'

  if (!auth) return <span className="text-xs text-ex-ink3">Ring · checking</span>
  if (!auth.connected) {
    const expired = auth.expires_at_ms != null && auth.expires_at_ms <= now
    if (expired) {
      return (
        <span className="inline-flex items-center gap-1.5">
          <span className="text-xs text-ex-ink2"><StatusDot tone="neg">Ring · expired</StatusDot></span>
          <Link href="/connect" aria-current={here} className="btn btn-sm">Reconnect</Link>
        </span>
      )
    }
    return (
      <Link href="/connect" aria-current={here} className={base}>
        <StatusDot tone="warn">Connect Ring</StatusDot>
      </Link>
    )
  }
  if (auth.mode === 'oauth' || auth.expires_at_ms == null) {
    return <Link href="/connect" aria-current={here} className={base}><StatusDot tone="pos">Ring · linked</StatusDot></Link>
  }
  const left = auth.expires_at_ms - now
  const soon = left <= 5 * 60_000
  const mins = Math.max(1, Math.ceil(left / 60_000))
  return (
    <Link
      href="/connect"
      aria-current={here}
      className={cx(base, soon && 'text-ex-warn hover:text-ex-warn')}
      title="Ring Playground token"
    >
      <StatusDot tone={soon ? 'warn' : 'pos'}>
        Ring · <span className="tabular-nums">{soon ? fmtCountdown(left) : `${mins} min`}</span>
        <span className="sr-only"> left on the Playground token. Open Connect.</span>
      </StatusDot>
    </Link>
  )
}

function Nav() {
  const pathname = usePathname()
  return (
    <header className="sticky top-0 z-40 border-b border-ex-line bg-ex-bg">
      <div className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-x-2 gap-y-1 px-4 py-2 sm:px-6">
        <Link href="/" className="-ml-1 mr-2 flex items-center gap-2.5 rounded-md px-1 py-1" aria-label="Exemplar home">
          <Mark />
          <span className="text-md font-semibold tracking-tight text-ex-ink">Exemplar</span>
        </Link>
        <nav aria-label="Primary" className="order-3 -mx-1 w-full overflow-x-auto sm:order-none sm:mx-0 sm:w-auto sm:flex-1">
          <ul className="flex items-center gap-0.5">
            {LINKS.map((l) => {
              const active = pathname === l.href || pathname.startsWith(`${l.href}/`)
              return (
                <li key={l.href}>
                  <Link
                    href={l.href}
                    aria-current={active ? 'page' : undefined}
                    className={cx(
                      'inline-flex h-8 items-center rounded-md px-2.5 text-base font-medium transition-colors',
                      active ? 'bg-ex-hover text-ex-ink' : 'text-ex-ink2 hover:bg-ex-raised hover:text-ex-ink',
                    )}
                  >
                    {l.label}
                  </Link>
                </li>
              )
            })}
          </ul>
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <EngineStatus />
          <span aria-hidden="true" className="mx-1 hidden h-4 w-px bg-ex-line2 sm:block" />
          <RingStatus />
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
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-ex-accent focus:px-4 focus:py-2 focus:font-semibold focus:text-white"
      >
        Skip to main content
      </a>
      <Nav />
      <main id="main" tabIndex={-1} className="mx-auto min-h-[calc(100vh-10rem)] max-w-[1240px] px-4 pb-20 pt-10 focus:outline-none sm:px-6">
        {children}
      </main>
      <footer className="border-t border-ex-line">
        <div className="mx-auto flex max-w-[1240px] flex-col gap-1 px-4 py-6 text-xs leading-5 text-ex-ink3 sm:px-6">
          <p>Exemplar teaches Ring cameras new detectors by example. No facial recognition.</p>
          <p>
            Built on the MIT-licensed{' '}
            <a className="underline underline-offset-2 hover:text-ex-ink2" href="https://github.com/AmazonAppDev/ring-api-helloworld">ring-api-helloworld</a> sample.
            Upload footage: &ldquo;Thief stealing our package&rdquo; by frollard, CC BY 4.0. Evaluation data: MEVA, CC BY 4.0.
          </p>
        </div>
      </footer>
    </AppProvider>
  )
}
