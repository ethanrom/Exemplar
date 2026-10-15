import { Suspense } from 'react'
import { PageFallback } from '../_components/ui'
import RuleScreen from '../_screens/RuleScreen'

export const metadata = { title: 'Rule' }

export default function Page() {
  return (
    <Suspense fallback={<PageFallback />}>
      <RuleScreen />
    </Suspense>
  )
}
