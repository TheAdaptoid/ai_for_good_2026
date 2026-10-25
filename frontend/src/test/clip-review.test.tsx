import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { json, ME, mockApi, renderAt, VIDEO } from './helpers'

const clip = { clip_id: 8, video_id: 7, start_seconds: 10.25, end_seconds: 15.75,
  person_ids: ['Person_0001'], created_at: 'now', review_status: 'UNREVIEWED' }
const SUMMARY = { dominant_activity: 'Singing', activity_distribution: { Singing: 1 },
  impact_score: 0.66, visible_affect: { positive: 0.6, neutral: 0.3, negative: 0.1, observation_count: 18 } }
const LABELS = [{ label_id: 1, name: 'Singing', category: 'activity', description: null, is_active: true },
  { label_id: 2, name: 'Dancing', category: 'activity', description: null, is_active: true },
  { label_id: 6, name: 'Rehearsal', category: 'activity', description: null, is_active: false },
  { label_id: 10, name: 'Sustained Participation', category: 'observation', description: null, is_active: true }]

it('opens only the selected clip with current activity and engagement values', async () => {
  const calls = mockApi({ 'GET /api/auth/me': ME, 'GET /api/person-clips/8': clip,
    'GET /api/person-clips/8/summary': SUMMARY, 'GET /api/labels': LABELS })
  renderAt('/review/clips/8')
  expect(await screen.findByRole('heading', { name: 'Review clip #8' })).toBeInTheDocument()
  expect(await screen.findByText('Singing', { selector: 'p' })).toBeInTheDocument()
  expect(screen.getByText('0.600')).toBeInTheDocument()
  const video = screen.getByLabelText('Clip 8') as HTMLVideoElement
  expect(video).toHaveAttribute('src', '/api/videos/7/stream#t=10.25,15.75')
  expect(video).toHaveAttribute('preload', 'auto')
  expect(video).not.toHaveAttribute('controls')
  expect(document.querySelector('.timeline')).toBeNull()
  expect(calls.some((call) => call.path.startsWith('/api/videos/'))).toBe(false)
  const pause = vi.spyOn(video, 'pause').mockImplementation(() => {})
  const play = vi.spyOn(video, 'play').mockResolvedValue()
  fireEvent.loadedMetadata(video)
  expect(video.currentTime).toBe(10.25)
  const range = screen.getByRole('slider', { name: 'Clip position' })
  expect(range).toHaveAttribute('max', '5.5')
  fireEvent.change(range, { target: { value: '3' } })
  expect(video.currentTime).toBe(13.25)
  video.currentTime = 100
  fireEvent.timeUpdate(video)
  expect(video.currentTime).toBe(15.75)
  expect(pause).toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Play clip' }))
  expect(video.currentTime).toBe(10.25)
  expect(play).toHaveBeenCalled()
  video.currentTime = 0
  fireEvent.seeking(video)
  expect(video.currentTime).toBe(10.25)
  fireEvent.error(video)
  expect(screen.getByRole('alert')).toHaveTextContent('The video file is unavailable')
})

it('handles a missing clip without opening a video', async () => {
  mockApi({ 'GET /api/auth/me': ME, 'GET /api/person-clips/99': json({ detail: 'missing' }, 404) })
  renderAt('/review/clips/99')
  expect(await screen.findByRole('alert')).toHaveTextContent('This clip was not found.')
  expect(document.querySelector('video')).toBeNull()
})

it('accepts browser-rounded clip boundaries without repeatedly seeking and replays after the end', async () => {
  const precise = { ...clip, start_seconds: 11.094416666666666, end_seconds: 16.18283333333333 }
  mockApi({ 'GET /api/auth/me': ME, 'GET /api/person-clips/8': precise,
    'GET /api/person-clips/8/summary': SUMMARY, 'GET /api/labels': LABELS })
  renderAt('/review/clips/8')
  const video = await screen.findByLabelText('Clip 8') as HTMLVideoElement
  let time = 0
  const seek = vi.fn((value: number) => { time = Math.floor(value * 1e6) / 1e6 })
  Object.defineProperty(video, 'currentTime', { configurable: true, get: () => time, set: seek })
  const pause = vi.spyOn(video, 'pause').mockImplementation(() => {})
  const play = vi.spyOn(video, 'play').mockResolvedValue()
  fireEvent.loadedMetadata(video)
  seek.mockClear()
  fireEvent.seeking(video)
  fireEvent.timeUpdate(video)
  expect(seek).not.toHaveBeenCalled()
  expect(pause).not.toHaveBeenCalled()
  time = Math.floor(precise.end_seconds * 1e6) / 1e6
  fireEvent.timeUpdate(video)
  expect(pause).toHaveBeenCalledOnce()
  await userEvent.click(screen.getByRole('button', { name: 'Play clip' }))
  expect(seek).toHaveBeenCalledExactlyOnceWith(precise.start_seconds)
  expect(play).toHaveBeenCalledOnce()
})

