/** 75.4 → "1:15", 3725 → "1:02:05". */
export function formatTime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—'
  const whole = Math.max(0, Math.floor(seconds))
  const h = Math.floor(whole / 3600)
  const m = Math.floor((whole % 3600) / 60)
  const s = String(whole % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

/** Seconds to the nearest frame, matching how the service stores spans. */
export function toFrame(seconds: number, fps: number): number {
  return Math.round(seconds * fps)
}

export function toSeconds(frame: number, fps: number): number {
  return frame / fps
}

/** Axis tick spacing that gives roughly `target` ticks. */
export function tickStep(duration: number, target = 8): number {
  const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]
  return steps.find((step) => duration / step <= target) ?? 3600
}
