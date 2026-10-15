import { Suspense } from 'react'
import LibraryScreen from '../_screens/LibraryScreen'

export const metadata = { title: 'Library' }

export default function Page() {
  return (
    <Suspense fallback={<p className="text-sm text-ex-ink2">Loading…</p>}>
      <LibraryScreen />
    </Suspense>
  )
}
