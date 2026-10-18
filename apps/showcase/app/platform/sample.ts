// What changed relative to Ring's ring-api-helloworld sample. Source of truth: apps/web/UPSTREAM.md and the git history
// of apps/web (the first commit there is the unmodified upstream snapshot). Paths are relative to the repository root.

export const SAMPLE_URL = 'https://github.com/AmazonAppDev/ring-api-helloworld'
export const SAMPLE_COMMIT = '76100aa'
export const SAMPLE_COMMIT_DATE = '2026-07-01'

export type Change = { what: string; where: string[] }

/** Left as the sample has it. */
export const KEPT: Change[] = [
  { what: 'The WHEP live-view hook, which worked immediately and still drives the live view.', where: ['apps/web/app/hooks/useWebRTCStream.ts'] },
  {
    what: 'The video-processor plug-in registry. Exemplar’s 2 fps frame grabber is one more processor in it.',
    where: ['apps/web/lib/video-processors/registry.ts', 'apps/web/lib/video-processors/types.ts', 'apps/web/lib/video-processors/useVideoProcessing.ts'],
  },
  { what: 'The Python helper scripts for devices, history and location, useful for seeing each API’s real response.', where: ['apps/web/scripts/event_history.py', 'apps/web/scripts/list_devices.py'] },
]

/** Sample files that were extended. */
export const EXTENDED: Change[] = [
  {
    what: 'Webhook receiver: the X-Signature HMAC-SHA256 is verified over the raw body with a constant-time compare, deliveries are deduplicated on meta.request_id, and the route answers inside Ring’s response window. The sample’s own path now runs the same verified handler; its event feed for the sample dashboard is kept.',
    where: ['apps/web/app/api/webhook/route.ts', 'apps/web/app/api/ring/webhook/route.ts', 'apps/web/lib/ring/webhook-verify.mjs'],
  },
  {
    what: 'Live-view session route: same-origin check, a restricted device-id alphabet, no redirects followed with credentials attached, and the session DELETE accepts only live-view session addresses on Ring’s API.',
    where: ['apps/web/app/api/ring/stream/route.ts', 'apps/web/lib/ring/whep-url.mjs', 'apps/web/lib/ring/guard.ts'],
  },
  {
    what: 'Authentication: the devices and config routes share one module that also accepts a Playground token pasted at runtime. The token stays on the server and is never returned.',
    where: ['apps/web/lib/ring/auth.ts', 'apps/web/app/api/ring/devices/route.ts', 'apps/web/app/api/ring/config/route.ts'],
  },
  {
    what: 'The development-only webhook test route is switched off in production builds.',
    where: ['apps/web/app/api/webhook/test/route.ts'],
  },
]

/** New in Exemplar. */
export const ADDED: Change[] = [
  { what: 'The Exemplar interface: Connect, Library, Teach, Rule, Live and Eval screens.', where: ['apps/web/app/(exemplar)'] },
  { what: 'A proxy from the web app to the engine, so the browser only talks to the web app.', where: ['apps/web/app/api/engine/[...path]/route.ts'] },
  { what: 'Frame capture for the live fact ticker, registered as a video processor.', where: ['apps/web/lib/video-processors/frame-grab.ts'] },
  { what: 'A signed-webhook replay tool and the shared fixtures behind both test suites.', where: ['scripts/send_signed_webhook.py', 'apps/web/lib/ring/ring.test.mjs'] },
]
