import { Suspense } from 'react'
import { PageFallback } from '../_components/ui'
import ConnectScreen from '../_screens/ConnectScreen'

export const metadata = { title: 'Connect' }

export default function Page() {
  return (
    <Suspense fallback={<PageFallback />}>
      <ConnectScreen />
    </Suspense>
  )
}
