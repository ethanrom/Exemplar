'use client'

import { useApp } from '../_lib/app'

/** Labelled concept picker shared by Library, Teach and Rule. */
export function ConceptSelect({ id = 'concept-select', label = 'Concept', className = 'min-w-[200px]' }: { id?: string; label?: string; className?: string }) {
  const { concepts, conceptId, setConceptId, conceptsLoading } = useApp()
  return (
    <div className={className}>
      <label htmlFor={id} className="field-label">{label}</label>
      <select
        id={id}
        className="field"
        value={conceptId ?? ''}
        disabled={conceptsLoading || concepts.length === 0}
        onChange={(e) => setConceptId(e.target.value)}
      >
        {concepts.length === 0 && <option value="">{conceptsLoading ? 'Loading…' : 'No concepts yet'}</option>}
        {concepts.map((c) => (
          <option key={c.id} value={c.id}>{c.name}</option>
        ))}
      </select>
    </div>
  )
}
