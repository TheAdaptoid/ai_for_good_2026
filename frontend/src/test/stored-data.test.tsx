import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'
import { ME, mockApi, renderAt, VIDEO } from './helpers'

it('browses stored clips across pages using database IDs and exact times', async () => {
  const clips = Array.from({ length: 11 }, (_, index) => ({ clip_id: index + 1, video_id: 7,
    start_seconds: index + 0.25, end_seconds: index + 0.75, person_ids: ['Person_0001'], created_at: 'now' }))
  const calls = mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [{ ...VIDEO, person_clip_count: 11 }],
    'GET /api/clips': [], 'GET /api/person-clips': ({ url }: { url: URL }) => {
      const offset = Number(url.searchParams.get('offset'))
      return clips.slice(offset, offset + Number(url.searchParams.get('limit')))
    } })
  renderAt('/review')
  expect(await screen.findByText('Showing 1–10 of 11')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Next clips' }))
  expect(await screen.findByText('Showing 11–11 of 11')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Songwriting camp/ })).toHaveAttribute('href', '/videos/7?t=10.25&person_clip=11')
  expect(screen.getByRole('button', { name: 'Next clips' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Previous clips' }))
  expect(await screen.findByText('Showing 1–10 of 11')).toBeInTheDocument()
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
