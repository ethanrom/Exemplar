// SANDBOX_MEDIA=trace build step: delete the posters and frame sheets of clips whose permission is still pending the
// owner's decision, so the trace-only variant ships no file for them (SPEC 9.3).
//
//   node apps/showcase/scripts/export/prune-media.mjs [--data DIR] [--media DIR] [--dry-run]
//
// Run it on a copy of public/media (or in CI before `next build`); the committed media folder is the "frames" variant.
import { existsSync, readFileSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const showcase = path.resolve(here, "..", "..");
const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 ? path.resolve(args[i + 1]) : fallback;
};
const dataDir = opt("--data", path.join(showcase, "data"));
const mediaDir = opt("--media", path.join(showcase, "public", "media"));
const dry = args.includes("--dry-run");

const library = JSON.parse(readFileSync(path.join(dataDir, "library.json"), "utf-8"));
const credits = JSON.parse(readFileSync(path.join(dataDir, "credits.json"), "utf-8"));
const pending = new Set(credits.filter((c) => c.permission.status === "pending_user_decision").map((c) => c.id));

let removed = 0;
for (const clip of library) {
  if (!pending.has(clip.credit)) continue;
  for (const sub of ["posters", "sheets"]) {
    const f = path.join(mediaDir, sub, `${clip.alias}.webp`);
    if (existsSync(f)) {
      if (!dry) rmSync(f);
      removed += 1;
    }
  }
}
console.log(`prune-media: ${dry ? "would remove" : "removed"} ${removed} file(s) for ${pending.size} pending credit(s)`);
