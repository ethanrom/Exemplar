'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Fragment, useEffect, useMemo, useState } from 'react'
import { useApp } from '../_lib/app'
import { errorMessage, patch } from '../_lib/api'
import { fmtInt, fmtNum, fmtScore, fmtUsd } from '../_lib/format'
import { useApi, type ApiState } from '../_lib/hooks'
import type { Backtest, BacktestRow, CostSummary, RuleAction, RuleSummary } from '../_lib/types'
import { CalibrationPanel, GuaranteeBadge } from '../_components/CalibrationPanel'
import { ConceptSelect } from '../_components/ConceptSelect'
import { DslBlock } from '../_components/Dsl'
import { EventDialog } from '../_components/EventDialog'
import { EventThumb, LabelIndicator } from '../_components/EventBits'
import { Icon, type IconName } from '../_components/Icon'
import { RuleMetrics, SuspectList } from '../_components/RuleCard'
import { Alert, Empty, PageHeader, Segmented, Skeleton, Stat, StatStrip, Switch, TONE_TEXT, cx, type Tone } from '../_components/ui'
import { WitnessTimeline } from '../_components/WitnessTimeline'

// ---------------------------------------------------------------------------------------------
type Outcome = 'tp' | 'fp' | 'fn' | 'tn' | 'unlabelled-match' | 'unlabelled'

function outcomeOf(r: BacktestRow): Outcome {
  const v = r.label?.value
  if (!v) return r.matched ? 'unlabelled-match' : 'unlabelled'
  if (v === 'pos') return r.matched ? 'tp' : 'fn'
  return r.matched ? 'fp' : 'tn'
}

const OUTCOME: Record<Outcome, { label: string; tone: Tone; icon: IconName }> = {
  tp: { label: 'Correct match', tone: 'pos', icon: 'check' },
  tn: { label: 'Correct reject', tone: 'neutral', icon: 'check' },
  fp: { label: 'False alarm', tone: 'neg', icon: 'cross' },
  fn: { label: 'Missed', tone: 'warn', icon: 'warning' },
  'unlabelled-match': { label: 'Matched, no label', tone: 'info', icon: 'question' },
  unlabelled: { label: 'No match', tone: 'neutral', icon: 'minus' },
}

/** Diverging score bar: zero in the middle, tau marked. Always paired with the numeric value. */
function ScoreBar({ score, tau }: { score: number; tau: number }) {
  const pct = (x: number) => `${50 + Math.max(-0.5, Math.min(0.5, x)) * 100}%`
  const pos = score >= 0
  const fires = score > tau
  return (
    <span aria-hidden="true" className="relative block h-5 w-32 shrink-0">
      <span className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-white/[0.08]" />
      <span className="absolute inset-y-[5px] left-1/2 w-px bg-ex-ink3" />
      <span
        className={cx('absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full', fires ? 'bg-ex-accent-ink' : 'bg-ex-ink3')}
        style={pos ? { left: '50%', width: `${Math.min(0.5, score) * 100}%` } : { right: '50%', width: `${Math.min(0.5, -score) * 100}%` }}
      />
      <span className="absolute inset-y-0 w-0.5 rounded-full bg-ex-ink" style={{ left: `calc(${pct(tau)} - 1px)` }} />
    </span>
  )
}

type Filter = 'all' | 'matches' | 'errors' | 'unlabelled'

