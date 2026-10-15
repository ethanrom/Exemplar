import { Suspense } from 'react'
import { PageFallback } from '../_components/ui'
import EvalScreen from '../_screens/EvalScreen'

export const metadata = { title: 'Eval' }

export default function Page() {
  return (
    <Suspense fallback={<PageFallback />}>
      <EvalScreen />
    </Suspense>
  )
}
