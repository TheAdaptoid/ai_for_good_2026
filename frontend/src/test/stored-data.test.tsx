import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'
import { ME, mockApi, renderAt, VIDEO } from './helpers'

it('browses stored clips across pages using database IDs', async () => {
  const clips = Array.from({ length: 21 }, (_, index) => ({ clip_id: index + 1, video_id: 7,
    start_seconds: index + 0.25, end_seconds: index + 0.75, person_ids: ['Person_0001'], created_at: 'now', review_status: index < 2 ? 'DEFERRED' : 'UNREVIEWED' }))
  const calls = mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [{ ...VIDEO, person_clip_count: 21 }],
    'GET /api/clips': [], 'GET /api/person-clips/status-counts': { UNREVIEWED: 19, ACCEPTED: 0, EDITED: 0, DEFERRED: 2 },
    'GET /api/person-clips': ({ url }: { url: URL }) => {
      const offset = Number(url.searchParams.get('offset'))
      const status = url.searchParams.get('review_status')
      const matching = status === 'DEFERRED' ? clips.slice(0, 2) : status ? [] : clips
      return matching.slice(offset, offset + Number(url.searchParams.get('limit')))
    } })
  renderAt('/review')
  expect(await screen.findByText('Showing 1–10 of 21')).toBeInTheDocument()
  expect(document.querySelectorAll('.clip-tile video')).toHaveLength(0)
  expect(document.querySelectorAll('.clip-tile img')).toHaveLength(10)
  expect(document.querySelector('.clip-tile img')).toHaveAttribute('src', '/api/person-clips/1/thumbnail')
  expect(screen.getByText('Page 1 of 3')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'First page' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Next page' }))
  expect(await screen.findByText('Showing 11–20 of 21')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Last page' }))
  expect(await screen.findByText('Showing 21–21 of 21')).toBeInTheDocument()
  expect(screen.getByText('Page 3 of 3')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Songwriting camp/ })).toHaveAttribute('href', '/review/clips/21')
  expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Last page' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Previous page' }))
  expect(await screen.findByText('Showing 11–20 of 21')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'First page' }))
  expect(await screen.findByText('Showing 1–10 of 21')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'All 21' })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Deferred 2' }))
  expect(await screen.findByText('Showing 1–2 of 2')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Deferred 2' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.queryByRole('button', { name: 'Next page' })).not.toBeInTheDocument()
  expect(calls.some((call) => call.path === '/api/person-clips?review_status=DEFERRED&limit=10&offset=0')).toBe(true)
  await userEvent.click(screen.getByRole('button', { name: 'Accepted 0' }))
  expect(await screen.findByText('No accepted clips.')).toBeInTheDocument()
  expect(calls.every((call) => call.method === 'GET')).toBe(true)
})

it('limits table rendering to 200 rows while retaining the complete export', async () => {
  mockApi({ 'GET /api/auth/me': ME, 'GET /api/exports/database/clips': () =>
    new Response('clip_id,person_ids\n' + Array.from({ length: 201 }, (_, i) => `${i},record-${i}\n`).join('')) })
  renderAt('/data')
  expect(await screen.findByText('Showing 200 of 201 records. Exports include all records.')).toBeInTheDocument()
  expect(screen.getAllByRole('row')).toHaveLength(201)
  expect(screen.getByRole('cell', { name: 'record-199' })).toBeInTheDocument()
  expect(screen.queryByRole('cell', { name: 'record-200' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByText('Export', { exact: true }))
  expect(screen.getByRole('link', { name: 'CSV' })).toHaveAttribute('href', '/api/exports/database/clips?format=csv')
})

it('searches the complete queue by video title or exact clip ID and preserves search across pages and tabs', async () => {
  const clips = Array.from({ length: 21 }, (_, i) => ({ clip_id: i + 1, video_id: 7,
    start_seconds: i, end_seconds: i + 0.5, person_ids: [], created_at: 'now', review_status: 'UNREVIEWED' }))
  const matching = (url: URL) => {
    const query = url.searchParams.get('search')?.toLowerCase() ?? ''
    return clips.filter((c) => !query || VIDEO.title.toLowerCase().includes(query) || String(c.clip_id) === query.replace('#', ''))
  }
  const calls = mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [{ ...VIDEO, person_clip_count: 21 }],
    'GET /api/person-clips/status-counts': ({ url }: { url: URL }) => ({ UNREVIEWED: matching(url).length, ACCEPTED: 0, EDITED: 0, DEFERRED: 0 }),
    'GET /api/person-clips': ({ url }: { url: URL }) => {
      if (url.searchParams.get('review_status') && url.searchParams.get('review_status') !== 'UNREVIEWED') return []
      const offset = Number(url.searchParams.get('offset'))
      return matching(url).slice(offset, offset + 10)
    } })
  renderAt('/review?page=3')
  await screen.findByText('Showing 21–21 of 21')
  const input = screen.getByRole('searchbox', { name: 'Search clips' })
  await userEvent.type(input, 'CAMP')
  await userEvent.click(screen.getByRole('button', { name: /^Search$/ }))
  expect(await screen.findByText('Showing 1–10 of 21')).toBeInTheDocument()
  expect(new URL(location.href).searchParams.get('page')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Last page' }))
  await screen.findByText('Showing 21–21 of 21')
  expect(new URL(location.href).searchParams.get('q')).toBe('CAMP')
  const updated = screen.getByRole('searchbox', { name: 'Search clips' })
  await userEvent.clear(updated)
  await userEvent.type(updated, '#21')
  await userEvent.click(screen.getByRole('button', { name: /^Search$/ }))
  await screen.findByText('Showing 1–1 of 1')
  expect(screen.getByRole('link', { name: /Songwriting camp/ })).toHaveAttribute('href', '/review/clips/21')
  await userEvent.click(screen.getByRole('button', { name: 'Accepted 0' }))
  expect(await screen.findByText('No clips match this search.')).toBeInTheDocument()
  expect(new URL(location.href).searchParams.get('q')).toBe('#21')
  expect(calls.some((c) => c.path === '/api/person-clips/status-counts?search=%2321')).toBe(true)
  expect(calls.some((c) => c.path.includes('review_status=ACCEPTED&search=%2321'))).toBe(true)
})


it.each(['ACCEPTED', 'EDITED', 'DEFERRED', 'UNREVIEWED'] as const)(
  'shows clip duration and the %s status style without absolute video timestamps', async (status) => {
    const clip = { clip_id: 466, video_id: 7, start_seconds: 71.25, end_seconds: 136.75,
      person_ids: ['Person_0001'], created_at: 'now', review_status: status }
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [{ ...VIDEO, person_clip_count: 1 }],
      'GET /api/person-clips': [clip],
      'GET /api/person-clips/status-counts': { UNREVIEWED: 0, ACCEPTED: 0, EDITED: 0, DEFERRED: 0, [status]: 1 } })
    renderAt('/review')
    const tile = await screen.findByRole('link', { name: /Songwriting camp/ })
    expect(within(tile).getByText('1:05 duration ·', { exact: false })).toHaveTextContent('1:05 duration · 1 participant')
    expect(within(tile).queryByText(/1:11–2:16/)).not.toBeInTheDocument()
    expect(within(tile).getByText(status)).toHaveClass(`badge--status-${status.toLowerCase()}`)
  },
)
