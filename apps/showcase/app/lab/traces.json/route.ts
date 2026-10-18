// Every library trace in one static file, /lab/traces.json: the facts the in-browser evaluator, the worker and the
// backtest read. Aliases only; the export has already been scrubbed.
import { loadLibrary, loadTrace } from '../../../lib/data/load.ts'

export const dynamic = 'force-static'

export function GET() {
  const traces: Record<string, unknown> = {}
  for (const c of loadLibrary()) traces[c.alias] = loadTrace(c.alias)
  return new Response(JSON.stringify(traces), { headers: { 'Content-Type': 'application/json; charset=utf-8' } })
}
