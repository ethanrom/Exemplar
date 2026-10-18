// Runs after `next build`. A statically exported page that calls notFound() is still written to out/ (as a
// soft 404 served with status 200), so pages that do not belong to this build are deleted from out/ here.
//   - pages whose `since` release is later than SHOWCASE_RELEASE (components/site/config.ts)
//   - the /kitchen/ gallery unless NEXT_PUBLIC_KITCHEN=1
// Their route chunks under out/_next/static/chunks/app/ go too, so nothing from an excluded page is deployed.
import { existsSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { PAGES, RELEASE, releaseAtLeast } from '../components/site/config.ts'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const out = join(root, 'out')
if (!existsSync(out)) {
  console.error('prune-release: out/ does not exist; run `next build` first')
  process.exit(1)
}

const routes = PAGES.filter((p) => !releaseAtLeast(RELEASE, p.since) && p.href !== '/').map((p) => p.href.replaceAll('/', ''))
if (process.env.NEXT_PUBLIC_KITCHEN !== '1') routes.push('kitchen')

for (const route of routes) {
  const targets = [join(out, route), join(out, '_next', 'static', 'chunks', 'app', route)]
  for (const t of targets) rmSync(t, { recursive: true, force: true })
  console.log(`prune-release: removed /${route}/ (release ${RELEASE})`)
}
