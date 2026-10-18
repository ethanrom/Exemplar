// Typed, cached loaders for the exported data. Server-side only (they read apps/showcase/data/ at build time, so a
// page component can call them directly and pass plain props to client components).
// Erasable TypeScript, ES modules, explicit .ts extensions.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type {
  CalDoc,
  ClaimsDoc,
  ClipCard,
  CreditEntry,
  CuratedDoc,
  LiveDoc,
  Manifest,
  RuleDoc,
  RunDoc,
  RunSlug,
  Sketch,
  TraceJson,
} from "./types.ts";

export const RUN_SLUGS: readonly RunSlug[] = ["p1-playground", "vehicle", "theft-a", "theft-b"];

/** "frames" (default) shows every Playground frame; "trace" hides the frames of clips whose permission is pending. */
export type SandboxMedia = "frames" | "trace";

let root: string | undefined;

/** The data folder: $SHOWCASE_DATA_DIR, else ./data (next build and npm scripts run in apps/showcase), else next to lib/. */
export function dataRoot(): string {
  if (root) return root;
  const candidates: string[] = [];
  if (process.env.SHOWCASE_DATA_DIR) candidates.push(path.resolve(process.env.SHOWCASE_DATA_DIR));
  candidates.push(path.resolve(process.cwd(), "data"));
  try {
    candidates.push(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "data"));
  } catch {
    // import.meta.url is not a file URL inside some bundles; the other candidates still apply
  }
  for (const c of candidates) {
    if (existsSync(path.join(c, "manifest.json"))) {
      root = c;
      return c;
    }
  }
  throw new Error("showcase data folder not found (expected data/manifest.json); run the export or set SHOWCASE_DATA_DIR");
}

const cache = new Map<string, unknown>();

function read<T>(rel: string): T {
  const hit = cache.get(rel);
  if (hit !== undefined) return hit as T;
  const value = JSON.parse(readFileSync(path.join(dataRoot(), rel), "utf-8")) as T;
  cache.set(rel, value);
  return value;
}

export function sandboxMedia(): SandboxMedia {
  return process.env.SANDBOX_MEDIA === "trace" ? "trace" : "frames";
}

export const loadManifest = (): Manifest => read<Manifest>("manifest.json");
export const loadLive = (): LiveDoc => read<LiveDoc>("live.json");
export const loadCalibration = (): CalDoc => read<CalDoc>("calibration/package.json");
export const loadCredits = (): CreditEntry[] => read<CreditEntry[]>("credits.json");
export const loadClaims = (): ClaimsDoc => read<ClaimsDoc>("claims.json");
export const loadCurated = (): CuratedDoc => read<CuratedDoc>("lab/curated.json");
export const loadSketches = (): Sketch[] => read<Sketch[]>("lab/sketches.json");

export const loadRun = (slug: RunSlug | string): RunDoc => read<RunDoc>(`runs/${slug}.json`);
export const loadRule = (slug: string): RuleDoc => read<RuleDoc>(`rules/${slug}.json`);
export const loadTrace = (alias: string): TraceJson => read<TraceJson>(`traces/${alias}.json`);

function listJson(dir: string): string[] {
  return readdirSync(path.join(dataRoot(), dir))
    .filter((f) => f.endsWith(".json"))
    .map((f) => f.slice(0, -".json".length))
    .sort();
}

/** Slugs of every exported rule, sorted. */
export const ruleSlugs = (): string[] => listJson("rules");
/** Slugs of every exported run, in the order of RUN_SLUGS (only those present in this export). */
export const runSlugs = (): RunSlug[] => {
  const have = new Set(listJson("runs"));
  return RUN_SLUGS.filter((s) => have.has(s));
};
export const traceAliases = (): string[] => listJson("traces");

/**
 * Apply the SANDBOX_MEDIA variant (SPEC 9.3): in "trace" mode the clips whose credit is pending the owner's decision
 * become trace-only (no poster, no sheet). The exported library.json is the "frames" variant.
 */
export function resolveMedia(cards: ClipCard[], credits: CreditEntry[], mode: SandboxMedia): ClipCard[] {
  if (mode === "frames") return cards;
  const pending = new Set(credits.filter((c) => c.permission.status === "pending_user_decision").map((c) => c.id));
  return cards.map((c) => {
    if (!pending.has(c.credit)) return c;
    const { poster: _poster, sheet: _sheet, ...rest } = c;
    return { ...rest, media: "trace_only" as const };
  });
}

/** The library, resolved for the build's SANDBOX_MEDIA variant. */
export function loadLibrary(mode: SandboxMedia = sandboxMedia()): ClipCard[] {
  return resolveMedia(read<ClipCard[]>("library.json"), loadCredits(), mode);
}

export function loadClip(alias: string, mode: SandboxMedia = sandboxMedia()): ClipCard {
  const card = loadLibrary(mode).find((c) => c.alias === alias);
  if (!card) throw new Error(`unknown clip alias: ${alias}`);
  return card;
}

/** The credits entry a clip points to. */
export function creditOf(card: ClipCard): CreditEntry {
  const e = loadCredits().find((c) => c.id === card.credit);
  if (!e) throw new Error(`clip ${card.alias} has no credits entry`);
  return e;
}

/** Every rule of a run, in the run's recorded candidate order (rank = index + 1). */
export function loadRunCandidates(slug: RunSlug | string): RuleDoc[] {
  return loadRun(slug).candidates.map((s) => loadRule(s));
}
