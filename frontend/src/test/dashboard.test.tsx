import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { json, ME, mockApi, renderAt, VIDEO } from './helpers'

const EMPTY = { ...VIDEO, video_id: 8, title: 'Intro', clip_count: 0,
  annotation_counts: { UNREVIEWED: 0, ACCEPTED: 0, EDITED: 0, REJECTED: 0, DEFERRED: 0 } }

describe('dashboard', () => {
  it('lists videos with participant and review counts', async () => {
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [VIDEO, EMPTY],
      'GET /api/participants': [{ person_id: 'Person_0001', video_count: 1, detection_count: 3 }] })
    renderAt('/')
    const row = (await screen.findByRole('link', { name: 'Songwriting camp' })).closest('tr')!
    expect(within(row).getAllByRole('cell').map((c) => c.textContent)).toEqual(['1:40', '2', '1', '1', '0', '0', '0', '0'])
    expect(screen.getByRole('link', { name: 'Songwriting camp' })).toHaveAttribute('href', '/videos/7')
    expect(screen.getByText('Anonymous participants').previousSibling).toHaveTextContent('1')
    expect(screen.getByRole('link', { name: 'Annotations (CSV)' })).toHaveAttribute('href', '/api/exports/annotations?format=csv')
  })

  it('treats an empty pipeline as normal, not as an error', async () => {
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [EMPTY], 'GET /api/participants': [] })
    renderAt('/')
    expect(await screen.findByText(/No review clips or suggested annotations yet/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows a retryable error when the service fails', async () => {
    let fail = true
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/participants': [],
      'GET /api/videos': () => (fail ? json({ detail: 'database is locked' }, 500) : [VIDEO]) })
    renderAt('/')
    expect(await screen.findByRole('alert')).toHaveTextContent('database is locked')
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('link', { name: 'Songwriting camp' })).toBeInTheDocument()
  })
})
