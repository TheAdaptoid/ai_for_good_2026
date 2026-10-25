import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'
import { ME, mockApi, renderAt, VIDEO } from './helpers'

const stages = (a: [number, number], e: [number, number], c: [number, number]) => [
  { stage: 'activity', done: a[0], total: a[1] }, { stage: 'engagement', done: e[0], total: e[1] }, { stage: 'clips', done: c[0], total: c[1] }]

it('shows overall and per-video processing progress with states in words', async () => {
  mockApi({ 'GET /api/auth/me': ME, 'GET /api/videos': [VIDEO], 'GET /api/participants': [], 'GET /api/processing': [
    { video_id: 1, title: 'Final show', stages: stages([505, 2337], [3168, 3168], [1, 1]) },
    { video_id: 2, title: 'Promo', stages: stages([0, 50], [50, 50], [0, 1]) }] })
  renderAt('/')
  await userEvent.click(await screen.findByRole('link', { name: 'Data Ingestion' }))
  expect(await screen.findByRole('heading', { name: 'Data Ingestion', level: 1 })).toBeInTheDocument()
  const overall = screen.getByRole('region', { name: 'Overall progress' })
  expect(within(overall).getByRole('progressbar', { name: 'Activity overall' })).toHaveAttribute('aria-valuetext', '505 of 2387 (21.2%)')
  expect(overall).toHaveTextContent('1,882 left')
  expect(within(overall).getByRole('progressbar', { name: 'Engagement overall' })).toHaveAttribute('aria-valuenow', '3218')
  expect(within(overall).getAllByText('Complete')).toHaveLength(1)
  const promo = screen.getByRole('rowheader', { name: 'Promo' }).closest('tr')!
  expect(promo).toHaveTextContent('0 / 50 · Not started')
  expect(promo).toHaveTextContent('0 / 1 · Not started')
  expect(screen.getByRole('rowheader', { name: 'Final show' }).closest('tr')!).toHaveTextContent('505 / 2,337 · In progress')
})
