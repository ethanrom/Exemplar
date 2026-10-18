/** First focusable element on every page; jumps over the header to <main id="main">. */
export function SkipLink({ target = 'main' }: { target?: string }) {
  return (
    <a
      href={`#${target}`}
      className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-ex-accent focus:px-4 focus:py-2 focus:font-semibold focus:text-white"
    >
      Skip to main content
    </a>
  )
}
