import { Suspense } from 'react'
import EvalScreen from '../_screens/EvalScreen'

export const metadata = { title: 'Eval' }

export default function Page() {
  return (
    <Suspense fallback={<p className="text-sm text-ex-ink2">Loading…</p>}>
      <EvalScreen />
    </Suspense>
  )
}
