import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { json, ME, mockApi, renderAt } from './helpers'

const ANNOTATIONS = 'annotation_id,label_name,source,review_status\n1,"Singing, together",AI,UNREVIEWED\n'
const HISTORY = 'event_id,annotation_id,action\n2,1,ACCEPTED\n'
const csv = (text: string) => new Response(text, { headers: { 'Content-Type': 'text/csv' } })

describe('data view', () => {
  it('previews the actual CSV response and switches datasets without changing the data', async () => {
    const calls = mockApi({ 'GET /api/auth/me': ME,
      'GET /api/exports/annotations': () => csv(ANNOTATIONS),
      'GET /api/exports/history': () => csv(HISTORY) })
    renderAt('/data')
    expect(await screen.findByRole('cell', { name: 'Singing, together' })).toBeInTheDocument()
    expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(['annotation_id', 'label_name', 'source', 'review_status'])
    await userEvent.selectOptions(screen.getByLabelText('Dataset'), 'history')
    expect(await screen.findByRole('cell', { name: 'ACCEPTED' })).toBeInTheDocument()
    expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(['event_id', 'annotation_id', 'action'])
    expect(calls.filter((call) => call.path.includes('/exports/')).map((call) => call.path)).toEqual([
      '/api/exports/annotations?format=csv', '/api/exports/history?format=csv',
    ])
    expect(calls.every((call) => call.method === 'GET')).toBe(true)
    await userEvent.click(screen.getByText('Export', { exact: true }))
    expect(screen.getByRole('link', { name: 'Annotations (CSV)' })).toHaveAttribute('href', '/api/exports/annotations?format=csv')
    expect(screen.getByRole('link', { name: 'Review history (JSON)' })).toHaveAttribute('href', '/api/exports/history?format=json')
  })

  it('shows the CSV header when there are no records', async () => {
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/exports/annotations': () => csv('annotation_id,label_name\n') })
    renderAt('/data')
    expect(await screen.findByRole('columnheader', { name: 'annotation_id' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'label_name' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'No records in this dataset yet.' })).toHaveAttribute('colspan', '2')
  })

  it('shows service errors and retries the preview', async () => {
    let failed = true
    mockApi({ 'GET /api/auth/me': ME, 'GET /api/exports/annotations': () => failed
      ? json({ detail: 'database is locked' }, 503) : csv(ANNOTATIONS) })
    renderAt('/data')
    expect(await screen.findByRole('alert')).toHaveTextContent('database is locked')
    failed = false
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('region', { name: 'CSV preview' })).toHaveTextContent('Singing, together')
  })

  it('returns to sign-in if the preview request loses its session', async () => {
    mockApi({ 'GET /api/auth/me': ME,
      'GET /api/exports/annotations': () => json({ detail: 'sign in required' }, 401) })
    renderAt('/data')
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })
})
