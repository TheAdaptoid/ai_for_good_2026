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

it('accepts, defers, and edits a clip through the review widget', async () => {
  let current = clip
  const calls = mockApi({ 'GET /api/auth/me': ME, 'GET /api/labels': LABELS, 'GET /api/videos': [VIDEO],
    'GET /api/person-clips/8': () => current, 'GET /api/person-clips/8/summary': SUMMARY,
    'POST /api/person-clips/8/accept': () => (current = { ...clip, review_status: 'ACCEPTED' }),
    'POST /api/person-clips/8/defer': () => (current = { ...clip, review_status: 'DEFERRED' }),
    'POST /api/person-clips/8/edit': () => (current = { ...clip, review_status: 'EDITED' }) })
  renderAt('/review/clips/8')
  const widget = await screen.findByRole('region', { name: 'Review this clip' })
  expect(within(widget).getByText('UNREVIEWED')).toBeInTheDocument()
  await userEvent.click(await within(widget).findByRole('button', { name: 'Accept' }))
  expect(await within(widget).findByText('ACCEPTED')).toBeInTheDocument()

  await userEvent.click(within(widget).getByRole('button', { name: 'Edit…' }))
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
  expect(await within(widget).findByText('EDITED')).toBeInTheDocument()
  expect(calls.find((c) => c.path === '/api/person-clips/8/edit')?.body).toEqual(
    { activity_label: 'Dancing', positive_score: 0.9, neutral_score: 0.3, negative_score: 0.1 })

  await userEvent.click(within(await screen.findByRole('region', { name: 'Review this clip' })).getByRole('button', { name: 'Defer' }))
  expect(await screen.findByRole('heading', { name: 'Review', level: 1 })).toBeInTheDocument()
  expect(window.location.pathname).toBe('/review')
  expect(current.review_status).toBe('DEFERRED')
  expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual(
    ['/api/person-clips/8/accept', '/api/person-clips/8/edit', '/api/person-clips/8/defer'])
})

it('adds a typed activity label through Other, reusing an existing one when it matches', async () => {
  const calls = mockApi({ 'GET /api/auth/me': ME, 'GET /api/labels': LABELS, 'GET /api/person-clips/8': clip,
    'GET /api/person-clips/8/summary': SUMMARY, 'POST /api/person-clips/8/edit': { ...clip, review_status: 'EDITED' } })
  renderAt('/review/clips/8')
  const widget = await screen.findByRole('region', { name: 'Review this clip' })
  await userEvent.click(await within(widget).findByRole('button', { name: 'Edit…' }))
  await userEvent.selectOptions(within(widget).getByLabelText('Activity label'), 'Other…')
  await userEvent.click(within(widget).getByRole('button', { name: 'Save edit' }))
  expect(within(widget).getByRole('alert')).toHaveTextContent('Type a name for the new activity label.')
  await userEvent.type(within(widget).getByLabelText(/New activity label/), '  Beatboxing ')
  await userEvent.click(within(widget).getByRole('button', { name: 'Save edit' }))
  await within(widget).findByRole('button', { name: 'Accept' })
  expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ activity_label: 'Beatboxing', create_activity_label: true })

  await userEvent.click(within(widget).getByRole('button', { name: 'Edit…' }))
  await userEvent.selectOptions(within(widget).getByLabelText('Activity label'), 'Other…')
  await userEvent.type(within(widget).getByLabelText(/New activity label/), 'dancing')
  await userEvent.click(within(widget).getByRole('button', { name: 'Save edit' }))
  await within(widget).findByRole('button', { name: 'Accept' })
  expect(calls.filter((c) => c.method === 'POST')[1].body).toEqual({ activity_label: 'Dancing' })
})
