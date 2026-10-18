// Shared presentational components. Import from here:  import { Card, Badge } from '@/components/index.ts'
// Everything is exported by name; client components ('use client') are Tabs, Tooltip, InfoTip, ScrollRegion and SiteHeader.

export { cx } from './cx.ts'
export { TONE_BADGE, TONE_ICON, TONE_PANEL, TONE_TEXT } from './tone.ts'
export type { Tone } from './tone.ts'

export { Icon } from './Icon.tsx'
export type { IconName } from './Icon.tsx'
export { Mark } from './Mark.tsx'

export { Card, CardTitle } from './Card.tsx'
export { Badge, Chip } from './Badge.tsx'
export { Button, ButtonLink } from './Button.tsx'
export type { ButtonSize, ButtonVariant } from './Button.tsx'
export { SmartLink, TextLink, isExternalHref } from './Link.tsx'
export { CodeBlock, Dsl, DslBlock, tokenizeDsl } from './CodeBlock.tsx'
export { Tabs } from './Tabs.tsx'
export type { TabItem } from './Tabs.tsx'
export { InfoTip, Tooltip } from './Tooltip.tsx'
export { Stat, StatStrip, StatTile } from './Stat.tsx'
export { PageHeader, Section, SectionHeader } from './SectionHeader.tsx'
export { Alert, Collapsible, Disclosure } from './Disclosure.tsx'
export { Placeholder } from './Placeholder.tsx'
export { ScrollRegion } from './ScrollRegion.tsx'

export { SiteFooter } from './site/SiteFooter.tsx'
export { SiteHeader } from './site/SiteHeader.tsx'
export { SkipLink } from './site/SkipLink.tsx'
export {
  PAGES, RELEASE, RELEASES, SANDBOX_MEDIA, disclosureParagraphs, getPage, isActivePath, pagesFor, releaseAtLeast,
} from './site/config.ts'
export type { PageId, PageInfo, Release, SandboxMedia } from './site/config.ts'
export { pageMetadata, requirePage } from './site/page.ts'
