# Exemplar showcase (apps/showcase)

Static Next.js 15 site (`output: 'export'`) that replays recorded Exemplar data and re-runs its offline logic in the browser. No server, no Ring token, no Bedrock. Build spec: `internal/showcase/SPEC.md` in the main checkout.

## Run

```
npm install
npm run dev          # http://localhost:3010
npm run build        # next build, then scripts/prune-release.mjs -> out/
npm run typecheck    # tsc --noEmit
npm test             # node --test over lib/**, components/** and app/**/_lib/** test files
```

Node: the build, the post-build step and the tests run `.ts` files with Node's built-in type stripping, so use Node 24 (built and tested on 24.4.1; 22.18 or later also strips types). On Vercel set the project's Node.js Version to 24.x, with Root Directory `apps/showcase`. The build reads nothing outside `apps/showcase`: no Python, no databases, no environment variables.

Data that does not come from the export (`scripts/export/`):

| File | Written by | Source |
|---|---|---|
| `data/cost_vs_rules.json` | `node scripts/sync-cost-table.mjs` | the table in `docs/eval/cost_vs_rules.md` (a test fails when the copy is stale) |
| `data/parity.json` | `node scripts/parity/make-parity.mjs` | runs the parity tests, reads the golden files and `data/grid/parity-report.json`; stops on any mismatch |

Build flags (environment, read at build time by `next.config.js`):

| Flag | Values | Effect |
|---|---|---|
| `SHOWCASE_RELEASE` | `R1` `R2` `R3` `R4` (default) | pages in the nav and in `out/`, footer disclosure text |
| `SANDBOX_MEDIA` | `frames` (default) `trace` | how Ring sandbox recordings are shown (SPEC 9.3); read it from `components/index.ts`. Every credits entry is cleared (the owner decided to show the Playground frames), so `trace` changes nothing unless an entry is set back to `pending_user_decision` |
| `NEXT_PUBLIC_KITCHEN` | `1` | builds the `/kitchen/` component gallery (preview only; otherwise it is not in `out/`) |

`build` ends with `scripts/prune-release.mjs`: a page that calls `notFound()` is still exported as a soft 404 with status 200, so pages outside the release (and `/kitchen/`) are deleted from `out/` instead.

## Conventions

- Erasable TypeScript only (no `enum`, `namespace`, parameter properties, decorators); relative imports carry explicit `.ts`/`.tsx` extensions; `@/` is the app root. `verbatimModuleSyntax` is on, so type-only imports must use `import type`.
- Anything under `lib/**` must run under `node --test` as well as in the browser.
- Colours and type scale come from `styles/tokens.js` (same values as `apps/web`); use the `ex-*` Tailwind colours. Colour is never the only signal: pair it with an icon or a word.
- Pages: `app/<route>/page.tsx`. Keep each section's `id` (anchors and tests rely on it); replace its `<Placeholder>`.

```tsx
import { PageHeader, Section, pageMetadata, requirePage } from '@/components/index.ts'
export const metadata = pageMetadata('live')
export default function LivePage() {
  const page = requirePage('live')
  return (<><PageHeader title={page.title} subtitle={page.purpose} /><Section id="events" title="Recorded events">…</Section></>)
}
```

## Components (`@/components/index.ts`)

`Card` `CardTitle` `Badge` `Chip` `Button` `ButtonLink` `TextLink` `SmartLink` `Dsl` `DslBlock` `CodeBlock` `Tabs` `Tooltip` `InfoTip` `Stat` `StatStrip` `StatTile` `PageHeader` `Section` `SectionHeader` `Disclosure` `Collapsible` `Alert` `Placeholder` `ScrollRegion` `Icon` `Mark`, plus `cx`, the tone maps, and the site pieces `SiteHeader` `SiteFooter` `SkipLink`. Site configuration (`PAGES`, `RELEASE`, `SANDBOX_MEDIA`, `pagesFor`, `disclosureParagraphs`) is in `components/site/config.ts`.

## Headers (`vercel.json`)

Next's `headers()` does not exist in export mode, so all headers live in `vercel.json`: COOP `same-origin` and COEP `require-corp` site-wide (cross-origin isolation for the Z3 spike, with no third-party embeds), CSP, `nosniff`, `Referrer-Policy`, immutable caching for `/_next/static/*` and `/media/*`, 5 minutes for `/data/*`, `application/wasm` and an immutable cache under `/z3/*` (the Z3 files sit under a versioned path, the worker under a content hash).

CSP choice (SPEC 2 leaves it to the scaffold): `script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'`. Next's exported pages carry inline bootstrap scripts whose hashes change with every build and every page, so hash allow-listing would mean regenerating per-route headers after each build. The site renders no user-supplied HTML, loads nothing from another origin (`connect-src 'self'`, `default-src 'self'`) and has `object-src 'none'`, so `'unsafe-inline'` is the accepted trade-off. SH-E verifies what Emscripten needs on top.
