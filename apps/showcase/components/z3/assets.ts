// Where the opt-in Z3 lives and whether this build ships it. Resolved at build time (Next inlines NEXT_PUBLIC_* and the
// release flag); scripts/z3/prebuild.mjs writes the first two into .env.production.local for a release R4 build.
import { Z3_VERSION } from '../../lib/synth/z3/protocol.ts'
import { RELEASE, releaseAtLeast } from '../site/config.ts'

/** Release R4 adds Z3 (SPEC 8); every other release has no Z3 control and no Z3 file. */
export const Z3_SHIPPED: boolean = releaseAtLeast(RELEASE, 'R4')

/** The content-hashed classic worker script under /z3/<version>/. Not requested until the user clicks. */
export const Z3_WORKER_URL: string = process.env.NEXT_PUBLIC_Z3_WORKER || `/z3/${Z3_VERSION}/z3-worker.js`

/** Estimated transfer in MB (brotli) of everything the click downloads. */
export const Z3_TRANSFER_MB: number = Number(process.env.NEXT_PUBLIC_Z3_TRANSFER_MB) || 6
