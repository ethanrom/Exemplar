'use client'

import Link from 'next/link'
import { useApp } from '../_lib/app'
import { fmtCountdown, fmtInt, fmtUsd } from '../_lib/format'
import { useApi, useNow } from '../_lib/hooks'
import type { CostSummary } from '../_lib/types'
import { HomeExample } from '../_components/HomeExample'
import { Icon, type IconName } from '../_components/Icon'
import { StatusDot, cx, type Tone } from '../_components/ui'

const STORY: { n: string; title: string; text: string; href: string; link: string }[] = [
  {
    n: '01', title: 'Teach from examples', href: '/teach', link: 'Open Teach',
    text: 'Mark a few clips as yes or no. An agent sketches rules, a solver fits the numbers exactly, and it asks you the one question that settles the rest.',
  },
  {
    n: '02', title: 'Prove it with a false-alarm guarantee', href: '/rule', link: 'Open Rule',
    text: 'Backtest on your own history. Random labels calibrate the threshold, so false alarms stay under the rate you chose, or you are told plainly that you cannot say yet.',
  },
  {
    n: '03', title: 'Run it live, with explanations', href: '/live', link: 'Open Live',
    text: 'Deployed rules watch new Ring events. Clear matches and clear misses cost almost nothing, and every alert shows the facts and times that satisfied the rule.',
  },
]

const PIPELINE: { icon: IconName; title: string; text: string; tag: string }[] = [
  { icon: 'eye', title: 'Facts', text: 'Claude turns sampled frames into symbolic facts such as picks_up(p1, k1).', tag: 'Amazon Bedrock' },
  { icon: 'spark', title: 'Sketch', text: 'An agent proposes the structure of a rule, with numeric holes.', tag: 'Strands agent' },
  { icon: 'sliders', title: 'Z3', text: 'A solver fills every hole exactly, or proves that none fit.', tag: 'MaxSMT' },
  { icon: 'gauge', title: 'Robustness', text: 'Each rule scores how strongly it holds, not just yes or no.', tag: 'Signal temporal logic' },
  { icon: 'scale', title: 'Conformal', text: 'Random labels set the threshold for a false-alarm guarantee.', tag: 'Conformal prediction' },
  { icon: 'pulse', title: 'Monitor', text: 'Cheap checks first; only close calls reach the strong model.', tag: 'Ring live view' },
]

function Pipeline() {
  return (
    <section aria-labelledby="pipe-h" className="mt-24">
      <h2 id="pipe-h" className="text-lg font-semibold tracking-tight text-ex-ink">Under the hood</h2>
      <p className="mt-1 max-w-2xl text-base text-ex-ink2">
        The language model only writes a rule&rsquo;s structure. Everything that decides, proves and fires is exact, checked code.
      </p>
      <ol className="mt-8 grid gap-x-6 gap-y-8 sm:grid-cols-2 lg:grid-cols-6">
        {PIPELINE.map((p, i) => (
          <li key={p.title} className="relative">
            {i < PIPELINE.length - 1 && (
              <span aria-hidden="true" className="absolute left-12 right-[-12px] top-[18px] hidden h-px bg-gradient-to-r from-ex-line2 to-transparent lg:block" />
            )}
            <span className="relative grid h-9 w-9 place-items-center rounded-lg border border-ex-line2 bg-ex-raised text-ex-accent-ink">
              <Icon name={p.icon} className="h-4 w-4" />
            </span>
            <p className="mt-3 flex items-baseline gap-2 text-base font-semibold text-ex-ink">
              <span aria-hidden="true" className="font-mono text-xs font-normal text-ex-ink3">{i + 1}</span>
              {p.title}
            </p>
            <p className="mt-1 text-sm text-ex-ink2">{p.text}</p>
            <p className="mt-2 font-mono text-xs text-ex-ink3">{p.tag}</p>
          </li>
        ))}
      </ol>
    </section>
  )
}

