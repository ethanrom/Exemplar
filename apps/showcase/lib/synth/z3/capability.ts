// Can this browser run Z3 here? Pure functions over a small environment record, so the rules are testable in Node.
//
// Z3 needs SharedArrayBuffer (cross-origin isolation: COOP and COEP headers) and reserves a fixed 2 GB WebAssembly heap,
// so it is offered on desktop browsers only. The check never touches Z3 and loads nothing.

export interface CapabilityEnv {
  readonly crossOriginIsolated?: boolean;
  /** `typeof SharedArrayBuffer !== "undefined"`. */
  readonly hasSharedArrayBuffer?: boolean;
  readonly userAgent?: string;
  /** `navigator.userAgentData?.mobile`. */
  readonly uaDataMobile?: boolean;
  readonly platform?: string;
  readonly maxTouchPoints?: number;
  /** `navigator.deviceMemory` in GB (Chromium only, capped at 8). */
  readonly deviceMemory?: number;
}

export type Unavailable = "not-isolated" | "no-shared-array-buffer" | "mobile" | "low-memory";

export type Capability = { readonly ok: true } | { readonly ok: false; readonly reason: Unavailable };

/** The one line shown instead of the button. */
export const UNAVAILABLE_NOTE = "Real Z3 runs on desktop browsers";

const MOBILE_UA = /Android|iPhone|iPad|iPod|Mobile|Windows Phone|IEMobile|Opera Mini|BlackBerry|Silk|Kindle/i;

export function isMobile(env: CapabilityEnv): boolean {
  if (env.uaDataMobile === true) return true;
  if (env.userAgent !== undefined && MOBILE_UA.test(env.userAgent)) return true;
  // iPadOS 13+ reports a desktop Safari user agent; it is a Mac with a touch screen
  if (env.platform === "MacIntel" && (env.maxTouchPoints ?? 0) > 1) return true;
  return false;
}

export function z3Capability(env: CapabilityEnv): Capability {
  if (env.crossOriginIsolated !== true) return { ok: false, reason: "not-isolated" };
  if (env.hasSharedArrayBuffer !== true) return { ok: false, reason: "no-shared-array-buffer" };
  if (isMobile(env)) return { ok: false, reason: "mobile" };
  if (typeof env.deviceMemory === "number" && env.deviceMemory < 4) return { ok: false, reason: "low-memory" };
  return { ok: true };
}

/** Read the environment of the running page (browser only). */
export function browserEnv(): CapabilityEnv {
  const nav = (typeof navigator === "undefined" ? undefined : navigator) as
    | (Navigator & { deviceMemory?: number; userAgentData?: { mobile?: boolean } })
    | undefined;
  return {
    crossOriginIsolated: typeof crossOriginIsolated === "boolean" ? crossOriginIsolated : false,
    hasSharedArrayBuffer: typeof SharedArrayBuffer !== "undefined",
    userAgent: nav?.userAgent,
    uaDataMobile: nav?.userAgentData?.mobile,
    platform: nav?.platform,
    maxTouchPoints: nav?.maxTouchPoints,
    deviceMemory: nav?.deviceMemory,
  };
}
