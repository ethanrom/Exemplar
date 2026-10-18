import './globals.css'
import type { Metadata, Viewport } from 'next'
import { GeistMono } from 'geist/font/mono'
import { GeistSans } from 'geist/font/sans'
import { SiteFooter } from '@/components/site/SiteFooter.tsx'
import { SiteHeader } from '@/components/site/SiteHeader.tsx'
import { SkipLink } from '@/components/site/SkipLink.tsx'
import { RELEASE, pagesFor } from '@/components/site/config.ts'

export const metadata: Metadata = {
  title: { default: 'Exemplar: teach your Ring camera by example', template: '%s · Exemplar' },
  description:
    'Supplementary showcase for Exemplar: recorded Ring Developer Playground runs, the readable rules they produced and the evidence behind each alert.',
}

export const viewport: Viewport = { themeColor: '#0A0B0D', colorScheme: 'dark' }

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const nav = pagesFor(RELEASE).map((p) => ({ href: p.href, label: p.label }))
  return (
    <html lang="en" className={`dark ${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="flex min-h-screen flex-col bg-ex-bg font-sans text-ex-ink">
        <SkipLink />
        <SiteHeader pages={nav} />
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1240px] flex-1 px-4 pb-20 pt-10 focus:outline-none sm:px-6">
          {children}
        </main>
        <SiteFooter release={RELEASE} />
      </body>
    </html>
  )
}
