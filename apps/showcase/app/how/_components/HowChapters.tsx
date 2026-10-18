'use client'

import { Section } from '@/components/SectionHeader.tsx'
import type { HowData } from '../_lib/types.ts'
import { Chapter1 } from './Chapter1.tsx'
import { Chapter2 } from './Chapter2.tsx'
import { Chapter3 } from './Chapter3.tsx'
import { Chapter4 } from './Chapter4.tsx'
import { Chapter5 } from './Chapter5.tsx'

/** The five chapters. One client component, so the traces they share are serialised once. */
export function HowChapters({ data }: { data: HowData }) {
  const ev3 = data.live.events.find((e) => e.order === 3) ?? data.live.events[0]
  if (!ev3) return null
  return (
    <>
      <Section
        id="perceive"
        step={1}
        title="Claude reads the clip once"
        description="The 16 frames perception read for recorded event 3, each with the facts written down for it."
      >
        <Chapter1 card={data.cards[ev3.alias] as HowData['cards'][string]} trace={data.traces[ev3.alias] as HowData['traces'][string]} eventNumber={ev3.order} />
      </Section>

      <Section
        id="sketch"
        step={2}
        title="The agent writes a rule with a blank"
        description="A language model proposes the shape of a rule and leaves the numbers blank. A type checker sends back what does not fit."
      >
        <Chapter2 p1={data.p1} />
      </Section>

      <Section
        id="solver"
        step={3}
        title="How the solver fills the blank"
        description="Why 15 s: the range of values that keeps the examples right, and the value placed in it."
      >
        <Chapter3 runs={data.runs} traces={data.traces} cards={data.cards} />
      </Section>

      <Section
        id="witness"
        step={4}
        title="Why it fired"
        description="Every alert comes with the evidence behind it. Drag the blank and watch each part of the rule re-score."
      >
        <Chapter4 live={data.live} deployed={data.deployed} traces={data.traces} cards={data.cards} />
      </Section>

      <Section
        id="calibration"
        step={5}
        title="A bound on false alarms"
        description="The recorded random sample, how its k-th score becomes the threshold, and the arithmetic of the rank."
      >
        <Chapter5 cal={data.cal} rule={data.packageRule} traces={data.traces} cards={data.cards} />
      </Section>
    </>
  )
}