function BacktestTable({
  bt, rule, onOpen,
}: { bt: Backtest; rule: RuleSummary; onOpen: (eventId: string) => void }) {
  const [filter, setFilter] = useState<Filter>('all')
  const [asc, setAsc] = useState(false)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [limit, setLimit] = useState(14)
  const tau = bt.calibration.tau

  const rows = useMemo(() => {
    let r = bt.rows
    if (filter === 'matches') r = r.filter((x) => x.matched)
    if (filter === 'errors') r = r.filter((x) => ['fp', 'fn'].includes(outcomeOf(x)))
    if (filter === 'unlabelled') r = r.filter((x) => !x.label)
    return [...r].sort((a, b) => (asc ? a.score - b.score : b.score - a.score))
  }, [bt.rows, filter, asc])

  const toggle = (id: string) => setOpen((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const th = 'border-b border-ex-line px-3 py-2.5 text-left text-xs font-medium text-ex-ink3'

  return (
    <section aria-labelledby="bt-h">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div>
          <h2 id="bt-h" tabIndex={-1} className="text-md font-semibold tracking-tight text-ex-ink focus:outline-none">Backtest on your history</h2>
          <p className="mt-0.5 text-sm text-ex-ink2">Every traced clip scored with this rule. No model calls: traces are cached.</p>
        </div>
        <div className="max-w-full overflow-x-auto">
          <Segmented
            label="Show"
            value={filter}
            onChange={(v) => { setFilter(v); setLimit(14) }}
            options={[
              { value: 'all', label: 'All', count: bt.rows.length },
              { value: 'matches', label: 'Matches' },
              { value: 'errors', label: 'Errors' },
              { value: 'unlabelled', label: 'Unlabelled' },
            ]}
          />
        </div>
      </div>

      <div className="relative overflow-x-auto rounded-xl border border-ex-line bg-ex-panel">
        <table className="w-full min-w-[720px] border-separate border-spacing-0 text-sm">
          <caption className="sr-only">Backtest results, one row per clip. Press the Why button on a matching row to see its witness timeline.</caption>
          <thead>
            <tr>
              <th scope="col" className={th}>Clip</th>
              <th scope="col" className={th}>Your label</th>
              <th scope="col" className={th} aria-sort={asc ? 'ascending' : 'descending'}>
                <button type="button" className="-ml-1 inline-flex min-h-[28px] items-center gap-1 rounded px-1 font-medium hover:text-ex-ink" onClick={() => setAsc(!asc)}>
                  Score ρ <Icon name="chevron" className={cx('h-3 w-3', asc && 'rotate-180')} />
                  <span className="sr-only">, press to sort {asc ? 'high to low' : 'low to high'}</span>
                </button>
              </th>
              <th scope="col" className={th}>Outcome</th>
              <th scope="col" className={cx(th, 'w-24')}><span className="sr-only">Witness</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, limit).map((r) => {
              const oc = outcomeOf(r)
              const o = OUTCOME[oc]
              const isOpen = open.has(r.clip_id)
              const flag = oc === 'fp' || oc === 'fn'
              const cell = 'border-b border-ex-line px-3 py-2.5 group-last:border-b-0'
              return (
                <Fragment key={r.clip_id}>
                  <tr className={cx('group transition-colors hover:bg-ex-raised/60', flag && 'bg-ex-warn-soft')}>
                    <td className={cell}>
                      <div className="flex items-center gap-3">
                        {r.event && (
                          <button type="button" className="shrink-0 overflow-hidden rounded-md" onClick={() => onOpen(r.event!.id)} aria-label={`View clip: ${r.event.summary ?? r.clip_id}`}>
                            <EventThumb event={r.event} compact className="h-[36px] w-16" />
                          </button>
                        )}
                        <span className="line-clamp-2 max-w-[24rem] text-ex-ink">{r.event?.summary ?? r.clip_id}</span>
                      </div>
                    </td>
                    <td className={cell}>
                      {r.label ? <LabelIndicator label={r.label} showProvenance={false} /> : <span className="text-xs text-ex-ink3">none</span>}
                    </td>
                    <td className={cell}>
                      <div className="flex items-center gap-2.5">
                        <ScoreBar score={r.score} tau={tau} />
                        <span className="w-12 font-mono text-xs tabular-nums text-ex-ink">{fmtScore(r.score)}</span>
                      </div>
                    </td>
                    <td className={cell}>
                      <span className={cx('inline-flex items-center gap-1.5 whitespace-nowrap text-sm', TONE_TEXT[o.tone])}>
                        <Icon name={o.icon} className="h-3.5 w-3.5" />{o.label}
                      </span>
                    </td>
                    <td className={cx(cell, 'text-right')}>
                      {r.witness && (
                        <button
                          type="button"
                          className="btn-ghost btn-sm"
                          aria-expanded={isOpen}
                          aria-controls={`wit-${r.clip_id}`}
                          onClick={() => toggle(r.clip_id)}
                        >
                          Why <Icon name="chevron" className={cx('h-3 w-3 transition-transform', isOpen && 'rotate-180')} />
                          <span className="sr-only">: {r.event?.summary ?? r.clip_id}</span>
                        </button>
                      )}
                    </td>
                  </tr>
                  {r.witness && isOpen && (
                    <tr>
                      <td colSpan={5} id={`wit-${r.clip_id}`} className="border-b border-ex-line bg-ex-bg/50 p-3 sm:p-4">
                        <WitnessTimeline witness={r.witness} durationMs={r.event?.duration_ms} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
        {rows.length === 0 && <div className="p-6"><Empty title="No clips in this view" className="border-0" /></div>}
      </div>
      {rows.length > limit && (
        <div className="mt-4 text-center">
          <button type="button" className="btn" onClick={() => { setLimit(limit + 40); requestAnimationFrame(() => document.getElementById('bt-h')?.focus()) }}>Show {Math.min(40, rows.length - limit)} more ({rows.length - limit} remaining)</button>
        </div>
      )}
      <p className="mt-3 flex flex-wrap items-center gap-x-2 text-xs text-ex-ink3">
        <span aria-hidden="true" className="inline-block h-3 w-0.5 rounded-full bg-ex-ink" />
        The white tick on each bar is τ = {fmtNum(tau)}{bt.calibration.guarantee ? '' : ' (no guarantee yet: the rule fires on any score above 0)'}. Bars grow from 0 (centre); blue means the clip fires.
        <span className="font-mono">{rule.id}</span>
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
    if (busy) return
    setBusy(true); setError(null)
    try { onChanged(await patch<RuleSummary>(`/rules/${rule.id}`, { status: next })) } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function toggleAction(id: RuleAction) {
    if (busy) return
    const next = new Set(actions)
    if (next.has(id)) next.delete(id); else next.add(id)
    setBusy(true); setError(null)
    try { onChanged(await patch<RuleSummary>(`/rules/${rule.id}`, { actions: Array.from(next) })) } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }

  return (
    <section aria-labelledby="dep-h" className="p-5 sm:p-6">
      <h2 id="dep-h" className="text-md font-semibold tracking-tight text-ex-ink">Deploy</h2>
      <div className="mt-4 flex items-center gap-3.5">
        <Switch checked={deployed} onChange={() => setStatus(deployed ? 'selected' : 'deployed')} labelledBy="dep-label" disabled={busy} />
        <div className="min-w-0">
          <p id="dep-label" className="font-medium text-ex-ink">{deployed ? 'Live: scoring new events' : 'Off: not scoring new events'}</p>
          <p className="text-xs text-ex-ink3">One rule per concept is live at a time; deploying replaces the current one.</p>
        </div>
      </div>
      {!hasGuarantee && (
        <div className="mt-4"><Alert tone="warn" title="Deploying without a guarantee">This rule will fire on any score above 0. Label random clips first if you want a bounded false-alarm rate.</Alert></div>
      )}
      {deployed && (
        <p className="mt-4 text-sm"><Link href="/live" className="inline-flex items-center gap-1 rounded font-medium text-ex-accent-ink hover:text-ex-ink">Watch it on the Live screen <Icon name="arrow-right" className="h-3.5 w-3.5" /></Link></p>
      )}

      <fieldset className="mt-6 border-t border-ex-line pt-5">
        <legend className="float-left mb-3 w-full text-sm font-semibold text-ex-ink">When it fires</legend>
        <div className="clear-both grid gap-3">
          {ACTIONS.map((a) => (
            <label key={a.id} className="flex cursor-pointer items-start gap-3 text-sm">
              <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-[#2A6BE0]" checked={actions.has(a.id)} aria-disabled={busy || undefined} onChange={() => toggleAction(a.id)} />
              <span><span className="text-ex-ink">{a.label}</span><span className="block text-xs text-ex-ink3">{a.hint}</span></span>
            </label>
          ))}
        </div>
      </fieldset>
      {error && <div className="mt-4"><Alert tone="neg">{error}</Alert></div>}
    </section>
  )
}

function CostCard({ cost }: { cost: ApiState<CostSummary> }) {
  return (
    <section aria-labelledby="cost-h" className="p-5 sm:p-6">
      <h2 id="cost-h" className="text-md font-semibold tracking-tight text-ex-ink">Cost per event</h2>
      {cost.data && cost.data.events > 0 ? (
        <>
          <p className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-semibold tracking-tight tabular-nums text-ex-ink">{fmtUsd(cost.data.per_event_usd)}</span>
            <span className="text-sm text-ex-ink3">per live event so far</span>
          </p>
          <dl className="mt-4 grid grid-cols-3 gap-3 text-xs">
            <div><dt className="text-ex-ink3">Dropped free</dt><dd className="mt-0.5 text-md font-medium tabular-nums text-ex-ink">{fmtInt(cost.data.stage0_dropped)}</dd><dd className="text-ex-ink3">stage 0</dd></div>
            <div><dt className="text-ex-ink3">Scored</dt><dd className="mt-0.5 text-md font-medium tabular-nums text-ex-ink">{fmtInt(cost.data.stage1_scored)}</dd><dd className="text-ex-ink3">stage 1</dd></div>
            <div><dt className="text-ex-ink3">Escalated</dt><dd className="mt-0.5 text-md font-medium tabular-nums text-ex-ink">{fmtInt(cost.data.stage2_escalated)}</dd><dd className="text-ex-ink3">stage 2</dd></div>
          </dl>
        </>
      ) : cost.loading ? (
        <Skeleton className="mt-3 h-14" label="Loading the cost" />
      ) : (
        <p className="mt-2 text-sm text-ex-ink2">No live events yet: costs appear once this rule has watched some.</p>
      )}
      <p className="mt-4 text-xs text-ex-ink3">Backtests are free: they reuse cached traces. Only new events cost a model call, and only those scoring within δ of τ use the stronger model.</p>
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
  const c = backtest.data?.counts ?? {}

  function onChanged(r: RuleSummary) {
    setUpdated(r)
    list.reload(); refreshConcepts(); backtest.reload()
  }

  return (
    <>
      <PageHeader title="Rule" subtitle="Check a rule against your history before it goes live: what it matches, what it gets wrong, and how many false alarms to expect." />

      <div className="mb-8 flex flex-wrap items-end gap-4">
        <ConceptSelect id="rule-concept" label="Concept" className="w-full sm:w-64" />
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

      {list.loading && !list.data && (
        <div role="status" aria-label="Loading rules" className="grid gap-4"><Skeleton className="h-52 rounded-xl" /><Skeleton className="h-20 rounded-xl" /></div>
      )}
      {!ruleId && !list.loading && (
        <Empty title="No rule to show yet" icon="spark" action={<Link href="/teach" className="btn btn-primary">Go to Teach <Icon name="arrow-right" /></Link>}>
          Teach this concept first, then come back to check the rule against your history.
        </Empty>
      )}
      {rule.error && <Alert tone="neg" title="Could not load the rule">{rule.error.message}</Alert>}

      {current && (
        <div className="grid grid-cols-1 gap-10 xl:grid-cols-[minmax(0,8fr)_minmax(0,4fr)] xl:gap-12">
          <div className="grid min-w-0 grid-cols-1 content-start gap-8">
            <section aria-label="Rule" className="rounded-xl border border-ex-line2 bg-ex-panel p-6 sm:p-8">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-medium text-ex-ink3">Rule</p>
                <span className="font-mono text-xs text-ex-ink3">{current.id}</span>
              </div>
              <p className="mt-3 text-xl font-semibold leading-snug tracking-tight text-ex-ink sm:text-2xl">{current.english}</p>
              <DslBlock text={current.dsl_text} size="lg" className="mt-5" />
              <div className="mt-5"><RuleMetrics rule={current} /></div>
              <SuspectList rule={current} events={events} onInspect={setOpenId} />
            </section>

            {backtest.loading && !backtest.data && (
              <div role="status" aria-label="Scoring your history" className="grid gap-4"><Skeleton className="h-20 rounded-xl" /><Skeleton className="h-64 rounded-xl" /></div>
            )}
            {backtest.error && <Alert tone="neg" title="Backtest failed">{backtest.error.message}</Alert>}

            {backtest.data && (
              <div>
                <StatStrip cols="grid-cols-2 sm:grid-cols-[repeat(4,minmax(0,1fr))_minmax(0,2fr)]" label="Backtest summary">
                  <Stat label="Matches" value={c.tp ?? 0} icon="check" hint="correct" />
                  <Stat label="False alarms" value={c.fp ?? 0} tone={(c.fp ?? 0) > 0 ? 'neg' : undefined} icon="cross" hint="matched a − clip" />
                  <Stat label="Missed" value={c.fn ?? 0} tone={(c.fn ?? 0) > 0 ? 'warn' : undefined} icon="warning" hint="a + clip, no match" />
                  <Stat label="Rejects" value={c.tn ?? 0} icon="minus" hint="correct" />
                  <div className="col-span-2 min-w-0 bg-ex-panel px-4 py-3.5 sm:col-span-1">
                    <dt className="flex items-center gap-1.5 text-xs text-ex-ink3"><Icon name="shield" className="h-3.5 w-3.5" />False-alarm guarantee</dt>
                    <dd className="mt-2 flex flex-wrap gap-1.5">{cal && <GuaranteeBadge cal={cal} wrap />}</dd>
                  </div>
                </StatStrip>
                <p className="mt-2 text-xs text-ex-ink3">
                  Counts use all your labels. Only random labels feed the guarantee.
                  {(c.unlabelled_matches ?? 0) > 0 && <> {c.unlabelled_matches} matched clip{c.unlabelled_matches === 1 ? ' has' : 's have'} no label yet: worth a look.</>}
                </p>
              </div>
            )}

            {cal && conceptId && <CalibrationPanel cal={cal} conceptId={current.concept_id} />}
            {backtest.data && <BacktestTable bt={backtest.data} rule={current} onOpen={setOpenId} />}
          </div>

          <aside aria-label="Deploy and cost" className="min-w-0 xl:sticky xl:top-20 xl:self-start">
            <div className="divide-y divide-ex-line rounded-xl border border-ex-line bg-ex-panel">
              <DeployCard rule={current} onChanged={onChanged} hasGuarantee={!!cal?.guarantee} />
              <CostCard cost={cost} />
            </div>
          </aside>
        </div>
      )}
      <EventDialog eventId={openId} onClose={() => setOpenId(null)} />
    </>
  )
}
