import { VideoProcessor, ProcessorResult } from './types'

/**
 * Exemplar live frame-grab processor.
 *
 * Captures JPEG frames from the Ring WHEP <video> at 2 fps and POSTs them (multipart: session_id,
 * device_id, t_ms, image) to the engine through the app's proxy at /api/engine/live/frames. The engine
 * turns them into the live fact ticker and, when the session ends, a `ring_live` clip that runs through
 * the deployed monitors. It is also the fallback clip source if Playground clip download misbehaves.
 *
 * - Disabled by default; enable it from the processor panel.
 * - Frames are the FULL video frame, uncropped and unscaled: Ring's mandatory watermark (logo, device
 *   id, app name, timestamp) must stay in every captured frame.
 * - A session starts at the first captured frame (t_ms = 0) and finishes when the processor is disabled,
 *   the stream goes idle for a few seconds, or the page is hidden/closed
 *   (POST /api/engine/live/sessions/{id}/finish).
 */

export const FRAME_GRAB_ID = 'exemplar-frame-grab'

const CAPTURE_INTERVAL_MS = 500 // 2 fps
const JPEG_QUALITY = 0.85
const MAX_IN_FLIGHT = 4 // drop frames rather than queue unboundedly when the engine is slow
const IDLE_FINISH_MS = 5000 // no frame for this long => the stream stopped; close the session
const FRAMES_ENDPOINT = '/api/engine/live/frames'
const finishEndpoint = (sessionId: string) => `/api/engine/live/sessions/${encodeURIComponent(sessionId)}/finish`

function newSessionId(): string {
  const c: Crypto | undefined = typeof crypto !== 'undefined' ? crypto : undefined
  if (c && typeof c.randomUUID === 'function') return c.randomUUID()
  return 'live-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10)
}

interface Session {
  id: string
  startedAt: number // performance.now() at the first captured frame
  deviceId: string
  sent: number
  failed: number
  dropped: number
  pending: Set<Promise<void>>
}

export class FrameGrabProcessor implements VideoProcessor {
  id = FRAME_GRAB_ID
  name = 'Exemplar frame grab (2 fps)'
  description = 'Sends JPEG frames from the live view to the Exemplar engine for the live fact ticker and live clips'
  enabled = false

  /** Device the live view is showing; set by the page (falls back to video.dataset.deviceId). */
  deviceId: string | null = null

  private session: Session | null = null
  private lastCaptureAt = 0
  private capturing = false
  private idleTimer: ReturnType<typeof setInterval> | null = null
  private lastFrameWall = 0
  private offscreen: HTMLCanvasElement | null = null
  private pageHideHandler: (() => void) | null = null

  /** Optional wiring from the UI. */
  configure(opts: { deviceId?: string | null }): void {
    if (opts.deviceId !== undefined) this.deviceId = opts.deviceId
  }

  async init(): Promise<void> {
    this.lastCaptureAt = 0
    if (typeof window !== 'undefined' && !this.pageHideHandler) {
      // Best effort when the tab is closed: sendBeacon survives page unload, fetch may not.
      this.pageHideHandler = () => this.finishWithBeacon()
      window.addEventListener('pagehide', this.pageHideHandler)
    }
    if (!this.idleTimer) {
      this.idleTimer = setInterval(() => {
        if (this.session && Date.now() - this.lastFrameWall > IDLE_FINISH_MS) void this.finishSession()
      }, 1000)
    }
  }

  async process(_frame: ImageData, _canvas: HTMLCanvasElement, video: HTMLVideoElement): Promise<ProcessorResult | null> {
    const now = performance.now()
    if (now - this.lastCaptureAt < CAPTURE_INTERVAL_MS || this.capturing) return null
    if (video.readyState < 2 || video.paused || !video.videoWidth || !video.videoHeight) return null
    this.lastCaptureAt = now
    this.capturing = true
    try {
      const session = this.session ?? this.startSession(now, video)
      const tMs = Math.max(0, Math.round(now - session.startedAt))
      const blob = await this.grabJpeg(video)
      if (!blob) return null
      this.lastFrameWall = Date.now()
      if (session.pending.size >= MAX_IN_FLIGHT) {
        session.dropped += 1
      } else {
        this.upload(session, tMs, blob)
      }
      return {
        id: `${this.id}-${tMs}`,
        processorId: this.id,
        timestamp: Date.now(),
        data: {
          session: session.id.slice(0, 8),
          t: `${(tMs / 1000).toFixed(1)}s`,
          sent: session.sent,
          failed: session.failed,
          dropped: session.dropped,
        },
        message: `Streaming frames to engine (${session.sent} sent)`,
      }
    } catch (err) {
      console.error('[frame-grab] capture failed', err)
      return null
    } finally {
      this.capturing = false
    }
  }

  async destroy(): Promise<void> {
    if (typeof window !== 'undefined' && this.pageHideHandler) {
      window.removeEventListener('pagehide', this.pageHideHandler)
      this.pageHideHandler = null
    }
    if (this.idleTimer) {
      clearInterval(this.idleTimer)
      this.idleTimer = null
    }
    await this.finishSession()
    this.offscreen = null
  }

  // ---- internals ---------------------------------------------------------------------------------

  private startSession(now: number, video: HTMLVideoElement): Session {
    const s: Session = {
      id: newSessionId(),
      startedAt: now,
      deviceId: this.deviceId ?? video.dataset?.deviceId ?? '',
      sent: 0,
      failed: 0,
      dropped: 0,
      pending: new Set(),
    }
    this.session = s
    this.lastFrameWall = Date.now()
    return s
  }

  /** Full-frame JPEG: no cropping, no scaling, so the Ring watermark is always part of the image. */
  private grabJpeg(video: HTMLVideoElement): Promise<Blob | null> {
    const canvas = (this.offscreen ??= document.createElement('canvas'))
    if (canvas.width !== video.videoWidth) canvas.width = video.videoWidth
    if (canvas.height !== video.videoHeight) canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) return Promise.resolve(null)
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    return new Promise((resolve) => canvas.toBlob((b) => resolve(b), 'image/jpeg', JPEG_QUALITY))
  }

  private upload(session: Session, tMs: number, blob: Blob): void {
    const form = new FormData()
    form.append('session_id', session.id)
    form.append('device_id', session.deviceId)
    form.append('t_ms', String(tMs))
    form.append('image', blob, `frame-${tMs}.jpg`)
    const p: Promise<void> = fetch(FRAMES_ENDPOINT, { method: 'POST', body: form })
      .then((res) => {
        if (res.ok) session.sent += 1
        else session.failed += 1
      })
      .catch(() => {
        session.failed += 1
      })
      .finally(() => {
        session.pending.delete(p)
      })
    session.pending.add(p)
  }

  /** Wait for in-flight uploads, then tell the engine the session is over. */
  private async finishSession(): Promise<void> {
    const session = this.session
    if (!session) return
    this.session = null // new frames start a new session
    await Promise.allSettled(Array.from(session.pending))
    if (session.sent === 0) return // nothing reached the engine; don't create an empty clip
    try {
      await fetch(finishEndpoint(session.id), { method: 'POST' })
    } catch (err) {
      console.error('[frame-grab] finishing live session failed', err)
    }
  }

  private finishWithBeacon(): void {
    const session = this.session
    if (!session || session.sent === 0) return
    this.session = null
    try {
      navigator.sendBeacon(finishEndpoint(session.id))
    } catch {
      /* page is going away; nothing else to do */
    }
  }
}

export const frameGrabProcessor = new FrameGrabProcessor()
