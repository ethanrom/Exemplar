import './globals.css'
import type { Metadata } from 'next'
import { Shell } from './(exemplar)/_components/Shell'

export const metadata: Metadata = {
  title: { default: 'Exemplar', template: '%s · Exemplar' },
  description: 'Teach your Ring camera new detectors by example: readable rules, proven before they go live.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-ex-bg text-ex-ink">
        <Shell>{children}</Shell>
      </body>
    </html>
  )
}
