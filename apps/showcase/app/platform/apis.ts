// The Ring API surface Exemplar uses, with one status label on each item. Every label is backed by code, tests or a
// friction-log entry marked live; the paths are checked against the repository by components/evidence/paths.test.ts.
// Endpoints are written without any Ring identifier.
import type { ApiItem } from '@/components/evidence/platform/ApiCard.tsx'

const LOG_PG2 = { id: 'PG-2', anchor: 'pg-2-simulated-events-on_demand-only-listed-27-44-s-late-no-webhook-live' }

export const API_ITEMS: ApiItem[] = [
  // ---------------------------------------------------------------- observed on the Playground
  {
    id: 'playground-token',
    name: 'Developer Playground token',
    status: 'observed',
    uses:
      'The demo environment. A read-only token generated in the Playground (valid for about 30 minutes) is pasted on the Connect screen. The server holds it and never returns it to the browser.',
    calls: [],
    basis: 'Every live run on the Playground used a pasted token.',
    code: ['apps/web/app/api/ring/token/route.ts', 'engine/exemplar/ring/tokens.py'],
    tests: ['engine/tests/ring/test_tokens.py'],
  },
  {
    id: 'devices',
    name: 'Connection check and devices',
    status: 'observed',
    uses:
      'Proves the token works, discovers the camera, and reads its status, capabilities, configuration and location. Cameras are shown by name in the interface.',
    calls: ['GET users/me', 'GET /v1/devices?include=status,capabilities,configurations', 'GET /v1/devices/{id}/location'],
    basis: 'Run against the Playground’s simulated device. A live test covers it and runs whenever a token is present.',
    code: ['engine/exemplar/ring/client.py', 'apps/web/app/api/ring/devices/route.ts'],
    tests: ['engine/tests/ring/test_live.py', 'engine/tests/ring/test_client.py'],
  },
  {
    id: 'history',
    name: 'Event history polling',
    status: 'observed',
    uses:
      'Cursor-paginated event history with event_types filters, polled every 15 seconds. Each new event is ingested once and cached by event. Backtests read the same history.',
    calls: ['GET /v1/history/devices/{id}/events'],
    basis: 'Events created with Simulate in the Playground showed up in history and were picked up by the poller.',
    code: ['engine/exemplar/ring/client.py', 'engine/exemplar/api/ingest.py'],
    tests: ['engine/tests/ring/test_live.py', 'engine/tests/ring/test_client.py'],
    log: [LOG_PG2],
  },
  {
    id: 'media',
    name: 'Event-scoped media download',
    status: 'observed',
    uses:
      'The clip for perception and a snapshot for the interface. The 303 redirect to a pre-signed URL is followed without the access token; the client waits for the recording to be ready and retries 416 and 425 with backoff.',
    calls: ['POST /v1/devices/{id}/media/video/download', 'POST /v1/devices/{id}/media/image/download'],
    basis: 'Every Playground clip Exemplar perceived arrived this way.',
    code: ['engine/exemplar/ring/client.py'],
    tests: ['engine/tests/ring/test_client.py', 'engine/tests/ring/test_live.py'],
    log: [
      { id: 'RING-5', anchor: 'ring-5-pre-signed-media-get-blocks-for-12-48-s-with-no-progress-signal-live' },
      { id: 'RING-6', anchor: 'ring-6-a-video-longer-than-the-event-returns-200-with-the-next-events-footage-not-206-live' },
    ],
  },
  {
    id: 'whep',
    name: 'WHEP live view',
    status: 'observed',
    uses:
      'Live view in the browser through a server proxy, with 2 fps frame capture feeding a live fact ticker. The proxy forwards the session address untouched and accepts only live-view sessions on Ring’s API. The Ring watermark is never covered.',
    calls: ['POST /v1/devices/{id}/media/streaming/whep/sessions', 'DELETE of the session address'],
    basis: 'Run in Chrome against the Playground’s simulated device.',
    code: [
      'apps/web/app/api/ring/stream/route.ts',
      'apps/web/app/hooks/useWebRTCStream.ts',
      'apps/web/lib/video-processors/frame-grab.ts',
      'apps/web/lib/ring/whep-url.mjs',
    ],
    tests: ['apps/web/lib/ring/ring.test.mjs'],
    log: [{ id: 'RING-14', anchor: 'ring-14-whep-session-url-has-a-long-query-string-that-delete-needs-verbatim' }],
  },

  // ---------------------------------------------------------------- tested against fixtures or mocks
  {
    id: 'webhooks',
    name: 'Signed webhooks',
    status: 'fixture',
    uses:
      'An event-driven path next to polling. The X-Signature HMAC-SHA256 is checked over the raw body with a constant-time compare, the route answers inside Ring’s response window, deliveries are deduplicated on meta.request_id, and the app_integration_added and app_integration_removed lifecycle events are handled. Valid deliveries are forwarded to the engine.',
    calls: ['Webhook deliveries to our route'],
    basis:
      'The Playground does not send webhooks, so the route is tested with signed fixtures, including tampered, re-serialised, unsigned and duplicate payloads, in both Node and Python. A replay tool posts the same fixtures to a running app.',
    code: [
      'apps/web/app/api/ring/webhook/route.ts',
      'apps/web/lib/ring/webhook-verify.mjs',
      'apps/web/lib/ring/webhook-delivery.mjs',
      'apps/web/lib/ring/webhook-handler.ts',
      'engine/exemplar/ring/webhook.py',
      'scripts/send_signed_webhook.py',
    ],
    tests: ['apps/web/lib/ring/ring.test.mjs', 'engine/tests/ring/test_webhook.py', 'engine/tests/ring/test_send_signed_webhook.py'],
    log: [LOG_PG2],
  },
  {
    id: 'oauth',
    name: 'OAuth app-integration flow',
    status: 'fixture',
    uses:
      'The production sign-in path: authorization code with PKCE, rotating refresh tokens, and account linking through app-integrations. The Playground token path is used for the demo.',
    calls: ['Authorization code exchange', 'Refresh-token rotation', 'POST and PATCH of the app-integration link'],
    basis: 'Tested against mocked HTTP. The Playground has no OAuth client, so the flow has not been run end to end against Ring.',
    code: ['engine/exemplar/ring/tokens.py', 'engine/exemplar/api/routes/ring.py'],
    tests: ['engine/tests/ring/test_tokens.py'],
    log: [{ id: 'PG-5', anchor: 'pg-5-oauth-app-mode-cannot-be-exercised-with-playground-access' }],
  },

  // ---------------------------------------------------------------- built behind a flag
  {
    id: 'chime',
    name: 'Chime playback (early access)',
    status: 'flag',
    uses: 'An optional rule action that plays a chime on the camera when a rule fires. It is the one call that acts on a device.',
    calls: ['POST /v1/devices/{id}/media/audio/playback'],
    basis:
      'Off unless EXEMPLAR_CHIME_ENABLED is set. Tested against a mocked client. The Playground’s simulated device has no chime slot, so the call has not been exercised live.',
    code: ['engine/exemplar/ring/client.py', 'engine/exemplar/monitor/actions.py', 'engine/exemplar/api/config.py'],
    tests: ['engine/tests/ring/test_client.py'],
    log: [{ id: 'RING-13', anchor: 'ring-13-chime-playback-returns-a-generic-400-and-cannot-be-exercised' }],
  },
]
