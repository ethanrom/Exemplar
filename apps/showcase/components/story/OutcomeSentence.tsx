import { Src } from './Src.tsx'
import { pluralise, words } from './format.ts'
import { CLASS_NOUN, type ClassOutcome } from './outcomes.ts'

/** The recorded outcome, in words, from the counts in the data (never typed by hand). */
export function OutcomeSentence({ outcomes, className }: { outcomes: ClassOutcome[]; className?: string }) {
  return (
    <p className={className ?? 'text-md text-ex-ink'}>
      {outcomes.map((o, i) => {
        const fired: string[] = []
        if (o.packageFired > 0) fired.push('package rule')
        if (o.vehicleFired > 0) fired.push('vehicle rule')
        const what = fired.length === 0 ? 'fired neither rule' : fired.length === 1 ? `fired only the ${fired[0]}` : 'fired both rules'
        const lead = i === 0 ? 'The' : i === outcomes.length - 1 ? 'and the' : 'the'
        return (
          <span key={o.cls}>
            {i > 0 && ', '}
            {lead} <Src src={`live.json#class.${o.cls}`}>{o.events === 1 ? '' : `${words(o.events)} `}{CLASS_NOUN[o.cls]} {pluralise(o.events, 'event')}</Src> {what}
          </span>
        )
      })}
      .
    </p>
  )
}

