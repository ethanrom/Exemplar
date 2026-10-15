'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useState } from 'react'
import { useApp } from '../_lib/app'
import { errorMessage, post, put } from '../_lib/api'
import { fmtCountdown, fmtDateTime } from '../_lib/format'
import { useApi, useNow } from '../_lib/hooks'
import type { Device, RingAuthStatus } from '../_lib/types'
import { Icon } from '../_components/Icon'
import { Alert, Badge, PageHeader, Spinner } from '../_components/ui'

const PLAYGROUND_URL = 'https://developer.amazon.com/ring/console/playground'
const TOKEN_LIFETIME_MS = 30 * 60_000

function TokenCard() {
  const { auth, setAuth, refreshAuth } = useApp()
  const now = useNow(1000)
  const [token, setToken] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const playground = auth?.mode === 'playground' && auth.expires_at_ms != null
  const left = playground ? auth!.expires_at_ms! - now : null
  const phase = !auth || !auth.mode ? 'none' : left == null ? 'oauth' : left <= 0 ? 'expired' : left <= 5 * 60_000 ? 'expiring' : 'ok'

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      const next = await put<RingAuthStatus>('/ring/auth', { access_token: token.trim() })
      setAuth(next)
      setToken('')
      setSaved(true)
      refreshAuth()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card" aria-labelledby="token-h">
      <h2 id="token-h" className="card-title">Developer Playground token</h2>
      <p className="mt-1 text-sm text-ex-ink2">
        Paste the read-only access token from the Ring Developer Playground. It is sent to the engine through this server and never stays in the browser.
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-[auto_1fr] sm:items-center">
        <div className="rounded-lg border border-ex-line bg-ex-bg px-4 py-3 text-center">
          <p className="text-xs text-ex-ink3">Token expires in</p>
          <p
            role="timer"
            aria-live="off"
            className={`font-mono text-4xl font-semibold tabular-nums ${
              phase === 'expired' ? 'text-red-300' : phase === 'expiring' ? 'text-amber-300' : 'text-ex-ink'
            }`}
          >
            {left == null ? '--:--' : fmtCountdown(left)}
          </p>
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {phase === 'ok' && <Badge tone="pos" icon="check">Connected</Badge>}
            {phase === 'expiring' && <Badge tone="warn">Expires soon</Badge>}
            {phase === 'expired' && <Badge tone="neg">Expired</Badge>}
            {phase === 'oauth' && <Badge tone="pos" icon="check">Connected with OAuth</Badge>}
            {phase === 'none' && <Badge tone="neutral" icon="info">Not connected</Badge>}
            {auth?.user_name && <span className="text-sm text-ex-ink2">{auth.user_name}</span>}
          </div>
          {playground && (
            <div className="mt-2" aria-hidden="true">
              <div className="h-2 overflow-hidden rounded-full bg-ex-bg">
                <div
                  className={`h-full rounded-full ${phase === 'expiring' ? 'bg-amber-400' : phase === 'expired' ? 'bg-red-400' : 'bg-ex-accent'}`}
                  style={{ width: `${Math.max(0, Math.min(1, (left ?? 0) / TOKEN_LIFETIME_MS)) * 100}%` }}
                />
              </div>
            </div>
          )}
          {auth?.issued_at_ms && playground && (
            <p className="mt-2 text-xs text-ex-ink3">
              Issued {fmtDateTime(auth.issued_at_ms)}. Ring only authorizes media from the first Playground token onward.
            </p>
          )}
        </div>
      </div>

      {phase === 'expiring' && (
        <div className="mt-3">
          <Alert tone="warn" title="This token is about to expire">
            Live rules stop receiving events when it does. Paste a fresh token from the Playground below.
          </Alert>
        </div>
      )}
      {phase === 'expired' && (
        <div className="mt-3">
          <Alert tone="neg" title="This token has expired">
            Open the Playground, copy a new access token and paste it below. Your library and rules are kept.
          </Alert>
        </div>
      )}

      <form onSubmit={save} className="mt-4">
        <label htmlFor="token-input" className="field-label">Playground access token</label>
        <div className="flex gap-2">
          <input
            id="token-input"
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
        <p id="token-help" className="mt-1 text-xs text-ex-ink3">
          Tokens last 30 minutes. Get one from the{' '}
          <a className="underline" href={PLAYGROUND_URL} target="_blank" rel="noopener noreferrer">
            Developer Playground<span className="sr-only"> (opens in a new tab)</span>
          </a>
          .
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button className="btn-primary" type="submit" disabled={busy || !token.trim()}>
            {busy ? 'Saving…' : phase === 'expired' || phase === 'expiring' ? 'Replace token' : 'Save token'}
          </button>
          <div aria-live="polite" className="text-sm">
            {saved && <span className="inline-flex items-center gap-1 text-green-300"><Icon name="check" /> Token saved. The 30 minute countdown has restarted.</span>}
          </div>
        </div>
        {error && <div className="mt-3"><Alert tone="neg" title="The engine rejected the token">{error}</Alert></div>}
      </form>
    </section>
  )
}

