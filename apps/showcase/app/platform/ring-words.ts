// Ring's own features, quoted from Ring's public support pages. The wording is Ring's; nothing here is paraphrased
// as a claim about Ring. Retrieved 2026-10-18 through the Ring Appstore docs server (page text as served then).

export const RING_PRODUCT_PAGE = {
  title: 'Wired Doorbell 2K',
  url: 'https://ring.com/support/products/doorbells/wired-doorbell-2k',
  section: 'Features Included',
  // Quoted from the "Features Included" list; the page lists more items. Footnote 2 is attached to the first four
  // and footnote 3 to the last on the page.
  features: [
    { name: 'Single Event Alert', note: 2 },
    { name: 'Unusual Event Alert', note: 2 },
    { name: 'Video Descriptions', note: 2 },
    { name: 'Video Search', note: 2 },
    { name: 'Package, person, and vehicle detection', note: 3 },
  ],
  footnote2:
    'Compatible Ring subscription required. Features not available for customers in Illinois due to state-specific legislation. Unusual Event Alerts, Video Descriptions, and Single Event Alert, and Active Warnings availability limited to mobile devices with select primary languages. Unusual Event Alerts trains off Video Descriptions and may be impacted by the number of events and other device limitations.',
  footnote3: 'Compatible Ring subscription required. Available on select devices. This feature is dependent upon network connectivity and other factors.',
} as const

export const RING_ARTICLE = {
  title: 'Video Descriptions, Single Event Alert (beta) and Unusual Event Alert (beta)',
  url: 'https://ring.com/support/articles/97l0i/Ring-Video-Descriptions-Single-Event-Alert-Beta',
  benefits: [
    { feature: 'Video Descriptions', text: 'Provides detailed text of the event which help you quickly scan through your recordings.' },
    { feature: 'Single Event Alert (beta)', text: 'Reduces notification clutter by combining similar alerts from the same camera.' },
    {
      feature: 'Unusual Event Alert (beta)',
      text: 'Reduces notification fatigue by intelligently filtering alerts, only notifying users of unusual events.',
    },
  ],
  requirements: [
    'A compatible Ring subscription.',
    'The primary language is set to English, Spanish, French, Italian, German, Dutch, or Japanese on the mobile device.',
    'Not available for Ring devices in Illinois due to state legislation',
  ],
  beta: 'Beta features are new or experimental. While you get early access to innovative features, results might vary as we continue making improvements based on user feedback.',
} as const
