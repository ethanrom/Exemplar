'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useRef, useState } from 'react'
import { useApp } from '../_lib/app'
import { ApiError, errorMessage, get, post, put } from '../_lib/api'
import { fmtCountdown, fmtDateTime } from '../_lib/format'
import { useApi, useNow } from '../_lib/hooks'
import type { Device, RingAuthStatus } from '../_lib/types'
import { Icon } from '../_components/Icon'
import { Alert, Badge, PageHeader, Skeleton, StatusDot, cx } from '../_components/ui'

const PLAYGROUND_URL = 'https://developer.amazon.com/ring/console/playground'
const TOKEN_LIFETIME_MS = 30 * 60_000

function TokenOption() {
  const { auth, setAuth, refreshAuth } = useApp()
  const now = useNow(1000)
  const [token, setToken] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const playground = auth?.mode === 'playground' && auth.expires_at_ms != null
  const left = playground ? auth!.expires_at_ms! - now : null
  const phase = !auth || !auth.mode ? 'none' : left == null ? 'oauth' : left <= 0 ? 'expired' : left <= 5 * 60_000 ? 'expiring' : 'ok'

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      // The web server keeps the token for the WHEP proxy and forwards it to the engine itself
      // (PUT /api/ring/token). Where that route does not exist (UI built against the mock engine
      // only) fall back to the engine's own PUT /ring/auth through the proxy.
      const res = await fetch('/api/ring/token', {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ access_token: token.trim() }),
        cache: 'no-store',
      })
      if (res.status === 404) {
        await put<RingAuthStatus>('/ring/auth', { access_token: token.trim() })
      } else if (!res.ok) {
        const body = await res.json().catch(() => null)
        throw new ApiError(res.status, body?.error || `The server rejected the token (${res.status})`)
      }
      const next = await get<RingAuthStatus>('/ring/auth')
      setAuth(next)
      setToken('')
      setSaved(true)
      refreshAuth()
      inputRef.current?.focus()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const tone = phase === 'expired' ? 'neg' : phase === 'expiring' ? 'warn' : phase === 'none' ? 'neutral' : 'pos'
  const label =
    phase === 'ok' ? 'Connected' : phase === 'expiring' ? 'Expires soon' : phase === 'expired' ? 'Expired' : phase === 'oauth' ? 'Connected with OAuth' : 'Not connected'
  const pct = Math.max(0, Math.min(1, (left ?? 0) / TOKEN_LIFETIME_MS)) * 100

  return (
    <section aria-labelledby="token-h" className="p-6 sm:p-8">
      <p className="text-xs font-medium text-ex-accent-ink">Fastest way to try Exemplar</p>
      <h2 id="token-h" className="mt-1.5 text-lg font-semibold tracking-tight text-ex-ink">Developer Playground token</h2>
      <p className="mt-1.5 text-sm text-ex-ink2">
        Paste the read-only access token from the Ring Developer Playground. It is sent to the engine through this server and never stays in the browser.
      </p>

      <div className="mt-6 rounded-xl border border-ex-line bg-ex-bg p-5">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-xs text-ex-ink3">Token expires in</p>
            <p
              role="timer"
              aria-live="off"
              className={cx(
                'mt-1 font-mono text-4xl font-medium leading-none tracking-tight tabular-nums',
                phase === 'expired' ? 'text-ex-neg' : phase === 'expiring' ? 'text-ex-warn' : 'text-ex-ink',
              )}
            >
              {left == null ? '--:--' : fmtCountdown(left)}
            </p>
          </div>
          <div className="pb-0.5 text-sm text-ex-ink2">
            <StatusDot tone={tone}>{label}</StatusDot>
            {auth?.user_name && <span className="ml-2 text-ex-ink3">{auth.user_name}</span>}
          </div>
        </div>
        {playground && (
          <div className="mt-4" aria-hidden="true">
            <div className="h-1 overflow-hidden rounded-full bg-white/[0.08]">
              <div
                className={cx('h-full rounded-full transition-[width] duration-1000 ease-linear', phase === 'expiring' ? 'bg-ex-warn' : phase === 'expired' ? 'bg-ex-neg' : 'bg-ex-accent-ink')}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}
        {auth?.issued_at_ms && playground && (
          <p className="mt-3 text-xs text-ex-ink3">
            Issued {fmtDateTime(auth.issued_at_ms)}. Ring only authorizes media from the first Playground token onward.
          </p>
        )}
      </div>

      {phase === 'expiring' && (
        <div className="mt-4">
          <Alert tone="warn" title="This token is about to expire">
            Live rules stop receiving events when it does. Paste a fresh token from the Playground below.
          </Alert>
        </div>
      )}
      {phase === 'expired' && (
        <div className="mt-4">
          <Alert tone="neg" title="This token has expired">
            Open the Playground, copy a new access token and paste it below. Your library and rules are kept.
          </Alert>
        </div>
      )}

      <form onSubmit={save} className="mt-6">
        <label htmlFor="token-input" className="field-label">Playground access token</label>
        <div className="flex gap-2">
          <input
            id="token-input"
            ref={inputRef}
            className="field font-mono"
            type={show ? 'text' : 'password'}
            autoComplete="off"
            spellCheck={false}
            value={token}
            onChange={(e) => setToken(e.target.value)}
            aria-describedby="token-help"
            placeholder="ava.v1:read token"
          />
          <button type="button" className="btn" aria-pressed={show} onClick={() => setShow(!show)}>
            <Icon name="eye" /> {show ? 'Hide' : 'Show'}
          </button>
        </div>
        <p id="token-help" className="mt-2 text-xs text-ex-ink3">
          Tokens last 30 minutes. Get one from the{' '}
          <a className="link" href={PLAYGROUND_URL} target="_blank" rel="noopener noreferrer">
            Developer Playground<span className="sr-only"> (opens in a new tab)</span>
          </a>
          .
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button className="btn-primary" type="submit" disabled={busy || !token.trim()}>
            {busy ? 'Saving…' : phase === 'expired' || phase === 'expiring' ? 'Replace token' : 'Save token'}
          </button>
          <div aria-live="polite" className="text-sm">
            {saved && <span className="inline-flex items-center gap-1.5 text-ex-pos"><Icon name="check" /> Token saved. The 30 minute countdown has restarted.</span>}
          </div>
        </div>
        {error && <div className="mt-4"><Alert tone="neg" title="The engine rejected the token">{error}</Alert></div>}
      </form>
    </section>
  )
}

