'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useId, useRef, useState } from 'react'
import { cx } from '../cx.ts'
import { Icon } from '../Icon.tsx'
import { Mark } from '../Mark.tsx'
import { isActivePath } from './config.ts'

export type NavItem = { href: string; label: string }

/**
 * Sticky header: logo and the primary navigation. Below `lg` the links sit behind a Menu button
 * (aria-expanded, Escape closes, a route change closes); from `lg` they are always visible.
 */
export function SiteHeader({ pages }: { pages: NavItem[] }) {
  const pathname = usePathname()
  const navId = useId()
  const [open, setOpen] = useState(false)
  const button = useRef<HTMLButtonElement>(null)
  const header = useRef<HTMLElement>(null)

  useEffect(() => { setOpen(false) }, [pathname])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        button.current?.focus()
      }
    }
    const onPointer = (e: PointerEvent) => {
      if (header.current && !header.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPointer)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPointer)
    }
  }, [open])

  return (
    <header ref={header} className="sticky top-0 z-40 border-b border-ex-line bg-ex-bg">
      <div className="mx-auto flex max-w-[1240px] items-center gap-2 px-4 py-2 sm:px-6">
        <Link href="/" className="-ml-1 mr-2 flex items-center gap-2.5 rounded-md px-1 py-1" aria-label="Exemplar home">
          <Mark />
          <span className="text-md font-semibold tracking-tight text-ex-ink">Exemplar</span>
        </Link>

        <button
          ref={button}
          type="button"
          className="btn btn-sm ml-auto lg:hidden"
          aria-expanded={open}
          aria-controls={navId}
          onClick={() => setOpen((o) => !o)}
        >
          <Icon name={open ? 'cross' : 'menu'} className="h-3.5 w-3.5" />
          Menu
        </button>

        <nav
          id={navId}
          aria-label="Primary"
          className={cx(
            open ? 'block' : 'hidden',
            'absolute inset-x-0 top-full border-b border-ex-line bg-ex-bg px-4 pb-3 pt-1 sm:px-6',
            'lg:static lg:block lg:flex-1 lg:border-0 lg:p-0',
          )}
        >
          <ul className="flex flex-col gap-0.5 lg:flex-row lg:items-center">
            {pages.map((p) => {
              const active = isActivePath(pathname, p.href)
              return (
                <li key={p.href}>
                  <Link
                    href={p.href}
                    aria-current={active ? 'page' : undefined}
                    className={cx(
                      'inline-flex h-10 w-full items-center rounded-md px-2.5 text-base font-medium transition-colors lg:h-8 lg:w-auto',
                      active ? 'bg-ex-hover text-ex-ink' : 'text-ex-ink2 hover:bg-ex-raised hover:text-ex-ink',
                    )}
                  >
                    {p.label}
                  </Link>
                </li>
              )
            })}
          </ul>
        </nav>
      </div>
    </header>
  )
}
