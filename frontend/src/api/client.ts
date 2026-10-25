import type { components } from './schema'

type Schemas = components['schemas']
export type StaffAccount = Schemas['StaffAccount']
export type VideoSummary = Schemas['VideoSummary']
export type VideoParticipant = Schemas['VideoParticipant']
export type PresenceInterval = Schemas['PresenceInterval']
export type ParticipantSummary = Schemas['ParticipantSummary']
export type ParticipantDetail = Schemas['ParticipantDetail']
export type ParticipantVideo = Schemas['ParticipantVideo']
export type Annotation = Schemas['Annotation']
export type ReviewEvent = Schemas['ReviewEvent']
export type ReviewResult = Schemas['ReviewResult']
export type ReviewClip = Schemas['ReviewClip']
export type PersonClip = Schemas['PersonClip']
export type StoredClipSummary = Schemas['StoredClipSummary']
export type ActivityCount = Schemas['ActivityCount']
export type VideoProgress = Schemas['VideoProgress']
export type Label = Schemas['Label']
export type ReviewStatus = Schemas['ReviewStatus']
export type CreateAnnotationRequest = Schemas['CreateAnnotationRequest']
export type EditRequest = Schemas['EditRequest']
export type ClipEditRequest = Partial<Schemas['ClipEditRequest']> // the service defaults create_activity_label
export type ReviewAction = 'accept' | 'reject' | 'defer'
export type ExportKind = 'annotations' | 'history' | 'clips' | 'activity' | 'engagement' | 'activity-history' | 'engagement-history' | 'clip-review-history'

export type ClipReviewStatus = 'UNREVIEWED' | 'ACCEPTED' | 'EDITED' | 'DEFERRED'
export const CLIP_REVIEW_STATUSES: ClipReviewStatus[] = ['UNREVIEWED', 'ACCEPTED', 'EDITED', 'DEFERRED']

export const REVIEW_STATUSES: ReviewStatus[] = ['UNREVIEWED', 'ACCEPTED', 'EDITED', 'DEFERRED', 'REJECTED']

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let unauthorized: () => void = () => {}

/** Called whenever the service reports the session is missing or expired. */
export function setUnauthorizedHandler(handler: () => void): void {
  unauthorized = handler
}

type Query = Record<string, string | number | boolean | null | undefined>

function withQuery(path: string, query?: Query): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) params.set(key, String(value))
  }
  const text = params.toString()
  return text ? `${path}?${text}` : path
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: { detail?: unknown } = await response.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      return body.detail.map((item: { msg?: string }) => item.msg ?? 'invalid value').join('; ')
    }
  } catch {
    // fall through to the status text
  }
  return response.statusText || `request failed (${response.status})`
}

async function request<T>(method: 'GET' | 'POST', path: string, body?: unknown, format: 'json' | 'text' = 'json'): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    credentials: 'same-origin',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (response.status === 401 && path !== '/auth/login') unauthorized()
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  if (response.status === 204) return undefined as T
  return (format === 'text' ? await response.text() : await response.json()) as T
}

export interface AnnotationQuery extends Query {
  video_id?: number
  person_id?: string
  clip_id?: number
  include_rejected?: boolean
}

export const api = {
  me: () => request<StaffAccount>('GET', '/auth/me'),
  login: (username: string, password: string) =>
    request<StaffAccount>('POST', '/auth/login', { username, password }),
  logout: () => request<void>('POST', '/auth/logout'),
  videos: () => request<VideoSummary[]>('GET', '/videos'),
  video: (id: number) => request<VideoSummary>('GET', `/videos/${id}`),
  videoParticipants: (id: number) => request<VideoParticipant[]>('GET', `/videos/${id}/participants`),
  participants: () => request<ParticipantSummary[]>('GET', '/participants'),
  participant: (personId: string) =>
    request<ParticipantDetail>('GET', `/participants/${encodeURIComponent(personId)}`),
  annotations: (query: AnnotationQuery) => request<Annotation[]>('GET', withQuery('/annotations', query)),
  annotation: (id: number) => request<Annotation>('GET', `/annotations/${id}`),
  history: (id: number) => request<ReviewEvent[]>('GET', `/annotations/${id}/history`),
  clips: (query: { video_id?: number; person_id?: string; order?: 'time' | 'priority'; limit?: number }) =>
    request<ReviewClip[]>('GET', withQuery('/clips', query)),
  clip: (id: number) => request<ReviewClip>('GET', `/clips/${id}`),
  personClips: (query: { video_id?: number; person_id?: string; review_status?: ClipReviewStatus; search?: string; limit?: number; offset?: number }) =>
    request<PersonClip[]>('GET', withQuery('/person-clips', query)),
  personClipStatusCounts: (search?: string) => request<Record<ClipReviewStatus, number>>('GET', withQuery('/person-clips/status-counts', { search })),
  personClip: (id: number) => request<PersonClip>('GET', `/person-clips/${id}`),
  personClipSummary: (id: number) => request<StoredClipSummary>('GET', `/person-clips/${id}/summary`),
  reviewPersonClip: (id: number, action: 'accept' | 'defer') => request<PersonClip>('POST', `/person-clips/${id}/${action}`),
  editPersonClip: (id: number, body: ClipEditRequest) => request<PersonClip>('POST', `/person-clips/${id}/edit`, body),
  activityCounts: () => request<ActivityCount[]>('GET', '/activity-counts'),
  processing: () => request<VideoProgress[]>('GET', '/processing'),
  labels: () => request<Label[]>('GET', '/labels?include_inactive=true'),
  exportCsv: (kind: ExportKind) => request<string>('GET', exportUrl(kind, 'csv').slice(4), undefined, 'text'),
  create: (body: CreateAnnotationRequest) => request<ReviewResult>('POST', '/annotations', body),
  review: (id: number, action: ReviewAction, note: string | null) =>
    request<ReviewResult>('POST', `/annotations/${id}/${action}`, { note }),
  edit: (id: number, body: EditRequest) => request<ReviewResult>('POST', `/annotations/${id}/edit`, body),
}

export const streamUrl = (videoId: number) => `/api/videos/${videoId}/stream`
export const exportUrl = (kind: ExportKind, format: 'csv' | 'json') =>
  `/api/exports/${kind === 'annotations' || kind === 'history' ? kind : `database/${kind}`}?format=${format}`
