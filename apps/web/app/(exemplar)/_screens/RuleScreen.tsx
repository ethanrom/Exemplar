'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Fragment, useEffect, useMemo, useState } from 'react'
import { useApp } from '../_lib/app'
import { errorMessage, patch } from '../_lib/api'
import { fmtInt, fmtNum, fmtScore, fmtUsd } from '../_lib/format'
import { useApi } from '../_lib/hooks'
import type { Backtest, BacktestRow, CostSummary, RuleAction, RuleSummary } from '../_lib/types'
import { CalibrationPanel } from '../_components/CalibrationPanel'
import { ConceptSelect } from '../_components/ConceptSelect'
import { EventDialog } from '../_components/EventDialog'
import { EventThumb, ProvenanceBadge } from '../_components/EventBits'
import { Icon } from '../_components/Icon'
import { RuleHeadline, RuleMetrics, SuspectList } from '../_components/RuleCard'
import { Alert, Badge, Empty, PageHeader, Spinner, Stat } from '../_components/ui'
import { WitnessTimeline } from '../_components/WitnessTimeline'

// ---------------------------------------------------------------------------------------------
type Outcome = 'tp' | 'fp' | 'fn' | 'tn' | 'unlabelled-match' | 'unlabelled'

function outcomeOf(r: BacktestRow): Outcome {
  const v = r.label?.value
  if (!v) return r.matched ? 'unlabelled-match' : 'unlabelled'
  if (v === 'pos') return r.matched ? 'tp' : 'fn'
  return r.matched ? 'fp' : 'tn'
}

const OUTCOME: Record<Outcome, { label: string; tone: 'pos' | 'neg' | 'warn' | 'neutral' | 'info'; icon: 'check' | 'cross' | 'warning' | 'minus' | 'question' }> = {
  tp: { label: 'Correct match', tone: 'pos', icon: 'check' },
  tn: { label: 'Correct reject', tone: 'neutral', icon: 'check' },
  fp: { label: 'False alarm', tone: 'neg', icon: 'cross' },
  fn: { label: 'Missed', tone: 'warn', icon: 'warning' },
  'unlabelled-match': { label: 'Matched, no label', tone: 'info', icon: 'question' },
  unlabelled: { label: 'No label', tone: 'neutral', icon: 'minus' },
}

/** Diverging score bar: zero in the middle, tau marked. Always paired with the numeric value. */
function ScoreBar({ score, tau }: { score: number; tau: number }) {
  const pct = (x: number) => `${50 + Math.max(-0.5, Math.min(0.5, x)) * 100}%`
  const pos = score >= 0
  return (
    <span aria-hidden="true" className="relative block h-3 w-28 rounded bg-ex-bg">
      <span className="absolute inset-y-0 left-1/2 w-px bg-ex-ink3" />
      <span
        className={`absolute inset-y-[3px] rounded-sm ${score > tau ? 'bg-green-400' : pos ? 'bg-slate-400' : 'bg-red-400/80'}`}
        style={pos ? { left: '50%', width: `${Math.min(0.5, score) * 100}%` } : { right: '50%', width: `${Math.min(0.5, -score) * 100}%` }}
      />
      <span className="absolute -inset-y-0.5 w-0.5 bg-cyan-300" style={{ left: pct(tau) }} />
    </span>
  )
}