function OAuthOption() {
  const { auth } = useApp()
  const params = useSearchParams()
  const justLinked = params.get('oauth') === 'ok'
  const linked = auth?.mode === 'oauth' && auth.connected
  return (
    <section aria-labelledby="oauth-h" className="flex flex-col p-6 sm:p-8">
      <p className="text-xs font-medium text-ex-ink3">For a real home</p>
      <h2 id="oauth-h" className="mt-1.5 text-lg font-semibold tracking-tight text-ex-ink">Ring account (OAuth)</h2>
      <p className="mt-1.5 text-sm text-ex-ink2">
        Link a real Ring account with the app-integration OAuth flow. Tokens refresh by rotation, so nothing expires mid-demo. The Playground token is enough to try Exemplar.
      </p>
      <ul className="mt-6 grid gap-3 text-sm text-ex-ink2">
        {['You sign in on Ring, never here', 'Access is read-only: history, snapshots, live view', 'Refresh tokens rotate on every use'].map((t) => (
          <li key={t} className="flex items-start gap-2.5"><Icon name="check" className="mt-0.5 h-4 w-4 text-ex-ink3" />{t}</li>
        ))}
      </ul>
      {(justLinked || linked) && (
        <div className="mt-5"><Alert tone="info" title="Ring account linked">Devices and history now come from the linked account.</Alert></div>
      )}
      <div className="mt-auto pt-8">
        {/* A plain navigation: the engine answers with a redirect to Ring's account-link page. */}
        <a className="btn" href="/api/engine/ring/oauth/start">
          <Icon name="link" /> Connect a Ring account
        </a>
      </div>
    </section>
  )
}

function DeviceImage({ device }: { device: Device }) {
  const [failed, setFailed] = useState(false)
  return (
    <span className="grid h-28 w-28 shrink-0 place-items-center rounded-xl bg-ex-raised p-3">
      {device.image_url && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={device.image_url} alt={`${device.name}, product image`} onError={() => setFailed(true)} className="h-full w-full object-contain" />
      ) : (
        <Icon name="camera" className="h-8 w-8 text-ex-ink3" />
      )}
    </span>
  )
}

function Capability({ on, children }: { on: boolean; children: React.ReactNode }) {
  return (
    <li className={cx('inline-flex items-center gap-1.5 text-sm', on ? 'text-ex-ink2' : 'text-ex-ink3')}>
      <Icon name={on ? 'check' : 'minus'} className={cx('h-3.5 w-3.5', on && 'text-ex-pos')} />
      {children}
    </li>
  )
}