it('saves an edited clip and returns with a dismissible confirmation', async () => {
  let current = clip
  const calls = mockApi({ 'GET /api/auth/me': ME, 'GET /api/labels': LABELS, 'GET /api/videos': [VIDEO],
    'GET /api/person-clips/8': () => current, 'GET /api/person-clips/8/summary': SUMMARY,
    'POST /api/person-clips/8/defer': () => (current = { ...clip, review_status: 'DEFERRED' }),
    'POST /api/person-clips/8/edit': () => (current = { ...clip, review_status: 'EDITED' }) })
  renderAt('/review/clips/8')
  const widget = await screen.findByRole('region', { name: 'Review this clip' })
  expect(within(widget).getByText('UNREVIEWED')).toBeInTheDocument()
  await userEvent.click(await within(widget).findByRole('button', { name: 'Edit…' }))
  const select = within(widget).getByLabelText('Activity label')
  expect(Array.from(select.querySelectorAll('option'), (o) => o.textContent)).toEqual(
    ['Keep current (Singing)', 'Singing', 'Dancing', 'Other…'])
  await userEvent.click(within(widget).getByRole('button', { name: 'Save edit' }))
  expect(within(widget).getByRole('alert')).toHaveTextContent('Choose a new activity label or change a score.')
  await userEvent.selectOptions(select, 'Dancing')
  const positive = within(widget).getByLabelText('Visible positive')
  expect(positive).toHaveValue(0.6)
  await userEvent.clear(positive)
  await userEvent.type(positive, '0.9')
  await userEvent.click(within(widget).getByRole('button', { name: 'Save edit' }))
  expect(await screen.findByText('Changes to clip #8 saved successfully.')).toHaveAttribute('role', 'status')
  expect(calls.find((c) => c.path === '/api/person-clips/8/edit')?.body).toEqual(
    { activity_label: 'Dancing', positive_score: 0.9, neutral_score: 0.3, negative_score: 0.1 })

  expect(await screen.findByRole('heading', { name: 'Review', level: 1 })).toBeInTheDocument()
  expect(window.location.pathname).toBe('/review')
  expect(current.review_status).toBe('EDITED')
  expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual(
    ['/api/person-clips/8/edit'])
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss confirmation' }))
  expect(screen.queryByText('Changes to clip #8 saved successfully.')).not.toBeInTheDocument()
})