function BacktestTable({
  bt, rule, onOpen,
}: { bt: Backtest; rule: RuleSummary; onOpen: (eventId: string) => void }) {
  const [filter, setFilter] = useState<'all' | 'matches' | 'errors' | 'unlabelled'>('all')
  const [asc, setAsc] = useState(false)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const tau = bt.calibration.tau

  const rows = useMemo(() => {
    let r = bt.rows
    if (filter === 'matches') r = r.filter((x) => x.matched)
    if (filter === 'errors') r = r.filter((x) => ['fp', 'fn'].includes(outcomeOf(x)))
    if (filter === 'unlabelled') r = r.filter((x) => !x.label)
    return [...r].sort((a, b) => (asc ? a.score - b.score : b.score - a.score))
  }, [bt.rows, filter, asc])

  const c = bt.counts ?? {}
  const toggle = (id: string) => setOpen((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })

  return (
    <section aria-labelledby="bt-h" className="card">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="bt-h" className="card-title">Backtest on your history</h2>
          <p className="mt-1 text-sm text-ex-ink2">Every traced clip scored with this rule. No model calls: traces are cached.</p>
        </div>
        <div>
          <label htmlFor="bt-filter" className="field-label">Show</label>
          <select id="bt-filter" className="field" value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
            <option value="all">All clips ({bt.rows.length})</option>
            <option value="matches">Matches only</option>
            <option value="errors">False alarms and misses</option>
            <option value="unlabelled">Unlabelled clips</option>
          </select>
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Stat label="Correct matches" value={c.tp ?? 0} />
        <Stat label="False alarms" value={c.fp ?? 0} />
        <Stat label="Missed" value={c.fn ?? 0} />
        <Stat label="Correct rejects" value={c.tn ?? 0} />
        <Stat label="Matched, unlabelled" value={c.unlabelled_matches ?? 0} hint="worth a look" />
      </dl>
      <p className="mt-1 text-xs text-ex-ink3">Counts use all your labels. Only random labels feed the guarantee.</p>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[760px] border-separate border-spacing-0 text-sm">
          <caption className="sr-only">Backtest results, one row per clip. Press the Why button on a matching row to see its witness timeline.</caption>
          <thead>
            <tr className="text-left text-xs text-ex-ink3">
              <th scope="col" className="border-b border-ex-line py-2 pr-2 font-medium">Clip</th>
              <th scope="col" className="border-b border-ex-line py-2 pr-2 font-medium">Your label</th>
              <th scope="col" className="border-b border-ex-line py-2 pr-2 font-medium" aria-sort={asc ? 'ascending' : 'descending'}>
                <button type="button" className="inline-flex min-h-[28px] items-center gap-1 rounded font-medium hover:text-ex-ink" onClick={() => setAsc(!asc)}>
                  Score ρ <Icon name="chevron" className={`h-3 w-3 ${asc ? 'rotate-180' : ''}`} />
                  <span className="sr-only">, press to sort {asc ? 'high to low' : 'low to high'}</span>
                </button>
              </th>
              <th scope="col" className="border-b border-ex-line py-2 pr-2 font-medium">Result</th>
              <th scope="col" className="border-b border-ex-line py-2 pr-2 font-medium">Outcome</th>
              <th scope="col" className="border-b border-ex-line py-2 font-medium"><span className="sr-only">Witness</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const o = OUTCOME[outcomeOf(r)]
              const isOpen = open.has(r.clip_id)
              const flag = ['fp', 'fn'].includes(outcomeOf(r))
              return (
                <Fragment key={r.clip_id}>
                  <tr className={flag ? 'bg-amber-950/25' : ''}>
                    <td className="border-b border-ex-line py-2 pr-2">
                      <div className="flex items-center gap-2">
                        {r.event && (
                          <button type="button" className="shrink-0 overflow-hidden rounded" onClick={() => onOpen(r.event!.id)} aria-label={`View clip: ${r.event.summary ?? r.clip_id}`}>
                            <EventThumb event={r.event} className="h-[36px] w-16" />
                          </button>
                        )}
                        <span className="line-clamp-2 max-w-[22rem] text-ex-ink">{r.event?.summary ?? r.clip_id}</span>
                      </div>
                    </td>
                    <td className="border-b border-ex-line py-2 pr-2">
                      {r.label ? <ProvenanceBadge label={r.label} /> : <span className="text-ex-ink3">none</span>}
                    </td>
                    <td className="border-b border-ex-line py-2 pr-2">
                      <div className="flex items-center gap-2">
                        <ScoreBar score={r.score} tau={tau} />
                        <span className="font-mono text-xs tabular-nums text-ex-ink">{fmtScore(r.score)}</span>
                      </div>
                    </td>
                    <td className="border-b border-ex-line py-2 pr-2">
                      {r.matched ? <Badge tone="pos" icon="check">Match</Badge> : <Badge tone="neutral" icon="minus">No match</Badge>}
                    </td>
                    <td className="border-b border-ex-line py-2 pr-2"><Badge tone={o.tone} icon={o.icon}>{o.label}</Badge></td>
                    <td className="border-b border-ex-line py-2 text-right">
                      {r.witness && (
                        <button
                          type="button"
                          className="btn !min-h-[32px] !px-2 text-xs"
                          aria-expanded={isOpen}
                          aria-controls={`wit-${r.clip_id}`}
                          onClick={() => toggle(r.clip_id)}
                        >
                          Why <Icon name="chevron" className={`h-3 w-3 ${isOpen ? 'rotate-180' : ''}`} />
                          <span className="sr-only">: {r.event?.summary ?? r.clip_id}</span>
                        </button>
                      )}
                    </td>
                  </tr>
                  {r.witness && isOpen && (
                    <tr>
                      <td colSpan={6} id={`wit-${r.clip_id}`} className="border-b border-ex-line bg-ex-bg/50 p-2">
                        <WitnessTimeline witness={r.witness} durationMs={r.event?.duration_ms} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <div className="mt-3"><Empty title="No clips in this view" /></div>}
      <p className="mt-2 text-xs text-ex-ink3">
        The cyan tick on each bar is τ = {fmtNum(tau)}{bt.calibration.guarantee ? '' : ' (no guarantee yet: the rule fires on any score above 0)'}.
        {' '}Rule {rule.id}.
      </p>
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
const ACTIONS: { id: RuleAction; label: string; hint: string }[] = [
  { id: 'ui', label: 'Notify in Exemplar', hint: 'Shows up on the Live screen and in the action log' },
  { id: 'webhook_out', label: 'Send a webhook', hint: 'POSTs the witness to a URL you configure' },
  { id: 'slack', label: 'Post to Slack', hint: 'Needs a Slack webhook in the engine settings' },
  { id: 'chime', label: 'Play a chime on the camera', hint: 'Ring early-access feature, behind a flag; the Playground device has no chime slot' },
]

function DeployCard({
  rule, onChanged, hasGuarantee,
}: { rule: RuleSummary; onChanged: (r: RuleSummary) => void; hasGuarantee: boolean }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const deployed = rule.status === 'deployed'
  const actions = new Set(rule.actions ?? [])

  async function setStatus(next: 'deployed' | 'selected') {
    setBusy(true); setError(null)
    try { onChanged(await patch<RuleSummary>(`/rules/${rule.id}`, { status: next })) } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function toggleAction(id: RuleAction) {
    const next = new Set(actions)
    if (next.has(id)) next.delete(id); else next.add(id)
    setBusy(true); setError(null)
    try { onChanged(await patch<RuleSummary>(`/rules/${rule.id}`, { actions: Array.from(next) })) } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }

  return (
    <section aria-labelledby="dep-h" className="card">
      <h2 id="dep-h" className="card-title">Deploy</h2>
      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={deployed}
          aria-labelledby="dep-label"
          disabled={busy}
          onClick={() => setStatus(deployed ? 'selected' : 'deployed')}
          className={`relative inline-flex h-8 w-14 shrink-0 items-center rounded-full border-2 transition-colors ${deployed ? 'border-green-300 bg-green-500' : 'border-ex-ink3 bg-ex-raised'}`}
        >
          <span aria-hidden="true" className={`absolute grid h-6 w-6 place-items-center rounded-full bg-white text-slate-900 transition-all ${deployed ? 'left-[26px]' : 'left-0.5'}`}>
            <Icon name={deployed ? 'check' : 'minus'} className="h-4 w-4" />
          </span>
        </button>
        <div>
          <p id="dep-label" className="font-medium text-ex-ink">{deployed ? 'Live: scoring new events' : 'Off: not scoring new events'}</p>
          <p className="text-xs text-ex-ink3">One rule per concept is live at a time; deploying replaces the current one.</p>
        </div>
      </div>
      {!hasGuarantee && (
        <div className="mt-3"><Alert tone="warn" title="Deploying without a guarantee">This rule will fire on any score above 0. Label random clips first if you want a bounded false-alarm rate.</Alert></div>
      )}
      {deployed && (
        <p className="mt-3 text-sm"><Link href="/live" className="inline-flex items-center gap-1 text-ex-info underline">Watch it on the Live screen <Icon name="chevron-right" className="h-3 w-3" /></Link></p>
      )}

      <fieldset className="mt-4">
        <legend className="text-sm font-semibold text-ex-ink">When it fires</legend>
        <div className="mt-2 grid gap-2">
          {ACTIONS.map((a) => (
            <label key={a.id} className="flex cursor-pointer items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1 h-4 w-4 accent-cyan-400" checked={actions.has(a.id)} disabled={busy} onChange={() => toggleAction(a.id)} />
              <span><span className="text-ex-ink">{a.label}</span><span className="block text-xs text-ex-ink3">{a.hint}</span></span>
            </label>
          ))}
        </div>
      </fieldset>
      {error && <div className="mt-3"><Alert tone="neg">{error}</Alert></div>}
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
export default function RuleScreen() {
  const { conceptId, setConceptId, refreshConcepts } = useApp()
  const params = useSearchParams()
  const ruleParam = params.get('rule')
  const list = useApi<RuleSummary[]>(conceptId ? `/concepts/${conceptId}/rules` : null)
  const [picked, setPicked] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [updated, setUpdated] = useState<RuleSummary | null>(null)

  // A ?rule= link wins; load it to learn which concept it belongs to.
  const linked = useApi<RuleSummary>(ruleParam ? `/rules/${encodeURIComponent(ruleParam)}` : null)
  useEffect(() => {
    if (linked.data) {
      setPicked(linked.data.id)
      if (linked.data.concept_id !== conceptId) setConceptId(linked.data.concept_id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linked.data?.id])

  const rules = list.data ?? []
  const ruleId = useMemo(() => {
    if (picked && (rules.some((r) => r.id === picked) || linked.data?.id === picked)) return picked
    return rules.find((r) => r.status === 'deployed')?.id ?? rules[0]?.id ?? null
  }, [picked, rules, linked.data?.id])

  const rule = useApi<RuleSummary>(ruleId ? `/rules/${encodeURIComponent(ruleId)}` : null)
  const backtest = useApi<Backtest>(ruleId ? `/rules/${encodeURIComponent(ruleId)}/backtest` : null)
  const cost = useApi<CostSummary>('/monitor/cost')
  const events = useMemo(() => new Map(backtest.data?.rows.filter((r) => r.event).map((r) => [r.clip_id, r.event!]) ?? []), [backtest.data])

  useEffect(() => { setUpdated(null) }, [ruleId])
  const current = updated && updated.id === ruleId ? updated : rule.data
  const cal = backtest.data?.calibration ?? current?.calibration ?? null

  function onChanged(r: RuleSummary) {
    setUpdated(r)
    list.reload(); refreshConcepts(); backtest.reload()
  }

  return (
    <>
      <PageHeader title="Rule" subtitle="Check a rule against your history before it goes live: what it matches, what it gets wrong, and how many false alarms to expect." />

      <div className="card mb-4 flex flex-wrap items-end gap-3">
        <ConceptSelect id="rule-concept" label="Concept" />
        <div className="min-w-[260px] flex-1">
          <label htmlFor="rule-pick" className="field-label">Rule</label>
          <select id="rule-pick" className="field" value={ruleId ?? ''} onChange={(e) => setPicked(e.target.value)} disabled={rules.length === 0}>
            {rules.length === 0 && <option value="">No rules yet</option>}
            {rules.map((r, i) => (
              <option key={r.id} value={r.id}>{i + 1}. {r.english.length > 90 ? `${r.english.slice(0, 88)}…` : r.english}{r.status === 'deployed' ? ' (live)' : ''}</option>
            ))}
          </select>
        </div>
      </div>

      {list.loading && !list.data && <Spinner label="Loading rules" />}
      {!ruleId && !list.loading && (
        <Empty title="No rule to show yet">
          Teach this concept first: <Link className="underline" href="/teach">go to Teach</Link>.
        </Empty>
      )}
      {rule.error && <Alert tone="neg" title="Could not load the rule">{rule.error.message}</Alert>}

      {current && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <div className="grid content-start gap-4">
            <section className="card" aria-label="Rule">
              <RuleHeadline rule={current} large />
              <RuleMetrics rule={current} />
              <SuspectList rule={current} events={events} onInspect={setOpenId} />
            </section>
            {backtest.loading && !backtest.data && <Spinner label="Scoring your history" />}
            {backtest.error && <Alert tone="neg" title="Backtest failed">{backtest.error.message}</Alert>}
            {backtest.data && <BacktestTable bt={backtest.data} rule={current} onOpen={setOpenId} />}
          </div>
          <div className="grid content-start gap-4">
            {cal && conceptId && <CalibrationPanel cal={cal} conceptId={current.concept_id} />}
            <section className="card" aria-labelledby="cost-h">
              <h2 id="cost-h" className="card-title">Cost per event</h2>
              {cost.data ? (
                <>
                  <p className="mt-2 text-3xl font-semibold text-ex-ink">{fmtUsd(cost.data.per_event_usd)}<span className="ml-1 text-sm font-normal text-ex-ink3">per live event so far</span></p>
                  <dl className="mt-3 grid grid-cols-3 gap-2">
                    <Stat label="Dropped free (stage 0)" value={fmtInt(cost.data.stage0_dropped)} />
                    <Stat label="Scored (stage 1)" value={fmtInt(cost.data.stage1_scored)} />
                    <Stat label="Escalated (stage 2)" value={fmtInt(cost.data.stage2_escalated)} />
                  </dl>
                </>
              ) : cost.loading ? <div className="mt-2"><Spinner /></div> : <p className="mt-2 text-sm text-ex-ink2">No live events yet.</p>}
              <p className="mt-3 text-xs text-ex-ink3">Backtests are free: they reuse cached traces. Only new events cost a model call, and only those scoring within δ of τ use the stronger model.</p>
            </section>
            <DeployCard rule={current} onChanged={onChanged} hasGuarantee={!!cal?.guarantee} />
          </div>
        </div>
      )}
      <EventDialog eventId={openId} onClose={() => setOpenId(null)} />
    </>
  )
}