function DevicesSection() {
  const { auth } = useApp()
  const connected = !!auth?.connected
  const devices = useApi<Device[]>(connected ? '/ring/devices' : null)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState<string | null>(null)

  async function sync() {
    setSyncing(true)
    setSyncMsg(null)
    try {
      const r = await post<{ new_events?: number }>('/ring/sync')
      const n = r?.new_events ?? 0
      setSyncMsg(n === 0 ? 'Up to date: no new events.' : `${n} new event${n === 1 ? '' : 's'} are being downloaded and read.`)
    } catch (err) {
      setSyncMsg(errorMessage(err))
    } finally {
      setSyncing(false)
    }
  }

  return (
    <section aria-labelledby="dev-h" className="mt-12">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="dev-h" className="text-md font-semibold tracking-tight text-ex-ink">Devices</h2>
          <p className="mt-0.5 text-sm text-ex-ink2">The cameras this token can see.</p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn" type="button" onClick={sync} disabled={!connected || syncing}>
            <Icon name="refresh" className={cx('h-4 w-4', syncing && 'motion-safe:animate-spin')} /> {syncing ? 'Syncing…' : 'Sync history now'}
          </button>
          <Link className="btn" href="/library">Open Library <Icon name="arrow-right" /></Link>
        </div>
      </div>
      <div aria-live="polite" className={cx('text-sm text-ex-ink2', syncMsg && 'mb-3')}>{syncMsg}</div>

      {!connected && (
        <div className="flex items-center gap-3 rounded-xl border border-ex-line bg-ex-panel px-5 py-6 text-sm text-ex-ink2">
          <span aria-hidden="true" className="grid h-9 w-9 place-items-center rounded-lg bg-ex-raised text-ex-ink3"><Icon name="camera" className="h-4 w-4" /></span>
          Connect first: devices appear here once a token is accepted.
        </div>
      )}
      {connected && devices.loading && !devices.data && <Skeleton className="h-40 rounded-xl" label="Loading devices" />}
      {devices.error && <Alert tone="neg" title="Could not list devices">{devices.error.message}</Alert>}
      {devices.data && devices.data.length === 0 && <p className="text-sm text-ex-ink2">This token sees no devices.</p>}
      {devices.data && devices.data.length > 0 && (
        <ul className="grid gap-4 md:grid-cols-2">
          {devices.data.map((d) => (
            <li key={d.id} className="flex items-start gap-5 rounded-xl border border-ex-line bg-ex-panel p-5">
              <DeviceImage device={d} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <p className="text-md font-semibold tracking-tight text-ex-ink">{d.name}</p>
                  {d.online != null && <span className="text-xs text-ex-ink2"><StatusDot tone={d.online ? 'pos' : 'neg'}>{d.online ? 'Online' : 'Offline'}</StatusDot></span>}
                </div>
                <p className="mt-0.5 font-mono text-xs text-ex-ink3">Device ID ····{d.id.slice(-6)}</p>
                <ul className="mt-4 flex flex-wrap gap-x-5 gap-y-1.5" aria-label="Capabilities">
                  <Capability on={!!d.snapshot}>Snapshots</Capability>
                  <Capability on={!!d.chime}>{d.chime ? 'Chime playback' : 'No chime'}</Capability>
                  {(d.codecs ?? []).length > 0 && (
                    <li className="inline-flex items-center gap-1.5 text-sm text-ex-ink2">
                      <Icon name="film" className="h-3.5 w-3.5 text-ex-ink3" />
                      <span className="font-mono text-xs">{(d.codecs ?? []).join(', ')}</span>
                    </li>
                  )}
                </ul>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default function ConnectScreen() {
  const { auth } = useApp()
  return (
    <>
      <PageHeader
        title="Connect Ring"
        subtitle="Exemplar reads your camera's event history and live view through the Ring API. All Ring calls happen on the server."
        actions={auth?.connected ? <Badge tone="pos" icon="check">Connected</Badge> : undefined}
      />
      <div className="grid divide-y divide-ex-line overflow-hidden rounded-xl border border-ex-line bg-ex-panel lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:divide-x lg:divide-y-0">
        <TokenOption />
        <OAuthOption />
      </div>
      <DevicesSection />
    </>
  )
}
