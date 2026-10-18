'use client'

import { useMemo, type ReactNode } from 'react'
import { Section } from '@/components/SectionHeader.tsx'
import { AgentTimeline } from '@/components/lab/AgentTimeline.tsx'
import { CandidateList, type CandidateView } from '@/components/lab/CandidateList.tsx'
import { cx } from '@/components/cx.ts'
import type { ClipCard, RunEvent } from '@/lib/data/types.ts'
import { backtest, crossCheck, tally } from '../_lib/backtest.ts'
import type { Assets } from '../_lib/useLabAssets.ts'
import type { LabProps, LabRule, Mode } from '../_lib/types.ts'
import { Backtest } from './Backtest.tsx'
import { calibrationCase, CalibrationPanel } from './CalibrationPanel.tsx'
import { SelectedRule } from './SelectedRule.tsx'

/**
 * The right-hand column of the workbench: the agent timeline, the ranked candidates, the selected rule, its backtest on the
 * whole library and its calibration. The same column serves the presets and free play; what differs is what is fed in.
 */
export function ResultsColumn({
  props, cards, assets, mode, timeline, candidates, experimental, contradiction, recordedRules, recordedMessage,
}: {
  props: LabProps
  cards: ReadonlyMap<string, ClipCard>
  assets: Assets
  mode: Mode
  timeline: { events: readonly RunEvent[]; running: boolean; label: string; controls?: ReactNode; note?: ReactNode }
  candidates: {
    views: CandidateView[]
    selectedKey: string | null
    onSelect: (key: string) => void
    busy: boolean
    empty: string
    above?: ReactNode
    below?: ReactNode
  }
  experimental: boolean
  contradiction: boolean
  /** The recorded rules by closed DSL text: they carry the recorded tau, scores and calibration message. */
  recordedRules: ReadonlyMap<string, LabRule>
  recordedMessage: string | null
}) {
  const titleOf = (a: string) => cards.get(a)?.title ?? a
  const selected = candidates.views.find((v) => v.key === candidates.selectedKey) ?? null
  const recordedRule = selected ? recordedRules.get(selected.dsl_text) : undefined
  const tau = recordedRule?.tau ?? 0

  const rows = useMemo(
    () => (selected && assets.traces ? backtest(selected.dsl_text, props.library, assets.traces, tau) : null),
    [selected, assets.traces, props.library, tau],
  )
  const cross = useMemo(() => {
    if (!rows || !selected) return null
    if (recordedRule) return { c: crossCheck(rows, new Map(recordedRule.backtest.map((b) => [b.alias, b.score]))), src: 'the scores recorded with this rule' }
    const cl = assets.closed?.rules.find((r) => r.dsl_text === selected.dsl_text)
    if (cl && assets.closed) {
      return { c: crossCheck(rows, new Map(assets.closed.clips.map((a, i) => [a, cl.scores[i] as number]))), src: 'the engine’s scores for this rule' }
    }
    return null
  }, [rows, selected, recordedRule, assets.closed])

  const deployedDsl = (props.rules['package-deployed'] as LabRule).dsl_text
  const cCase = calibrationCase({
    mode, selectedDsl: selected?.dsl_text ?? null, deployedDsl, contradiction, recordedMessage: recordedRule?.calibration?.message ?? recordedMessage,
  })

  return (
    <div>
      <Section id="timeline" title="Agent timeline" description={mode === 'free' ? 'The solver working through the recorded sketch bank on your examples.' : 'The recorded session, or the same loop re-run in your browser.'}>
        {timeline.controls}
        <AgentTimeline events={timeline.events} clips={cards} running={timeline.running} label={timeline.label} limit={mode === 'free' ? 60 : undefined} />
        {timeline.note}
      </Section>

      <Section id="candidates" title="Candidates" description={mode === 'free' ? 'Ranked by description length, then margin.' : 'Each with its recorded rank in the recorded run.'}>
        <div aria-busy={candidates.busy} className={cx('space-y-3 transition-opacity', candidates.busy && 'opacity-60')}>
          {candidates.above}
          {candidates.views.length === 0 && !candidates.busy ? (
            <p className="text-sm text-ex-ink2">{candidates.empty}</p>
          ) : (
            <CandidateList
              items={candidates.views}
              selectedKey={candidates.selectedKey}
              onSelect={candidates.onSelect}
              titleOf={titleOf}
              name={`candidates-${mode}`}
              label="Candidate rules, best first. Choose one to see it below."
            />
          )}
          {candidates.below}
        </div>
      </Section>

      <Section id="selected" title="Selected rule" description="English, rule text, filled blanks and margin.">
        <SelectedRule rule={selected} experimental={experimental} titleOf={titleOf} />
      </Section>

      <Section id="backtest" title="Backtest" description="The selected rule scored on the whole library, by class. Select a clip to see its frames and the rule’s witness.">
        <Backtest
          rows={rows}
          tallies={rows ? tally(rows) : []}
          cards={cards}
          traces={assets.traces}
          dslText={selected?.dsl_text ?? null}
          tau={tau}
          cross={cross?.c ?? null}
          crossSource={cross?.src ?? null}
        />
      </Section>

      <Section id="calibration" title="Calibration" description="The recorded false-alarm bound, or an exploratory recalibration marked as such.">
        <CalibrationPanel c={cCase} cal={props.cal} selectedDsl={selected?.dsl_text ?? null} traces={assets.traces} titleOf={titleOf} />
      </Section>
    </div>
  )
}