function StatusStrip() {
  const { auth, engineOk, isMock, concepts } = useApp()
  const cost = useApi<CostSummary>('/monitor/cost')
  const now = useNow(1000)

  const engineTone: Tone = engineOk === false ? 'neg' : isMock ? 'info' : 'pos'
  const engineText = engineOk === null ? 'Checking' : engineOk === false ? 'Offline' : isMock ? 'Mock engine' : 'Online'

  let ring = 'Checking'
  let ringTone: Tone = 'neutral'
  if (auth) {
    if (!auth.connected) {
      const expired = auth.expires_at_ms != null && auth.expires_at_ms <= now
      ring = expired ? 'Token expired' : 'Not connected'
      ringTone = expired ? 'neg' : 'warn'
    } else if (auth.mode === 'oauth' || auth.expires_at_ms == null) {
      ring = 'Linked'
      ringTone = 'pos'
    } else {
      const left = auth.expires_at_ms - now
      ring = `${fmtCountdown(left)} left`
      ringTone = left <= 5 * 60_000 ? 'warn' : 'pos'
    }
  }
  const deployed = concepts.filter((c) => c.deployed_rule_id).length
  const c = cost.data

  const cell = 'min-w-0 bg-ex-panel'
  const link = 'group block px-4 py-3.5 transition-colors hover:bg-ex-raised'
  const arrow = <Icon name="arrow-right" className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
  return (
    <section aria-label="Status" className="mt-16">
      <ul className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-ex-line bg-ex-line lg:grid-cols-4">
        <li className={cell}>
          <div className="px-4 py-3.5">
            <p className="text-xs text-ex-ink3">Engine</p>
            <p className="mt-1 text-md font-medium text-ex-ink"><StatusDot tone={engineTone}>{engineText}</StatusDot></p>
          </div>
        </li>
        <li className={cell}>
          <Link href="/connect" className={link}>
            <p className="flex items-center justify-between text-xs text-ex-ink3">Ring token {arrow}</p>
            <p className={cx('mt-1 text-md font-medium tabular-nums', ringTone === 'neg' ? 'text-ex-neg' : 'text-ex-ink')}><StatusDot tone={ringTone}>{ring}</StatusDot></p>
          </Link>
        </li>
        <li className={cell}>
          <Link href="/live" className={link}>
            <p className="flex items-center justify-between text-xs text-ex-ink3">Rules watching live {arrow}</p>
            <p className="mt-1 text-md font-medium tabular-nums text-ex-ink">{deployed}</p>
          </Link>
        </li>
        <li className={cell}>
          <div className="px-4 py-3.5">
            <p className="text-xs text-ex-ink3">Events scored so far</p>
            <p className="mt-1 text-md font-medium tabular-nums text-ex-ink">
              {c ? fmtInt(c.events) : '-'}
              {c && c.events > 0 && <span className="ml-2 text-xs font-normal text-ex-ink3">{fmtUsd(c.per_event_usd)} per event</span>}
            </p>
          </div>
        </li>
      </ul>
    </section>
  )
}

export default function HomeScreen() {
  const { auth } = useApp()
  const started = !!auth?.connected
  return (
    <div>
      <section className="relative grid items-center gap-10 overflow-x-clip pt-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-14">
        <div aria-hidden="true" className="pointer-events-none absolute -top-24 left-1/2 h-[420px] w-[900px] -translate-x-1/3 bg-[radial-gradient(closest-side,rgba(88,142,255,0.10),transparent)]" />
        <div className="relative">
          <p className="inline-flex items-center gap-2 rounded-full border border-ex-line2 px-3 py-1 text-xs text-ex-ink2">
            <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-ex-accent-ink" /> Ring track · Amazon Developer Hackathon 2026
          </p>
          <h1 className="mt-6 text-3xl font-semibold tracking-tight text-ex-ink sm:text-4xl">
            Teach your Ring camera
            <span className="block text-ex-ink3">new detectors by example.</span>
          </h1>
          <p className="mt-6 max-w-xl text-md text-ex-ink2 sm:text-lg">
            Ring knows four things: person, vehicle, package, other motion. Show Exemplar a clip or two of what you actually care about. It learns a readable rule, proves its false-alarm rate on your own history, and watches live with an explanation for every alert.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link href={started ? '/library' : '/connect'} className="btn btn-primary btn-lg">
              Get started <Icon name="arrow-right" />
            </Link>
            <Link href="/eval" className="btn btn-lg">See the evidence</Link>
          </div>
        </div>
        <div className="relative"><HomeExample /></div>
      </section>

      <StatusStrip />

      <section aria-labelledby="story-h" className="mt-24">
        <h2 id="story-h" className="sr-only">How it works</h2>
        <ol className="grid divide-y divide-ex-line border-y border-ex-line md:grid-cols-3 md:divide-x md:divide-y-0">
          {STORY.map((s) => (
            <li key={s.n} className="group relative px-0 py-8 md:px-8 md:first:pl-0 md:last:pr-0">
              <p className="font-mono text-xs text-ex-ink3">{s.n}</p>
              <p className="mt-3 text-lg font-semibold leading-snug tracking-tight text-ex-ink">{s.title}</p>
              <p className="mt-2 text-base text-ex-ink2">{s.text}</p>
              <Link href={s.href} className="mt-5 inline-flex items-center gap-1 rounded text-sm font-medium text-ex-accent-ink hover:text-ex-ink">
                {s.link} <Icon name="arrow-right" className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
              </Link>
            </li>
          ))}
        </ol>
      </section>

      <Pipeline />
    </div>
  )
}
