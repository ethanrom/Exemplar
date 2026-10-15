import { Suspense } from 'react'
import { PageFallback } from '../_components/ui'
import LibraryScreen from '../_screens/LibraryScreen'

export const metadata = { title: 'Library' }

export default function Page() {
  return (
    <Suspense fallback={<PageFallback />}>
      <LibraryScreen />
    </Suspense>
  )
}
