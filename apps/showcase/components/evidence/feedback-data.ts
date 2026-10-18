// Friction-log highlights, written as what we learned and what Exemplar does about it. Anchors follow GitHub's heading
// slugs for docs/FRICTION_LOG.md and are checked by paths.test.ts.

export const LOG = 'docs/FRICTION_LOG.md'
export const FEEDBACK = 'docs/FEEDBACK.md'

export type Highlight = { id: string; area: string; learned: string; did: string; anchor: string }

export const HIGHLIGHTS: Highlight[] = [
  {
    id: 'PG-2',
    area: 'Ring Developer Playground',
    learned: 'Simulated events arrive as on-demand recordings, listed shortly after they start, with no webhook.',
    did: 'Exemplar polls event history and reads each watched clip itself, instead of relying on an event sub-type.',
    anchor: 'pg-2-simulated-events-on_demand-only-listed-27-44-s-late-no-webhook-live',
  },
  {
    id: 'RING-6',
    area: 'Ring API',
    learned: 'A video download is a window onto continuous recording, so asking for more than one event’s span runs into the next event.',
    did: 'The client always requests exactly the event’s own start-to-end span.',
    anchor: 'ring-6-a-video-longer-than-the-event-returns-200-with-the-next-events-footage-not-206-live',
  },
  {
    id: 'RING-5',
    area: 'Ring API',
    learned: 'The pre-signed media link can stay open for tens of seconds while the clip is rendered and watermarked.',
    did: 'The media step has its own long read timeout; ordinary calls keep a short one.',
    anchor: 'ring-5-pre-signed-media-get-blocks-for-12-48-s-with-no-progress-signal-live',
  },
  {
    id: 'RING-14',
    area: 'Ring API',
    learned: 'The live-view session URL carries a long query string that is part of the address.',
    did: 'The server proxy forwards it untouched and accepts only live-view session URLs on Ring’s own API.',
    anchor: 'ring-14-whep-session-url-has-a-long-query-string-that-delete-needs-verbatim',
  },
  {
    id: 'BR-1',
    area: 'Amazon Bedrock',
    learned: 'Newer Claude models differ in which request settings they accept, such as temperature, forced tool choice and thinking.',
    did: 'One tested recipe per model, with validate-and-retry on the structured output.',
    anchor: 'br-1-new-claude-models-temperature-rejected-per-model-toolchoice-and-thinking-rules',
  },
  {
    id: 'OT-10',
    area: 'Conformal calibration',
    learned: 'Computing the conformal rank in floating point is off by one for some levels.',
    did: 'Exact rational arithmetic, checked by the simulation listed above.',
    anchor: 'ot-10-float-arithmetic-in-the-conformal-rank',
  },
]
