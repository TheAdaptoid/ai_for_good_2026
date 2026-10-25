import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'
import { ME, mockApi, renderAt, VIDEO } from './helpers'

it('browses stored clips across pages using database IDs and exact times', async () => {
  const clips = Array.from({ length: 21 }, (_, index) => ({ clip_id: index + 1, video_id: 7,
    start_seconds: index + 0.25, end_seconds: index + 0.75, person_ids: ['Person_0001'], created_at: 'now' }))
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
  expect(screen.getByRole('link', { name: 'Clips (CSV)' })).toHaveAttribute('href', '/api/exports/database/clips?format=csv')
})