it.each([
  ['Accept', 'accept', 'ACCEPTED', 'accepted', 'Accepted', 2],
  ['Defer', 'defer', 'DEFERRED', 'deferred', 'Deferred', 2],
  ['Accept', 'accept', 'ACCEPTED', 'accepted', 'Accepted', 3],
  ['Edit…', 'edit', 'EDITED', 'saved', 'Edited', 2],
] as const)('%s (%s) persists %s and returns with confirmation "%s" to %s from page %s', async (button, action, status, message, tab, page) => {
  const clips = Array.from({ length: 21 }, (_, i) => ({ ...clip, clip_id: i + 1 }))
  const target = page === 3 ? 21 : 11
  const calls = mockApi({
    'GET /api/auth/me': ME, 'GET /api/videos': [{ ...VIDEO, person_clip_count: 21 }],
    'GET /api/labels': LABELS, 'GET /api/person-clips/status-counts': () => ({
      UNREVIEWED: clips.filter((c) => c.review_status === 'UNREVIEWED').length,
      ACCEPTED: clips.filter((c) => c.review_status === 'ACCEPTED').length,
      DEFERRED: clips.filter((c) => c.review_status === 'DEFERRED').length,
      EDITED: clips.filter((c) => c.review_status === 'EDITED').length,
    }),
    'GET /api/person-clips': ({ url }: { url: URL }) => {
      const matching = clips.filter((c) => !url.searchParams.has('review_status') || c.review_status === url.searchParams.get('review_status'))
      const offset = Number(url.searchParams.get('offset'))
      return matching.slice(offset, offset + 10)
    },
    [`GET /api/person-clips/${target}`]: () => clips[target - 1],
    [`GET /api/person-clips/${target}/summary`]: SUMMARY,
    [`POST /api/person-clips/${target}/${action}`]: () => (clips[target - 1] = { ...clips[target - 1], review_status: status }),
  })
  renderAt(`/review?status=UNREVIEWED&page=${page}&q=camp`)
  await screen.findByText(page === 3 ? 'Showing 21–21 of 21' : 'Showing 11–20 of 21')
  await userEvent.click(screen.getAllByRole('link', { name: /Songwriting camp/ })[0])
  await screen.findByRole('heading', { name: `Review clip #${target}` })
  const card = document.querySelector('.clip-playback-card') as HTMLElement
  expect(within(card).getByRole('heading', { name: `Review clip #${target}` })).toBeInTheDocument()
  expect(within(card).getByLabelText(`Clip ${target}`)).toBeInTheDocument()
  expect(within(card).getByRole('button', { name: 'Play clip' })).toBeInTheDocument()
  expect(within(card).getByRole('slider', { name: 'Clip position' })).toBeInTheDocument()
  await userEvent.click(await within(screen.getByRole('region', { name: 'Review this clip' })).findByRole('button', { name: button }))
  if (action === 'edit') {
    await userEvent.selectOptions(screen.getByLabelText('Activity label'), 'Dancing')
    await userEvent.click(screen.getByRole('button', { name: 'Save edit' }))
  }
  expect(await screen.findByText(action === 'edit' ? `Changes to clip #${target} saved successfully.` : `Clip #${target} ${message}.`)).toHaveAttribute('role', 'status')
  expect(window.location.pathname + window.location.search).toBe(`/review?status=UNREVIEWED&page=${page}&q=camp`)
  expect(await screen.findByText('Page 2 of 2')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Unreviewed 20' })).toHaveAttribute('aria-pressed', 'true')
  expect(clips[target - 1].review_status).toBe(status)
  await userEvent.click(screen.getByRole('button', { name: `${tab} 1` }))
  await screen.findByText('Showing 1–1 of 1')
  const tile = screen.getByRole('link', { name: /Songwriting camp/ })
  expect(within(tile).getByText(status)).toBeInTheDocument()
  await userEvent.click(tile)
  const widget = await screen.findByRole('region', { name: 'Review this clip' })
  expect(within(widget).getByText(status)).toBeInTheDocument()
  expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
})

it('keeps the clip open and shows an error when accepting fails', async () => {
  mockApi({ 'GET /api/auth/me': ME, 'GET /api/person-clips/8': clip,
    'GET /api/person-clips/8/summary': SUMMARY, 'GET /api/labels': LABELS,
    'POST /api/person-clips/8/accept': json({ detail: 'Could not save this review.' }, 500) })
  renderAt('/review/clips/8')
  await userEvent.click(await screen.findByRole('button', { name: 'Accept' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save this review.')
  expect(window.location.pathname).toBe('/review/clips/8')
  expect(screen.getByRole('button', { name: 'Accept' })).toBeEnabled()
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

it.each([['  Beatboxing ', { activity_label: 'Beatboxing', create_activity_label: true }],
  ['dancing', { activity_label: 'Dancing' }]])('saves Other label %s and returns to review', async (name, body) => {
  const calls = mockApi({ 'GET /api/auth/me': ME, 'GET /api/labels': LABELS, 'GET /api/person-clips/8': clip,
    'GET /api/videos': [VIDEO],
    'GET /api/person-clips/8/summary': SUMMARY, 'POST /api/person-clips/8/edit': { ...clip, review_status: 'EDITED' } })
  renderAt('/review/clips/8')
  const widget = await screen.findByRole('region', { name: 'Review this clip' })
  await userEvent.click(await within(widget).findByRole('button', { name: 'Edit…' }))
  await userEvent.selectOptions(within(widget).getByLabelText('Activity label'), 'Other…')
  await userEvent.click(within(widget).getByRole('button', { name: 'Save edit' }))
  expect(within(widget).getByRole('alert')).toHaveTextContent('Type a name for the new activity label.')
  await userEvent.type(within(widget).getByLabelText(/New activity label/), name)
  await userEvent.click(within(widget).getByRole('button', { name: 'Save edit' }))
  await screen.findByText('Changes to clip #8 saved successfully.')
  expect(calls.find((c) => c.method === 'POST')?.body).toEqual(body)
})
