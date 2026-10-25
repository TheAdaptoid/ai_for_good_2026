import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { json, ME, mockApi, renderAt, VIDEO } from './helpers'

const EMPTY = { ...VIDEO, video_id: 8, title: 'Intro', clip_count: 0,
  annotation_counts: { UNREVIEWED: 0, ACCEPTED: 0, EDITED: 0, REJECTED: 0, DEFERRED: 0 } }

describe('dashboard', () => {
  it('gives every total a short, keyboard-reachable description', async () => {
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [VIDEO], 'GET /api/participants': [],
      'GET /api/clips': [], 'GET /api/imports': [] })
    renderAt('/')
    const totals = await screen.findByRole('region', { name: 'Totals' })
    const icons = within(totals).getAllByLabelText(/^About /)
    expect(icons.map((i) => i.getAttribute('aria-label'))).toEqual(
      ['About Videos', 'About Footage', 'About Participants', 'About Clips', 'About Human Annotations'])
    for (const icon of icons) {
      expect(icon).toHaveAttribute('tabindex', '0')
      expect(icon).toHaveAccessibleDescription(/\S/)
      expect(icon.getAttribute('aria-describedby') && document.getElementById(icon.getAttribute('aria-describedby')!)!.textContent!.length).toBeLessThan(90)
    }
    expect(within(totals).getByLabelText('About Footage')).toHaveAccessibleDescription('Total running time of all videos.')
  })

  it('sorts video columns high to low, then low to high', async () => {
    const LONG = { ...EMPTY, video_id: 9, title: 'Final show', duration_seconds: 900, participant_count: 40 }
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [VIDEO, EMPTY, LONG], 'GET /api/participants': [],
      'GET /api/clips': [], 'GET /api/imports': [] })
    renderAt('/')
    await screen.findByRole('link', { name: 'Final show' })
    const titles = () => screen.getAllByRole('rowheader').map((h) => h.textContent)
    expect(titles()).toEqual(['Songwriting camp', 'Intro', 'Final show'])
    const header = screen.getByRole('columnheader', { name: /Participants/ })
    expect(header).toHaveAttribute('aria-sort', 'none')
    await userEvent.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'descending')
    expect(titles()).toEqual(['Final show', 'Songwriting camp', 'Intro'])
    await userEvent.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'ascending')
    expect(titles()).toEqual(['Songwriting camp', 'Intro', 'Final show']) // equal counts keep database order
    await userEvent.click(screen.getByRole('button', { name: /Unreviewed/ }))
    expect(header).toHaveAttribute('aria-sort', 'none')
    expect(titles()).toEqual(['Songwriting camp', 'Intro', 'Final show']) // ties keep database order
  })

  it('lists videos with participant and review counts', async () => {
    const reviewed = { ...VIDEO, person_clip_count: 6, clip_status_counts: { UNREVIEWED: 2, ACCEPTED: 2, EDITED: 1, DEFERRED: 1 } }
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [reviewed, EMPTY],
      'GET /api/participants': [{ person_id: 'Person_0001', video_count: 1, detection_count: 3 }],
      'GET /api/clips': [], 'GET /api/imports': [] })
    renderAt('/')
    const row = (await screen.findByRole('link', { name: 'Songwriting camp' })).closest('tr')!
    // Status columns count stored clips (VIDEO's one UNREVIEWED annotation is not a clip).
    // Reviewed Clips = Accepted + Edited; Deferred is not counted as reviewed.
    expect(within(row).getAllByRole('cell').map((c) => c.textContent)).toEqual(['1:40', '2', '6', '3', '2', '2', '1', '1'])
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent?.replace(/[↕↓↑]/g, ''))).toEqual(
      ['Video', 'Length', 'Participants', 'Clips', 'Reviewed Clips', 'Unreviewed', 'Accepted', 'Edited', 'Deferred'])
    expect(screen.getByRole('link', { name: 'Songwriting camp' })).toHaveAttribute('href', '/videos/7')
    expect(screen.getByText('The Performance Academy Video Intelligence')).toBeInTheDocument()
    expect(screen.getByRole('separator')).toBeInTheDocument()
    expect(screen.queryByText('TPA Video Review')).not.toBeInTheDocument()
    expect(screen.getByRole('contentinfo')).toHaveTextContent('Product of Random Forest LLC · © 2026')
    expect(screen.getByRole('link', { name: /The Performance Academy, Florida/ })).toHaveAttribute('href', '/')
    const totals = screen.getByRole('region', { name: 'Totals' })
    expect(within(totals).getByText('Participants').previousSibling).toHaveTextContent(/^11$/) // animated copy + final value for screen readers
    expect(totals.querySelectorAll('.stat__value .sr-only')[1]).toHaveTextContent('3:20') // two 100 s videos
    expect(screen.getByText('Human Annotations').previousSibling).toHaveTextContent('0')
    expect(within(screen.getByRole('region', { name: 'Totals' })).queryByText('Review clips')).not.toBeInTheDocument()
    expect(screen.queryByText('Export', { exact: true })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /^Data view$/i })).toHaveAttribute('href', '/data')
    expect(screen.queryByRole('region', { name: 'Review queue' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Browse participants' })).not.toBeInTheDocument()
  })

  it('treats an empty pipeline as normal, not as an error', async () => {
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [EMPTY], 'GET /api/participants': [], 'GET /api/clips': [], 'GET /api/imports': [] })
    renderAt('/')
    expect(await screen.findByText(/No review clips or suggested annotations yet/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText('No pipeline output has been imported yet.')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Review' }))
    expect(await screen.findByRole('heading', { name: 'Review', level: 1 })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Review queue' })).not.toBeInTheDocument()
  })

  it('shows no import line on the dashboard and no review queue on the review page', async () => {
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
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.queryByText(/Latest pipeline import/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Review' }))
    expect(await screen.findByRole('heading', { name: 'Review', level: 1 })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Review queue' })).not.toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/clips?order=priority'))).toBe(false)
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
