import { Suspense } from 'react'
import { PageFallback } from '../_components/ui'
import EvidenceScreen from '../_screens/EvidenceScreen'

export const metadata = { title: 'Evidence' }

export default function Page() {
  return (
    <Suspense fallback={<PageFallback />}>
      <EvidenceScreen />
    </Suspense>
  )
}
