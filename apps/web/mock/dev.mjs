// `npm run dev:mock`: start the mock engine (port 8787) and `next dev` (port 3000) together.
//   ENGINE_URL is pointed at the mock; Ctrl+C stops both.
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(path.join(root, 'package.json'))
const nextBin = require.resolve('next/dist/bin/next')
const mockPort = process.env.MOCK_PORT || '8787'
const webPort = process.env.PORT || '3000'

const env = { ...process.env, ENGINE_URL: `http://127.0.0.1:${mockPort}` }
const children = []

function run(label, args, extraEnv = {}) {
  const child = spawn(process.execPath, args, { cwd: root, env: { ...env, ...extraEnv }, stdio: ['ignore', 'pipe', 'pipe'] })
  const prefix = (stream, out) =>
    stream.on('data', (d) => String(d).split(/\r?\n/).filter(Boolean).forEach((l) => out.write(`[${label}] ${l}\n`)))
  prefix(child.stdout, process.stdout)
  prefix(child.stderr, process.stderr)
  child.on('exit', (code) => {
    console.log(`[${label}] exited (${code})`)
    shutdown(code ?? 0)
  })
  children.push(child)
}

let closing = false
function shutdown(code = 0) {
  if (closing) return
  closing = true
  for (const c of children) if (!c.killed) c.kill()
  setTimeout(() => process.exit(code), 300)
}
process.on('SIGINT', () => shutdown(0))
process.on('SIGTERM', () => shutdown(0))

run('mock', [path.join(root, 'mock', 'server.mjs')], { PORT: mockPort })
run('web ', [nextBin, 'dev', '-p', webPort])
