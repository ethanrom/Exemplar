// Serves the engine's precomputed Lab grid (data/grid/grid.json.gz) as the static file /lab/grid.json, decompressed at build
// time. The page reads it only after a solve has finished (SPEC 6.5). A build without a grid export serves `null`.
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { gunzipSync } from 'node:zlib'
import { dataRoot, loadLibrary } from '../../../lib/data/load.ts'

export const dynamic = 'force-static'

export function GET() {
  const dir = path.join(dataRoot(), 'grid')
  const gz = path.join(dir, 'grid.json.gz')
  const plain = path.join(dir, 'grid.json')
  const body = existsSync(gz) ? gunzipSync(readFileSync(gz)).toString('utf-8') : existsSync(plain) ? readFileSync(plain, 'utf-8') : 'null'
  // The grid keeps the engine's bit order for all eight curated clips, so a clip that is not published stays in its place
  // under a neutral name. The Lab never sets its bit (it is pinned to "not used"), so the name is never shown.
  const doc = JSON.parse(body) as { clips: string[]; provenance: { curated: { alias: string }[] } } | null
  if (doc) {
    const keep = new Set(loadLibrary().map((c) => c.alias))
    doc.clips = doc.clips.map((a) => (keep.has(a) ? a : 'unused'))
    doc.provenance.curated = doc.provenance.curated.map((c) => (keep.has(c.alias) ? c : { ...c, alias: 'unused' }))
  }
  return new Response(JSON.stringify(doc), { headers: { 'Content-Type': 'application/json; charset=utf-8' } })
}