function OAuthCard() {
  const { auth } = useApp()
  const params = useSearchParams()
  const justLinked = params.get('oauth') === 'ok'
  const linked = auth?.mode === 'oauth' && auth.connected
  return (
    <section className="card" aria-labelledby="oauth-h">
      <h2 id="oauth-h" className="card-title">Ring account (OAuth)</h2>
      <p className="mt-1 text-sm text-ex-ink2">
        Link a real Ring account with the app-integration OAuth flow. Tokens refresh by rotation, so nothing expires mid-demo. The Playground token above is enough to try Exemplar.
      </p>
      {(justLinked || linked) && (
        <div className="mt-3"><Alert tone="info" title="Ring account linked">Devices and history now come from the linked account.</Alert></div>
      )}
      <div className="mt-4">
        {/* A plain navigation: the engine answers with a redirect to Ring's account-link page. */}
        <a className="btn" href="/api/engine/ring/oauth/start">
          <Icon name="link" /> Connect a Ring account
        </a>
      </div>
    </section>
  )
}

function DevicesCard() {
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
    <section className="card lg:col-span-2" aria-labelledby="dev-h">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="dev-h" className="card-title">Devices</h2>
        <div className="flex items-center gap-2">
          <button className="btn" type="button" onClick={sync} disabled={!connected || syncing}>
            <Icon name="refresh" /> {syncing ? 'Syncing…' : 'Sync history now'}
          </button>
          <Link className="btn" href="/library">Open Library <Icon name="chevron-right" /></Link>
        </div>
      </div>
      <div aria-live="polite" className="mt-2 min-h-[1.25rem] text-sm text-ex-ink2">{syncMsg}</div>

      {!connected && <p className="mt-2 text-sm text-ex-ink2">Connect first: devices appear here once a token is accepted.</p>}
      {connected && devices.loading && !devices.data && <div className="mt-3"><Spinner label="Loading devices" /></div>}
      {devices.error && (
        <div className="mt-3"><Alert tone="neg" title="Could not list devices">{devices.error.message}</Alert></div>
      )}
      {devices.data && devices.data.length === 0 && <p className="mt-2 text-sm text-ex-ink2">This token sees no devices.</p>}
      {devices.data && devices.data.length > 0 && (
        <ul className="mt-3 grid gap-3 md:grid-cols-2">
          {devices.data.map((d) => (
            <li key={d.id} className="flex items-start gap-3 rounded-lg border border-ex-line bg-ex-bg p-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-ex-raised text-ex-info"><Icon name="camera" className="h-5 w-5" /></span>
              <div className="min-w-0 flex-1">
                <p className="font-medium text-ex-ink">{d.name}</p>
                <p className="truncate font-mono text-xs text-ex-ink3" title={d.id}>{d.id}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {d.online != null && <Badge tone={d.online ? 'pos' : 'neg'} icon={d.online ? 'check' : 'cross'}>{d.online ? 'Online' : 'Offline'}</Badge>}
                  {(d.codecs ?? []).map((c) => <span key={c} className="chip font-mono">{c}</span>)}
                  <Badge tone={d.snapshot ? 'pos' : 'neutral'} icon={d.snapshot ? 'check' : 'minus'}>Snapshots</Badge>
                  <Badge tone={d.chime ? 'pos' : 'neutral'} icon={d.chime ? 'check' : 'minus'}>{d.chime ? 'Chime playback' : 'No chime'}</Badge>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default function ConnectScreen() {
  return (
    <>
      <PageHeader
        title="Connect Ring"
        subtitle="Exemplar reads your camera's event history and live view through the Ring API. All Ring calls happen on the server."
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <TokenCard />
        <OAuthCard />
        <DevicesCard />
      </div>
    </>
  )
}
