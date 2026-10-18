import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import { RELEASE, getPage, releaseAtLeast, type PageId, type PageInfo } from './config.ts'

/**
 * Call first in a page component. Returns the page's entry (title, purpose, route) and, when the page is not
 * part of this build's SHOWCASE_RELEASE, renders the not-found page instead.
 */
export function requirePage(id: PageId): PageInfo {
  const page = getPage(id)
  if (!releaseAtLeast(RELEASE, page.since)) notFound()
  return page
}

/** `export const metadata = pageMetadata('lab')` in each route. Home keeps the root default title. */
export function pageMetadata(id: PageId): Metadata {
  const page = getPage(id)
  return id === 'home' ? { description: page.purpose } : { title: page.title, description: page.purpose }
}
