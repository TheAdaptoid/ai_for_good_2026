import { render } from '@testing-library/react'
import { vi } from 'vitest'
import type { Annotation, Label, VideoParticipant, VideoSummary } from '../api/client'
import { App } from '../App'

type Route = unknown | ((request: { url: URL; body: unknown }) => unknown)
export interface Call { method: string; path: string; body: unknown }

export const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

/** Stub fetch with "METHOD /api/path" routes; unknown routes answer 404. Returns the call log. */
export function mockApi(routes: Record<string, Route>): Call[] {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input, 'http://localhost')
    const method = init.method ?? 'GET'
    const body = init.body ? JSON.parse(init.body as string) : undefined
    calls.push({ method, path: url.pathname + url.search, body })
    const route = routes[`${method} ${url.pathname}`] ?? (method === 'GET' && url.pathname === '/api/person-clips' ? [] : undefined)
    if (route === undefined) return json({ detail: 'not found' }, 404)
    const result = typeof route === 'function' ? route({ url, body }) : route
    return result instanceof Response ? result : json(result)
  }))
  return calls
}

export function renderAt(path: string) {
  window.history.pushState({}, '', path)
  return render(<App />)
}

export const ME = { staff_id: 1, username: 'alex', is_active: true, created_at: '2026-10-24T00:00:00Z' }

export const VIDEO: VideoSummary = {
  video_id: 7, title: 'Songwriting camp', filename: 'song.mp4', duration_seconds: 100, fps: 24,
  frame_count: 2400, participant_count: 2, detection_count: 30, clip_count: 1, person_clip_count: 0, human_annotation_count: 0,
  annotation_counts: { UNREVIEWED: 1, ACCEPTED: 0, EDITED: 0, REJECTED: 0, DEFERRED: 0 },
}

export const PARTICIPANTS: VideoParticipant[] = [
  { person_id: 'Person_0001', first_seconds: 10, last_seconds: 40, detection_count: 20,
    intervals: [{ start_seconds: 10, end_seconds: 20, detection_count: 12 },
      { start_seconds: 30, end_seconds: 40, detection_count: 8 }] },
  { person_id: 'Person_0002', first_seconds: 50, last_seconds: 60, detection_count: 10,
    intervals: [{ start_seconds: 50, end_seconds: 60, detection_count: 10 }] },
]

export function annotation(overrides: Partial<Annotation> = {}): Annotation {
  return {
    annotation_id: 1, video_id: 7, clip_id: null, person_id: 'Person_0001', label_id: 1,
    label_name: 'Singing', label_category: 'activity', start_frame: 240, end_frame: 480,
    start_seconds: 10, end_seconds: 20, confidence: 0.61, source: 'AI', review_status: 'UNREVIEWED',
    created_at: '2026-10-24T00:00:00Z', updated_at: '2026-10-24T00:00:00Z', ...overrides,
  }
}

export const LABELS: Label[] = [
  { label_id: 1, name: 'Singing', category: 'activity', description: null, is_active: true },
  { label_id: 4, name: 'Spoken Performance', category: 'activity', description: null, is_active: true },
  { label_id: 6, name: 'Rehearsal', category: 'activity', description: null, is_active: false },
  { label_id: 16, name: 'Visible Positive Affect', category: 'observation', description: null, is_active: true },
]
