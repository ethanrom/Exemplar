import { Suspense } from 'react'
import ConnectScreen from '../_screens/ConnectScreen'

export const metadata = { title: 'Connect' }

export default function Page() {
  return (
    <Suspense fallback={<p className="text-sm text-ex-ink2">Loading…</p>}>
      <ConnectScreen />
    </Suspense>
  )
}
