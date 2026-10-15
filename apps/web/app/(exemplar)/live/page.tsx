import { Suspense } from 'react'
import { PageFallback } from '../_components/ui'
import LiveScreen from '../_screens/LiveScreen'

export const metadata = { title: 'Live' }

export default function Page() {
  return (
    <Suspense fallback={<PageFallback />}>
      <LiveScreen />
    </Suspense>
  )
}
