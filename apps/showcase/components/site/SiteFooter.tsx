import { Disclosure } from '../Disclosure.tsx'
import { TextLink } from '../Link.tsx'
import { disclosureParagraphs, type Release } from './config.ts'

/** Footer on every page: the replay disclosure for this release (SPEC section 10.3), then the quiet small print. */
export function SiteFooter({ release }: { release: Release }) {
  return (
    <footer className="border-t border-ex-line">
      <div className="mx-auto max-w-[1240px] px-4 py-8 sm:px-6">
        <Disclosure title="What runs here" as="h2">
          {disclosureParagraphs(release).map((text) => <p key={text}>{text}</p>)}
        </Disclosure>
        <p className="mt-5 text-xs leading-5 text-ex-ink3">
          Supplementary showcase for Exemplar. Media sources, licences and permissions are listed on the{' '}
          <TextLink href="/credits/">Credits</TextLink> page.
        </p>
      </div>
    </footer>
  )
}
