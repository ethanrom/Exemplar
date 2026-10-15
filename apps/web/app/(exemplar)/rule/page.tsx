import { Suspense } from 'react'
import RuleScreen from '../_screens/RuleScreen'

export const metadata = { title: 'Rule' }

export default function Page() {
  return (
    <Suspense fallback={<p className="text-sm text-ex-ink2">Loading…</p>}>
      <RuleScreen />
    </Suspense>
  )
}
