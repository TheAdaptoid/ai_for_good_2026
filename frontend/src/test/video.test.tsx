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

  it('shows not found for an unknown video', async () => {
    mockApi({ 'GET /api/auth/me': ME })
    renderAt('/videos/99')
    expect(await screen.findByText('This video was not found.')).toBeInTheDocument()
  })
})
