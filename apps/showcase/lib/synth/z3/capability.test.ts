// When the "Check with real Z3" button is offered: desktop, cross-origin isolated, SharedArrayBuffer, enough memory.
import { test } from "node:test";
import assert from "node:assert/strict";
import { UNAVAILABLE_NOTE, isMobile, z3Capability } from "./capability.ts";
import type { CapabilityEnv } from "./capability.ts";

const DESKTOP: CapabilityEnv = {
  crossOriginIsolated: true, hasSharedArrayBuffer: true, deviceMemory: 8, platform: "Win32", maxTouchPoints: 0,
  userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36",
};

test("a desktop, isolated browser is offered Z3", () => {
  assert.deepEqual(z3Capability(DESKTOP), { ok: true });
  assert.deepEqual(z3Capability({ ...DESKTOP, deviceMemory: undefined }), { ok: true }); // Firefox and Safari have no deviceMemory
  assert.deepEqual(z3Capability({ ...DESKTOP, deviceMemory: 4 }), { ok: true });
});

test("each missing requirement hides it", () => {
  assert.deepEqual(z3Capability({ ...DESKTOP, crossOriginIsolated: false }), { ok: false, reason: "not-isolated" });
  assert.deepEqual(z3Capability({ ...DESKTOP, crossOriginIsolated: undefined }), { ok: false, reason: "not-isolated" });
  assert.deepEqual(z3Capability({ ...DESKTOP, hasSharedArrayBuffer: false }), { ok: false, reason: "no-shared-array-buffer" });
  assert.deepEqual(z3Capability({ ...DESKTOP, deviceMemory: 2 }), { ok: false, reason: "low-memory" });
  assert.deepEqual(z3Capability({ ...DESKTOP, deviceMemory: 0.5 }), { ok: false, reason: "low-memory" });
});

test("mobile browsers are detected", () => {
  const ios = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
  const android = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Mobile Safari/537.36";
  assert.ok(isMobile({ userAgent: ios }));
  assert.ok(isMobile({ userAgent: android }));
  assert.ok(isMobile({ uaDataMobile: true }));
  assert.ok(isMobile({ userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15", platform: "MacIntel", maxTouchPoints: 5 })); // iPadOS
  assert.ok(!isMobile({ userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", platform: "MacIntel", maxTouchPoints: 0 }));
  assert.ok(!isMobile(DESKTOP));
  assert.deepEqual(z3Capability({ ...DESKTOP, userAgent: android }), { ok: false, reason: "mobile" });
});

test("the one-line note", () => {
  assert.equal(UNAVAILABLE_NOTE, "Real Z3 runs on desktop browsers");
});
