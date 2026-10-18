import { Badge } from '@/components/index.ts'

// One status label per Ring capability. Colour is paired with an icon and the words, never used alone.
export type ApiStatus = 'observed' | 'fixture' | 'flag'

export const STATUS_LABEL: Record<ApiStatus, string> = {
  observed: 'Observed on the Ring Developer Playground',
  fixture: 'Tested against fixtures or mocks',
  flag: 'Built behind a flag, off by default',
}

export const STATUS_MEANING: Record<ApiStatus, string> = {
  observed: 'Exercised against the Playground’s simulated device in our own runs.',
  fixture: 'Covered by signed fixtures or mocked HTTP. Not exercised live.',
  flag: 'Implemented and covered by mocks. Switched off unless the flag is set, and not exercised live.',
}

export function StatusBadge({ status }: { status: ApiStatus }) {
  if (status === 'observed') return <Badge tone="pos" icon="check">{STATUS_LABEL.observed}</Badge>
  if (status === 'fixture') return <Badge tone="info" icon="layers">{STATUS_LABEL.fixture}</Badge>
  return <Badge tone="accent" icon="flag">{STATUS_LABEL.flag}</Badge>
}
