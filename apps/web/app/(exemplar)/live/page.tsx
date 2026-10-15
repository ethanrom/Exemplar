import { Suspense } from 'react'
import LiveScreen from '../_screens/LiveScreen'

export const metadata = { title: 'Live' }

export default function Page() {
  return (
    <Suspense fallback={<p className="text-sm text-ex-ink2">Loading…</p>}>
      <LiveScreen />
    </Suspense>
  )
}
