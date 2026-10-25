import { fireEvent, screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'
import { ME, mockApi, renderAt, VIDEO } from './helpers'
import { drawnShares } from '../pieShares'

const routes = (counts: unknown) => ({ 'GET /api/auth/me': ME, 'GET /api/videos': [VIDEO], 'GET /api/participants': [],
  'GET /api/clips': [], 'GET /api/imports': [], 'GET /api/activity-counts': counts })

it('shows every activity with its share and mean, colour following the label', async () => {
  mockApi(routes([{ activity_label: 'Uncertain result', count: 6, mean_positive_score: 0.29, observation_count: 60 },
    { activity_label: 'Rapping', count: 3, mean_positive_score: 0.25, observation_count: 30 },
    { activity_label: 'Acting', count: 1, mean_positive_score: null, observation_count: 0 }]))
  renderAt('/')
  const legend = await screen.findByRole('list', { name: 'Activity shares' })
  expect(within(legend).getAllByRole('listitem').map((li) => li.textContent)).toEqual(
    ['Uncertain result60.0%0.290', 'Rapping30.0%0.250', 'Acting10.0%—'])
  const slices = Array.from(document.querySelectorAll('.activity-chart > svg:first-child path'))
  // Largest to smallest; activities take colour slots by rank and the uncertain result is gray.
  expect(slices.map((s) => [s.getAttribute('aria-label'), s.getAttribute('fill')])).toEqual([
    ['Uncertain result: 6 windows, 60.0%', 'var(--series-neutral)'], ['Rapping: 3 windows, 30.0%', 'var(--series-1)'],
    ['Acting: 1 windows, 10.0%', 'var(--series-2)']])
  expect(screen.getByRole('img', { name: 'Pie chart of activity shares by label' })).not.toHaveTextContent('10windows')
  const pie = screen.getByRole('img', { name: /^Pie chart/ })
  fireEvent.focus(slices[1])
  expect(pie).toHaveTextContent('30.0%Rapping')
  expect((slices[1] as SVGPathElement).style.transform).toMatch(/^translate\(/) // pops out
  expect((slices[0] as SVGPathElement).style.transform).toBe('')
  // Bars run from highest mean to lowest and keep the pie's colours; no observations means no bar.
  const bars = Array.from(document.querySelectorAll('.affect-bars path'))
  expect(bars.map((b) => [b.getAttribute('aria-label'), b.getAttribute('fill')])).toEqual([
    ['Uncertain result: mean positive engagement score 0.290', 'var(--series-neutral)'],
    ['Rapping: mean positive engagement score 0.250', 'var(--series-1)']])
  expect(screen.getByRole('img', { name: /^Bar chart/ })).toHaveTextContent('no data')
  fireEvent.focus(bars[1])
  expect(screen.getByRole('img', { name: /^Bar chart/ })).toHaveTextContent('0.250')
})

it('folds labels beyond eight into Reviewer Defined and handles empty data', async () => {
  const many = Array.from({ length: 10 }, (_, i) => ({ activity_label: `Label ${String.fromCharCode(74 - i)}`, count: 20 - i }))
  mockApi(routes(many))
  const view = renderAt('/')
  const legend = await screen.findByRole('list', { name: 'Activity shares' })
  expect(within(legend).getAllByRole('listitem')).toHaveLength(8) // seven activities + folded group
  expect(within(legend).getByText('Reviewer Defined')).toBeInTheDocument()
  expect(within(legend).queryByText('(3 labels)')).not.toBeInTheDocument()
  const fills = Array.from(document.querySelectorAll('.activity-chart > svg:first-child path'), (p) => p.getAttribute('aria-label'))
  expect(fills[0]).toMatch(/^Label J: 20/) // largest first
  expect(fills.at(-1)).toMatch(/^Reviewer Defined: 36/) // folded J..: 13 + 12 + 11
  view.unmount()
  mockApi(routes([]))
  renderAt('/')
  expect(await screen.findByText('No activity results in the database yet.')).toBeInTheDocument()
})

it('orders bars by mean positive score while each keeps its pie colour', async () => {
  mockApi(routes([
    { activity_label: 'Rapping', count: 9, mean_positive_score: 0.2, observation_count: 90 },
    { activity_label: 'Acting', count: 5, mean_positive_score: 0.4, observation_count: 50 },
    { activity_label: 'Dancing', count: 1, mean_positive_score: 0.6, observation_count: 10 },
    { activity_label: 'Walking', count: 1, mean_positive_score: null, observation_count: 0 }]))
  renderAt('/')
  await screen.findByRole('img', { name: /^Bar chart/ })
  const pie = Object.fromEntries(Array.from(document.querySelectorAll('.activity-chart > svg:first-child path'),
    (p) => [p.getAttribute('aria-label')!.split(':')[0], p.getAttribute('fill')]))
  const bars = Array.from(document.querySelectorAll('.affect-bars path'),
    (p) => [p.getAttribute('aria-label')!.split(':')[0], p.getAttribute('fill')])
  expect(bars.map(([label]) => label)).toEqual(['Dancing', 'Acting', 'Rapping'])
  for (const [label, fill] of bars) expect(fill).toBe(pie[label!])
  const axis = Array.from(document.querySelectorAll('.affect-bars .bar-group > text:last-child'), (x) => x.textContent)
  expect(axis).toEqual(['Dancing', 'Acting', 'Rapping', 'Walking']) // no observations: last
})

it('keeps the pie to scale and enlarges only a highlighted small slice', () => {
  const counts = [443, 89, 33, 19, 6, 5, 2, 2]
  const exact = counts.map((c) => c / 599)
  expect(drawnShares(counts)).toEqual(exact) // at rest: true proportions
  const boosted = drawnShares(counts, 6) // Dancing, 0.3%
  expect(boosted[6]).toBeCloseTo(3 * 2 / 599) // three times its size
  expect(boosted.reduce((a, b) => a + b, 0)).toBeCloseTo(1)
  expect(boosted[1] / boosted[0]).toBeCloseTo(89 / 443) // the rest keep their relative sizes
  expect(drawnShares(counts, 0)).toEqual(exact) // a large slice is not resized
  expect(drawnShares(counts, 3)).toEqual(exact) // Singing, 3.2%: 2% or more keeps its size
  expect(drawnShares(counts, 4)[4]).toBeCloseTo(3 * 6 / 599) // Drawing or painting, 1.0%
  // The enlarged slice still covers every point of its original span.
  const edges = (shares: number[], i: number) => [shares.slice(0, i).reduce((a, b) => a + b, 0), shares.slice(0, i + 1).reduce((a, b) => a + b, 0)]
  for (let i = 0; i < counts.length; i++) {
    const [s0, e0] = edges(exact, i), [s1, e1] = edges(drawnShares(counts, i), i)
    expect(s1).toBeLessThanOrEqual(s0 + 1e-12)
    expect(e1).toBeGreaterThanOrEqual(e0 - 1e-12)
  }
  expect(drawnShares([])).toEqual([])
})
