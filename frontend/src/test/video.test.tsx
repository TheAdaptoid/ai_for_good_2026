import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Annotation } from '../api/client'
import { annotation, json, LABELS, ME, mockApi, PARTICIPANTS, renderAt, VIDEO } from './helpers'

const CLIP = { clip_id: 3, video_id: 7, start_frame: 0, end_frame: 480, start_seconds: 0, end_seconds: 20,
  person_ids: ['Person_0001'], priority_score: 2.07, priority_method: 'positive-affect@1', created_at: 'x' }

function videoRoutes(store: { current: Annotation[] }, extra: Record<string, unknown> = {}) {
  return {
    'GET /api/auth/me': ME, 'GET /api/videos/7': VIDEO, 'GET /api/videos/7/participants': PARTICIPANTS,
    'GET /api/clips': [CLIP], 'GET /api/labels': LABELS,
    'GET /api/annotations': ({ url }: { url: URL }) => store.current.filter(
      (a) => url.searchParams.get('include_rejected') === 'true' || a.review_status !== 'REJECTED'),
    'GET /api/annotations/1': () => store.current[0],
    'GET /api/annotations/1/history': [],
    'GET /api/clips/3': CLIP,
    ...extra,
  }
}

describe('video view', () => {
  it('shows one row per participant and seeks when presence is clicked', async () => {
    mockApi(videoRoutes({ current: [annotation()] }))
    const { container } = renderAt('/videos/7')
    expect(await screen.findByRole('link', { name: 'Person_0002' })).toHaveAttribute('href', '/participants/Person_0002')
    const presence = screen.getByTitle('Person_0001 on screen 0:30–0:40')
    fireEvent.click(presence)
    expect(container.querySelector('video')!.currentTime).toBe(30)
  })

  it('moves the active interval highlight with fractional playback time and clears it outside presence', async () => {
    mockApi(videoRoutes({ current: [] }))
    const { container } = renderAt('/videos/7')
    const presence = await screen.findByTitle('Person_0001 on screen 0:30–0:40')
    const player = container.querySelector('video')!
    player.currentTime = 32.15
    fireEvent.timeUpdate(player)
    expect(presence).toHaveAttribute('aria-current', 'time')
    player.currentTime = 41
    fireEvent.timeUpdate(player)
    expect(presence).not.toHaveAttribute('aria-current')
    player.currentTime = 5
    fireEvent.timeUpdate(player)
    expect(screen.getByRole('button', { name: 'Review clip at 0:00' })).toHaveAttribute('aria-current', 'time')
  })

  it('labels clip review priority as a plain number, separate from confidence', async () => {
    mockApi(videoRoutes({ current: [annotation()] }))
    renderAt('/videos/7')
    const clip = await screen.findByTitle(/review priority 2\.07/)
    expect(clip.title).not.toContain('%')
    expect(screen.getByRole('button', { name: /Singing.*model confidence 0\.61/ })).toBeInTheDocument()
  })

  it('starts at the time given in the link', async () => {
    mockApi(videoRoutes({ current: [] }))
    const { container } = renderAt('/videos/7?t=42')
    await waitFor(() => expect(container.querySelector('video')).not.toBeNull())
    const player = container.querySelector('video')!
    fireEvent.loadedMetadata(player)
    expect(player.currentTime).toBe(42)
  })

  it('hides rejected annotations until asked', async () => {
    const calls = mockApi(videoRoutes({ current: [annotation({ review_status: 'REJECTED' })] }))
    renderAt('/videos/7')
    await screen.findByRole('link', { name: 'Person_0001' })
    expect(screen.queryByRole('button', { name: /^Singing/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Show rejected annotations'))
    expect(await screen.findByRole('button', { name: /^Singing/ })).toBeInTheDocument()
    expect(calls.some((c) => c.path.includes('include_rejected=true'))).toBe(true)
  })

  it('accepts a suggestion and shows the new current state', async () => {
    const store = { current: [annotation()] }
    const calls = mockApi(videoRoutes(store, {
      'POST /api/annotations/1/accept': () => {
        store.current = [annotation({ review_status: 'ACCEPTED', updated_at: 'later' })]
        return { annotation: store.current[0], event: {} }
      },
    }))
    renderAt('/videos/7')
    await userEvent.click(await screen.findByRole('button', { name: /^Singing/ }))
    const panel = await screen.findByRole('complementary', { name: 'Review annotation' })
    expect(within(panel).getByText('UNREVIEWED')).toBeInTheDocument()
    expect(within(panel).getByText('Source: AI')).toBeInTheDocument()
    await userEvent.type(within(panel).getByLabelText('Note (optional)'), 'looks right')
    await userEvent.click(within(panel).getByRole('button', { name: 'Accept' }))
    expect(await within(panel).findByText('ACCEPTED')).toBeInTheDocument()
    expect(within(panel).getByText('Source: AI')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ note: 'looks right' })
  })

  it('edits the label within its category and shows service errors', async () => {
    const calls = mockApi(videoRoutes({ current: [annotation()] }, {
      'POST /api/annotations/1/edit': () => json({ detail: 'end_frame 9999 is beyond the video' }, 400),
    }))
    renderAt('/videos/7?annotation=1')
    const panel = await screen.findByRole('complementary', { name: 'Review annotation' })
    await userEvent.click(within(panel).getByRole('button', { name: 'Edit…' }))
    const select = within(panel).getByLabelText('Label')
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Singing', 'Spoken Performance'])
    await userEvent.selectOptions(select, 'Spoken Performance')
    await userEvent.click(within(panel).getByRole('button', { name: 'Save edit' }))
    expect(await within(panel).findByRole('alert')).toHaveTextContent('beyond the video')
    expect(calls.find((c) => c.path === '/api/annotations/1/edit')?.body).toEqual({ label_id: 4, note: null })
  })

  it('creates a missed moment in frames', async () => {
    const calls = mockApi(videoRoutes({ current: [] }, {
      'POST /api/annotations': () => ({ annotation: annotation({ annotation_id: 1, source: 'HUMAN', review_status: 'ACCEPTED' }), event: {} }),
    }))
    renderAt('/videos/7')
    await userEvent.click(await screen.findByRole('button', { name: 'Add annotation' }))
    const panel = await screen.findByRole('complementary', { name: 'Add annotation' })
    await userEvent.selectOptions(within(panel).getByLabelText('Label'), 'Visible Positive Affect')
    await userEvent.clear(within(panel).getByLabelText('Start (s)'))
    await userEvent.type(within(panel).getByLabelText('Start (s)'), '10')
    await userEvent.clear(within(panel).getByLabelText('End (s)'))
    await userEvent.type(within(panel).getByLabelText('End (s)'), '12.5')
    await userEvent.selectOptions(within(panel).getByLabelText('Participant'), 'Person_0002')
    await userEvent.click(within(panel).getByRole('button', { name: 'Save annotation' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      video_id: 7, label_id: 16, start_frame: 240, end_frame: 300, person_id: 'Person_0002', note: null })
  })

  it('refuses an end before the start without calling the service', async () => {
    const calls = mockApi(videoRoutes({ current: [] }))
    renderAt('/videos/7')
    await userEvent.click(await screen.findByRole('button', { name: 'Add annotation' }))
    const panel = await screen.findByRole('complementary', { name: 'Add annotation' })
    await userEvent.clear(within(panel).getByLabelText('End (s)'))
    await userEvent.type(within(panel).getByLabelText('End (s)'), '0')
    await userEvent.clear(within(panel).getByLabelText('Start (s)'))
    await userEvent.type(within(panel).getByLabelText('Start (s)'), '5')
    await userEvent.click(within(panel).getByRole('button', { name: 'Save annotation' }))
    expect(within(panel).getByRole('alert')).toHaveTextContent('End must be at or after start')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('opens a clip panel with participants, priority, and the clip annotations', async () => {
    const inClip = annotation({ clip_id: 3, person_id: null, label_name: 'Group Performance', label_id: 7 })
    const calls = mockApi(videoRoutes({ current: [inClip] }))
    renderAt('/videos/7')
    await userEvent.click(await screen.findByRole('button', { name: 'Review clip at 0:00' }))
    const panel = await screen.findByRole('complementary', { name: 'Review clip' })
    expect(within(panel).getByText('2.07')).toBeInTheDocument()
    expect(within(panel).getByText('(positive-affect@1)')).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: 'Person_0001' })).toHaveAttribute('href', '/participants/Person_0001')
    expect(panel.textContent).not.toContain('%')
    await userEvent.click(await within(panel).findByRole('button', { name: /Group Performance · whole clip/ }))
    expect(await screen.findByRole('complementary', { name: 'Review annotation' })).toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/annotations?clip_id=3'))).toBe(true)
  })

  it('renders no label bars when no annotations exist', async () => {
    mockApi(videoRoutes({ current: [] }))
    const { container } = renderAt('/videos/7')
    await screen.findByRole('link', { name: 'Person_0002' })
    expect(container.querySelectorAll('.bar--annotation')).toHaveLength(0)
  })

  it('shows not found for an unknown video', async () => {
    mockApi({ 'GET /api/auth/me': ME })
    renderAt('/videos/99')
    expect(await screen.findByText('This video was not found.')).toBeInTheDocument()
  })
})

it('opens stored analysis independently of a review clip with the same ID', async () => {
  const storedClip = { clip_id: 3, video_id: 7, start_seconds: 5.25, end_seconds: 9.75,
    person_ids: ['Person_0002'], created_at: 'now' }
  const calls = mockApi(videoRoutes({ current: [annotation()] }, {
    'GET /api/person-clips': [storedClip], 'GET /api/person-clips/3': storedClip,
    'GET /api/person-clips/3/summary': { dominant_activity: 'Current database activity',
      activity_distribution: { 'Current database activity': 1 },
      visible_affect: { positive: 0.6, neutral: 0.3, negative: 0.1, observation_count: 1 } },
  }))
  renderAt('/videos/7?clip=3')
  await screen.findByRole('complementary', { name: 'Review clip' })
  await userEvent.click(await screen.findByRole('button', { name: 'Clip #3 at 0:05' }))
  const panel = await screen.findByRole('complementary', { name: 'Database clip' })
  expect(await within(panel).findByText('Current database activity', { selector: 'p' })).toBeInTheDocument()
  expect(within(panel).getByText('0.600')).toBeInTheDocument()
  expect(within(panel).getByRole('link', { name: 'Person_0002' })).toBeInTheDocument()
  expect(screen.queryByRole('complementary', { name: 'Review clip' })).not.toBeInTheDocument()
  expect(calls.some((call) => call.path === '/api/person-clips/3/summary')).toBe(true)
  expect(calls.every((call) => call.method === 'GET')).toBe(true)
  await userEvent.click(screen.getByRole('button', { name: 'Add annotation' }))
  expect(screen.queryByRole('complementary', { name: 'Database clip' })).not.toBeInTheDocument()
  expect(new URL(location.href).searchParams.has('person_clip')).toBe(false)
})

it('filters a video to its ten highest scored clips and seeks from the ranked list', async () => {
  const clips = Array.from({ length: 12 }, (_, index) => ({ clip_id: index + 1, video_id: 7,
    start_seconds: index * 5, end_seconds: index * 5 + 2, person_ids: ['Person_0001'],
    created_at: 'now', mean_positive_score: (index + 1) / 20, impact_score: 1.1 * (index + 1) / 20 }))
  clips[10].mean_positive_score = clips[11].mean_positive_score
  clips[10].impact_score = clips[11].impact_score
  const unscored = { ...clips[0], clip_id: 99, mean_positive_score: null, impact_score: null }
  mockApi(videoRoutes({ current: [] }, {
    'GET /api/person-clips': [...clips, unscored], 'GET /api/person-clips/11': clips[10],
    'GET /api/person-clips/11/summary': { dominant_activity: null, activity_distribution: {},
      visible_affect: { positive: 0.6, neutral: 0.3, negative: 0.1, observation_count: 18 }, impact_score: 0.66 },
  }))
  const { container } = renderAt('/videos/7')
  await screen.findByRole('button', { name: 'Clip #12 at 0:55' })
  await userEvent.selectOptions(screen.getByLabelText('Clip filter'), 'impact')
  const ranked = screen.getByRole('region', { name: 'High-impact clips' })
  const links = within(ranked).getAllByRole('button')
  expect(links).toHaveLength(10)
  expect(links[0]).toHaveTextContent('Clip #11:') // ties use earliest time
  expect(links[1]).toHaveTextContent('Clip #12:')
  expect(links[9]).toHaveTextContent('Clip #3:')
  const timeline = screen.getByRole('region', { name: 'Scrollable video timeline' })
  expect(within(timeline).getAllByRole('button', { name: /^Clip #/ })).toHaveLength(10)
  expect(within(timeline).queryByRole('button', { name: /^Clip #99 / })).not.toBeInTheDocument()
  await userEvent.click(links[0])
  expect(container.querySelector('video')!.currentTime).toBe(50)
  expect(new URL(location.href).searchParams.get('person_clip')).toBe('11')
  const panel = await screen.findByRole('complementary', { name: 'Database clip' })
  expect(await within(panel).findByText('0.660')).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Clip filter'), 'all')
  expect(within(timeline).getAllByRole('button', { name: /^Clip #/ })).toHaveLength(13)
})

it.each([null, 0])('handles missing and zero impact scores (%s)', async (impact) => {
  const clip = { clip_id: 5, video_id: 7, start_seconds: 2, end_seconds: 3,
    person_ids: ['Person_0001'], created_at: 'now', mean_positive_score: impact, impact_score: impact }
  mockApi(videoRoutes({ current: [] }, { 'GET /api/person-clips': [clip] }))
  renderAt('/videos/7')
  await screen.findByRole('button', { name: 'Clip #5 at 0:02' })
  await userEvent.selectOptions(screen.getByLabelText('Clip filter'), 'impact')
  if (impact === null) expect(screen.getByText('No clips have visible-affect observations to score.')).toBeInTheDocument()
  else expect(screen.getByRole('region', { name: 'High-impact clips' })).toHaveTextContent('Impact score 0.000')
})
