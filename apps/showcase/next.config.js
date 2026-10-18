// Static export for Vercel Hobby (SPEC section 2). Response headers cannot be set from here in export mode;
// they live in vercel.json (COOP/COEP, CSP, caching, WASM MIME type).

// Build flags (SPEC section 2). Read at build time and inlined into server and client code through `env`.
//   SHOWCASE_RELEASE = R1 | R2 | R3 | R4   pages in the nav, footer disclosure variant. Default R4 (every page, and the opt-in Z3).
//   SANDBOX_MEDIA    = frames | trace      how sandbox recordings are shown (SPEC section 9.3). Default frames.
const RELEASES = ['R1', 'R2', 'R3', 'R4']
const MEDIA = ['frames', 'trace']

function flag(name, allowed, fallback) {
  const raw = process.env[name]
  if (raw === undefined || raw === '') return fallback
  if (!allowed.includes(raw)) {
    throw new Error(`${name}=${JSON.stringify(raw)} is not valid; use one of ${allowed.join(', ')}`)
  }
  return raw
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  images: { unoptimized: true },
  trailingSlash: true,
  reactStrictMode: true,
  poweredByHeader: false,
  env: {
    SHOWCASE_RELEASE: flag('SHOWCASE_RELEASE', RELEASES, 'R4'),
    SANDBOX_MEDIA: flag('SANDBOX_MEDIA', MEDIA, 'frames'),
  },
  // Worker bundles and the Node-side TS port never touch these; stub them for the browser build.
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.resolve.fallback = { ...config.resolve.fallback, fs: false, path: false, crypto: false }
    }
    return config
  },
}

export default nextConfig
