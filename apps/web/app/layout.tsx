import './globals.css'
import type { Metadata, Viewport } from 'next'
import { GeistSans } from 'geist/font/sans'
import { GeistMono } from 'geist/font/mono'
import { Shell } from './(exemplar)/_components/Shell'

export const metadata: Metadata = {
  title: { default: 'Exemplar', template: '%s · Exemplar' },
  description: 'Teach your Ring camera new detectors by example: readable rules, tested before they go live.',
}

export const viewport: Viewport = { themeColor: '#0A0B0D', colorScheme: 'dark' }

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-screen bg-ex-bg font-sans text-ex-ink">
        <Shell>{children}</Shell>
      </body>
    </html>
  )
}
