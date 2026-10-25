import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { ME, mockApi, renderAt, VIDEO } from './helpers'
import { api } from '../api/client'
import { Ingestion } from '../pages/Ingestion'

const stages = (a: [number, number], e: [number, number], c: [number, number]) => [
  { stage: 'activity', done: a[0], total: a[1] }, { stage: 'engagement', done: e[0], total: e[1] }, { stage: 'clips', done: c[0], total: c[1] }]

afterEach(() => vi.useRealTimers())

const progress = (done: number) => [{ video_id: 1, title: 'Final show', stages: stages([done, 100], [100, 100], [1, 1]) }]

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

it('refreshes committed counts and the successful timestamp after three seconds', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-25T12:00:00Z'))
  vi.spyOn(api, 'processing').mockResolvedValueOnce(progress(10)).mockResolvedValue(progress(12))
  const view = await act(async () => render(<Ingestion />))
  expect(screen.getByRole('progressbar', { name: 'Activity overall' })).toHaveAttribute('aria-valuenow', '10')
  expect(view.container.querySelector('time')).toHaveAttribute('datetime', '2026-10-25T12:00:00.000Z')
  await act(async () => vi.advanceTimersByTimeAsync(3000))
  expect(screen.getByRole('progressbar', { name: 'Activity overall' })).toHaveAttribute('aria-valuenow', '12')
  expect(view.container.querySelector('time')).toHaveAttribute('datetime', '2026-10-25T12:00:03.000Z')
})

it('keeps the last received counts and timestamp on failure, then recovers automatically', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-25T12:00:00Z'))
  vi.spyOn(api, 'processing').mockResolvedValueOnce(progress(10))
    .mockRejectedValueOnce(new Error('Service unavailable')).mockResolvedValue(progress(14))
  const view = await act(async () => render(<Ingestion />))
  await act(async () => vi.advanceTimersByTimeAsync(3000))
  expect(screen.getByRole('progressbar', { name: 'Activity overall' })).toHaveAttribute('aria-valuenow', '10')
  expect(screen.getByRole('status')).toHaveTextContent(/retrying automatically/i)
  expect(view.container.querySelector('time')).toHaveAttribute('datetime', '2026-10-25T12:00:00.000Z')
  await act(async () => vi.advanceTimersByTimeAsync(3000))
  expect(screen.getByRole('progressbar', { name: 'Activity overall' })).toHaveAttribute('aria-valuenow', '14')
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

it('waits for each response before scheduling another poll and stops after unmount', async () => {
  vi.useFakeTimers()
  let resolve!: (value: ReturnType<typeof progress>) => void
  const load = vi.spyOn(api, 'processing').mockReturnValue(new Promise((done) => { resolve = done }))
  const view = await act(async () => render(<Ingestion />))
  await act(async () => vi.advanceTimersByTimeAsync(9000))
  expect(load).toHaveBeenCalledTimes(1)
  await act(async () => { resolve(progress(10)) })
  view.unmount()
  await act(async () => vi.advanceTimersByTimeAsync(6000))
  expect(load).toHaveBeenCalledTimes(1)
})
