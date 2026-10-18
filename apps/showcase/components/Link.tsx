import NextLink from 'next/link'
import type { AnchorHTMLAttributes, ReactNode } from 'react'
import { cx } from './cx.ts'
import { Icon } from './Icon.tsx'

/** Absolute URLs and mailto: links leave the site; everything else is an in-site route. */
export const isExternalHref = (href: string): boolean => /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(href)

type SmartLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & { href: string; children?: ReactNode }

/** In-site hrefs use the client router; external ones are plain anchors. The site makes no request until a link is followed. */
export function SmartLink({ href, children, ...rest }: SmartLinkProps) {
  if (isExternalHref(href)) {
    return <a href={href} rel="noopener noreferrer" {...rest}>{children}</a>
  }
  return <NextLink href={href} {...rest}>{children}</NextLink>
}

/** Link inside prose. External links get a small "opens elsewhere" glyph. */
export function TextLink({ href, children, className, ...rest }: SmartLinkProps) {
  const external = isExternalHref(href)
  return (
    <SmartLink href={href} className={cx('link', className)} {...rest}>
      {children}
      {external && <Icon name="external" className="ml-1 inline h-3 w-3 align-[-1px]" />}
    </SmartLink>
  )
}
