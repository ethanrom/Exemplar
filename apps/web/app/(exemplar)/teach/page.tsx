import { Suspense } from 'react'
import TeachScreen from '../_screens/TeachScreen'

export const metadata = { title: 'Teach' }

export default function Page() {
  return (
    <Suspense fallback={<p className="text-sm text-ex-ink2">Loading…</p>}>
      <TeachScreen />
    </Suspense>
  )
}
