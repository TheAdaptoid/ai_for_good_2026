import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { annotation, ME, mockApi, PARTICIPANTS, renderAt, VIDEO } from './helpers'

const LIST = [
  { person_id: 'Person_0001', video_count: 2, detection_count: 30 },
  { person_id: 'Person_0002', video_count: 1, detection_count: 10 },
]
const DETAIL = { person_id: 'Person_0001', videos: [
  { video_id: 7, title: 'Songwriting camp', first_seconds: 10, last_seconds: 40, detection_count: 20 },
  { video_id: 8, title: 'Final show', first_seconds: 5, last_seconds: 6, detection_count: 2 },
] }

describe('participant view', () => {
  it('filters the participant list', async () => {
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/participants': LIST })
    renderAt('/participants')
    await screen.findByRole('link', { name: /Person_0002/ })
    await userEvent.type(screen.getByLabelText('Find an anonymous ID'), '0001')
    expect(screen.queryByRole('link', { name: /Person_0002/ })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Person_0001/ })).toBeInTheDocument()
  })

  it('lists every video with presence and annotations linking to the moment', async () => {
    mockApi({
      'GET /api/auth/me': ME, 'GET /api/participants': LIST, 'GET /api/participants/Person_0001': DETAIL,
      'GET /api/videos/7': VIDEO, 'GET /api/videos/7/participants': PARTICIPANTS,
      'GET /api/videos/8': { ...VIDEO, video_id: 8, title: 'Final show' },
      'GET /api/videos/8/participants': [{ ...PARTICIPANTS[0], intervals: [{ start_seconds: 5, end_seconds: 6, detection_count: 2 }] }],
      'GET /api/annotations': [annotation()],
      'GET /api/clips': [{ clip_id: 3, video_id: 7, start_frame: 240, end_frame: 480, start_seconds: 10,
        end_seconds: 20, person_ids: ['Person_0001'], priority_score: 1.5, priority_method: 'm@1', created_at: 'x' }],
    })
    renderAt('/participants/Person_0001')
    expect(await screen.findByRole('heading', { name: 'Person_0001' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Songwriting camp' })).toHaveAttribute('href', '/videos/7?t=10.00')
    expect(screen.getByRole('link', { name: 'Final show' })).toHaveAttribute('href', '/videos/8?t=5.00')
    const presence = screen.getByLabelText('Person_0001 presence in Songwriting camp')
    expect(within(presence).getAllByRole('link').map((l) => l.getAttribute('href'))).toEqual(['/videos/7?t=10.00', '/videos/7?t=30.00'])
    expect(screen.getByRole('link', { name: /Singing/ })).toHaveAttribute('href', '/videos/7?t=10.00&annotation=1')
    expect(screen.getByText('UNREVIEWED')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '0:10–0:20' })).toHaveAttribute('href', '/videos/7?t=10.00&clip=3')
  })

  it('reports an unknown participant', async () => {
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/participants': LIST })
    renderAt('/participants/Person_9999')
    expect(await screen.findByText('This participant was not found.')).toBeInTheDocument()
  })
})
