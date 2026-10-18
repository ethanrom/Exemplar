// Serves the engine's scores of every closed rule on every library clip (data/grid/closed.json.gz) as the static file
// /lab/closed.json, decompressed at build time. The backtest is cross-checked against it. A build without it serves `null`.
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { gunzipSync } from 'node:zlib'
import { dataRoot, loadLibrary } from '../../../lib/data/load.ts'

export const dynamic = 'force-static'

export function GET() {
  const dir = path.join(dataRoot(), 'grid')
  const gz = path.join(dir, 'closed.json.gz')
  const plain = path.join(dir, 'closed.json')
  const body = existsSync(gz) ? gunzipSync(readFileSync(gz)).toString('utf-8') : existsSync(plain) ? readFileSync(plain, 'utf-8') : 'null'
  // The engine's file also scored clips that are not published; their columns are dropped so the file names only the library.
  const doc = JSON.parse(body) as { clips: string[]; rules: { scores: number[] }[] } | null
  if (doc) {
    const keep = new Set(loadLibrary().map((c) => c.alias))
    const cols = doc.clips.map((a, i) => (keep.has(a) ? i : -1)).filter((i) => i >= 0)
    doc.clips = cols.map((i) => doc.clips[i] as string)
    for (const r of doc.rules) r.scores = cols.map((i) => r.scores[i] as number)
  }
  return new Response(JSON.stringify(doc), { headers: { 'Content-Type': 'application/json; charset=utf-8' } })
}
