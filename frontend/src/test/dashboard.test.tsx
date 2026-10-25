import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { json, ME, mockApi, renderAt, VIDEO } from './helpers'

const EMPTY = { ...VIDEO, video_id: 8, title: 'Intro', clip_count: 0,
  annotation_counts: { UNREVIEWED: 0, ACCEPTED: 0, EDITED: 0, REJECTED: 0, DEFERRED: 0 } }

describe('dashboard', () => {
  it('lists videos with participant and review counts', async () => {
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [VIDEO, EMPTY],
      'GET /api/participants': [{ person_id: 'Person_0001', video_count: 1, detection_count: 3 }],
      'GET /api/clips': [], 'GET /api/imports': [] })
    renderAt('/')
    const row = (await screen.findByRole('link', { name: 'Songwriting camp' })).closest('tr')!
    expect(within(row).getAllByRole('cell').map((c) => c.textContent)).toEqual(['1:40', '2', '1', '1', '0', '0', '0', '0'])
    expect(screen.getByRole('link', { name: 'Songwriting camp' })).toHaveAttribute('href', '/videos/7')
    expect(screen.getByText('Anonymous participants').previousSibling).toHaveTextContent('1')
    expect(screen.getByRole('link', { name: 'Annotations (CSV)' })).toHaveAttribute('href', '/api/exports/annotations?format=csv')
    expect(screen.queryByRole('region', { name: 'Review queue' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Browse participants' }))
    expect(await screen.findByLabelText('Find an anonymous ID')).toBeInTheDocument()
  })

  it('treats an empty pipeline as normal, not as an error', async () => {
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [EMPTY], 'GET /api/participants': [], 'GET /api/clips': [], 'GET /api/imports': [] })
    renderAt('/')
    expect(await screen.findByText(/No review clips or suggested annotations yet/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('No pipeline output has been imported yet.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Review' }))
    expect(await screen.findByText('No review clips have been imported yet.')).toBeInTheDocument()
  })

  it('lists imported clips by review priority with the latest import', async () => {
    const calls = mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [VIDEO], 'GET /api/participants': [],
      'GET /api/clips': [
        { clip_id: 9, video_id: 7, start_frame: 240, end_frame: 480, start_seconds: 10, end_seconds: 20,
          person_ids: ['Person_0001', 'Person_0002'], priority_score: 2.07, priority_method: 'm@1', created_at: 'x' },
        { clip_id: 4, video_id: 7, start_frame: 0, end_frame: 24, start_seconds: 0, end_seconds: 1,
          person_ids: [], priority_score: null, priority_method: null, created_at: 'x' }],
      'GET /api/imports': [{ run_id: 1, pipeline_name: 'clip-pipeline', pipeline_version: '1.0', models: [],
        generated_at: null, imported_at: '2026-10-25T12:00:00Z', source_name: 'out.json', input_sha256: 'x',
        counts: { inserted: 12, updated: 0, skipped_protected: 1, clips_inserted: 2, clips_updated: 0,
          clips_skipped_protected: 0, unchanged: 0, clips_unchanged: 0 } }] })
    renderAt('/')
    expect(await screen.findByText(/Latest pipeline import/)).toHaveTextContent('clip-pipeline 1.0')
    await userEvent.click(screen.getByRole('link', { name: 'Review' }))
    expect(await screen.findByRole('heading', { name: 'Review', level: 1 })).toBeInTheDocument()
    const queue = await screen.findByRole('region', { name: 'Review queue' })
    const items = await within(queue).findAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Songwriting camp · 0:10–0:20')
    expect(items[0]).toHaveTextContent('2 participants · review priority 2.07')
    expect(items[0].textContent).not.toContain('%')
    expect(items[1]).toHaveTextContent('review priority not computed')
    expect(within(items[0]).getByRole('link')).toHaveAttribute('href', '/videos/7?t=10.00&clip=9')
    expect(calls.some((c) => c.path === '/api/clips?order=priority&limit=10')).toBe(true)
  })

  it('shows a retryable error when the service fails', async () => {
    let fail = true
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/participants': [], 'GET /api/clips': [], 'GET /api/imports': [],
      'GET /api/videos': () => (fail ? json({ detail: 'database is locked' }, 500) : [VIDEO]) })
    renderAt('/')
    expect(await screen.findByRole('alert')).toHaveTextContent('database is locked')
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('link', { name: 'Songwriting camp' })).toBeInTheDocument()
  })
})
