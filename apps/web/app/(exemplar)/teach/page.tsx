import { Suspense } from 'react'
import { PageFallback } from '../_components/ui'
import TeachScreen from '../_screens/TeachScreen'

export const metadata = { title: 'Teach' }

export default function Page() {
  return (
    <Suspense fallback={<PageFallback />}>
      <TeachScreen />
    </Suspense>
  )
}
