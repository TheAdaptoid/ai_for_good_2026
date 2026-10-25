import { expect, test, type Page } from '@playwright/test'
import type { components } from '../src/api/schema.js'

type Annotation = components['schemas']['Annotation']
type VideoSummary = components['schemas']['VideoSummary']

// Entirely synthetic responses; abort every media request before it reaches the service.
const video: VideoSummary = {
  video_id: 7, title: 'Synthetic songwriting session with a deliberately long program title',
  filename: 'synthetic.mp4', duration_seconds: 100, fps: 24, frame_count: 2400,
  participant_count: 1, detection_count: 2, clip_count: 1, person_clip_count: 1, human_annotation_count: 0,
  annotation_counts: { UNREVIEWED: 1, ACCEPTED: 0, EDITED: 0, REJECTED: 0, DEFERRED: 0 },
}
const annotation: Annotation = {
  annotation_id: 1, video_id: 7, clip_id: 3, person_id: 'Person_0001', label_id: 1,
  label_name: 'Synthetic singing observation', label_category: 'activity', start_frame: 240,
  end_frame: 480, start_seconds: 10, end_seconds: 20, confidence: 0.61,
  source: 'AI', review_status: 'UNREVIEWED', created_at: '2026-10-24T00:00:00Z', updated_at: '2026-10-24T00:00:00Z',
}
const clip = { clip_id: 3, video_id: 7, start_frame: 0, end_frame: 720, start_seconds: 0,
  end_seconds: 30, person_ids: ['Person_0001'], priority_score: 2.07,
  priority_method: 'synthetic-review-priority-method-with-a-long-name@1', created_at: '2026-10-24T00:00:00Z' }
const people = [{ person_id: 'Person_0001', first_seconds: 10, last_seconds: 40,
  detection_count: 2, intervals: [{ start_seconds: 10, end_seconds: 40, detection_count: 2 }] }]

async function fixture(page: Page) {
  const csv: Record<string, string> = {
    '/exports/database/clips': 'clip_id,video_id,start_time_seconds,end_time_seconds,person_ids\n8,7,5,35,Person_0001\n',
    '/exports/annotations': 'annotation_id,label_name,source,review_status\n1,Synthetic singing observation,AI,UNREVIEWED\n',
    '/exports/history': 'event_id,annotation_id,action\n',
  }
  const routes: Record<string, unknown> = {
    '/auth/me': { staff_id: 1, username: 'synthetic-staff-with-a-long-username', is_active: true },
    '/videos': [video], '/videos/7': video, '/videos/7/participants': people,
    '/participants': [{ person_id: 'Person_0001', video_count: 1, detection_count: 2 }],
    '/participants/Person_0001': { person_id: 'Person_0001', videos: [{ ...video, ...people[0] }] },
    '/person-clips': [{ clip_id: 8, video_id: 7, start_seconds: 5, end_seconds: 35, person_ids: ['Person_0001'], mean_positive_score: 0.5, impact_score: 0.55, created_at: '2026-10-25T00:00:00Z' }],
    '/person-clips/8': { clip_id: 8, video_id: 7, start_seconds: 5, end_seconds: 35, person_ids: ['Person_0001'], mean_positive_score: 0.5, impact_score: 0.55, created_at: '2026-10-25T00:00:00Z' },
    '/person-clips/8/summary': { impact_score: 0.55, dominant_activity: 'Synthetic singing', activity_distribution: { 'Synthetic singing': 1 }, visible_affect: { positive: 0.5, neutral: 0.4, negative: 0.1, observation_count: 2 } },
    '/clips': [clip], '/clips/3': clip, '/annotations': [annotation], '/annotations/1': annotation,
    '/annotations/1/history': [], '/imports': [],
    '/labels': [{ label_id: 1, name: annotation.label_name, category: 'activity', is_active: true }],
  }
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const path = new URL(route.request().url()).pathname.slice(4)
    if (path.endsWith('/stream')) return route.abort()
    if (path in csv) return route.fulfill({ contentType: 'text/csv', body: csv[path] })
    return route.fulfill({ json: routes[path] ?? { detail: 'Synthetic missing route' },
      status: path in routes ? 200 : 404 })
  })
}

async function fits(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
}

async function capture(page: Page, name: string) {
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe('light')
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim())).toBe('#581b9e')
  if (await page.locator('.sidebar').count()) {
    await expect(page.locator('.sidebar')).toHaveCSS('background-color', 'rgb(244, 244, 245)')
  } else {
    await expect(page.locator('.login__card')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  }
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: `test-results/design/${name}.png`, fullPage: true,
    mask: [page.locator('video')], maskColor: '#000000' })
}

async function readable(page: Page) {
  const ratios = await page.locator('.stat__value, .stat__label, table.videos tbody th a, .panel h2, .facts dt, .facts dd, .badge, .legend, button.primary').evaluateAll((elements) => {
    const luminance = (color: string) => {
      const channels = color.match(/[\d.]+/g)!.slice(0, 3).map((part) => {
        const value = Number(part) / 255
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
      })
      return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
    }
    return elements.map((element) => {
      let surface: Element = element
      while (getComputedStyle(surface).backgroundColor === 'rgba(0, 0, 0, 0)' && surface.parentElement) {
        surface = surface.parentElement
      }
      const text = luminance(getComputedStyle(element).color)
      const background = luminance(getComputedStyle(surface).backgroundColor)
      return { text: element.textContent, ratio: (Math.max(text, background) + 0.05) / (Math.min(text, background) + 0.05) }
    })
  })
  expect(ratios.length).toBeGreaterThan(0)
  for (const item of ratios) expect(item.ratio, item.text ?? '').toBeGreaterThanOrEqual(4.5)
}

for (const [width, colorScheme] of [[320, 'light'], [390, 'light'], [768, 'light'], [1280, 'light'], [1280, 'dark'], [2400, 'light']] as const) {
  test(`${width}px ${colorScheme} device preference: staff screens stay light and keyboard usable`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 2400 ? 1092 : 900 })
    await page.emulateMedia({ colorScheme })
    await fixture(page)
    const name = `${width}-${colorScheme}`
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
    for (const card of await page.locator('.stat').all()) {
      await expect(card).toHaveCSS('background-color', 'rgb(244, 244, 245)')
      await expect(card.locator('.stat__value')).toHaveCSS('color', 'rgb(88, 27, 158)')
      await expect(card.locator('.stat__label')).toHaveCSS('color', 'rgb(88, 27, 158)')
    }
    await expect(page.getByRole('region', { name: 'Totals' }).getByText('Participants', { exact: true })).toBeVisible()
    await readable(page)
    await expect(page.getByRole('button', { name: 'Start feedback mode' })).toBeVisible()
    await expect(page.locator('agentation-toolbar [data-agentation-root]')).toHaveAttribute('data-agentation-theme', 'light')
    await page.keyboard.press('Tab')
    await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('main')).toBeFocused()
    await fits(page)
    await capture(page, `${name}-dashboard`)
    const videoLink = page.getByRole('link', { name: video.title, exact: true })
    const unusedWidth = await videoLink.evaluate((element) => {
      const cell = element.closest('th')!
      const style = getComputedStyle(cell)
      return cell.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
        - element.getBoundingClientRect().width
    })
    expect(Math.abs(unusedWidth)).toBeLessThan(2)
    await expect(videoLink).toHaveCSS('background-color', 'rgb(88, 27, 158)')
    await expect(videoLink).toHaveCSS('color', 'rgb(255, 255, 255)')
    await expect(videoLink).toHaveCSS('text-decoration-line', 'none')
    await videoLink.hover()
    expect(await videoLink.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe('rgb(88, 27, 158)')
    await readable(page)
    await videoLink.focus()
    expect(await videoLink.evaluate((element) => getComputedStyle(element).outlineStyle)).toBe('solid')
    await page.keyboard.press('Enter')
    await expect(page.getByRole('heading', { name: video.title, exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Back', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Dashboard', level: 1 })).toBeVisible()
    await expect(page.getByRole('region', { name: 'Review queue' })).toHaveCount(0)
    await expect(page.getByText('Export', { exact: true })).toHaveCount(0)
    await page.getByRole('link', { name: 'Data view', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Data view', level: 1 })).toBeVisible()
    await expect(page.getByRole('region', { name: 'CSV preview' })).toContainText('Person_0001')
    await fits(page)
    await capture(page, `${name}-data`)
    await page.getByLabel('Dataset').selectOption('history')
    await expect(page.getByRole('columnheader')).toHaveText(['event_id', 'annotation_id', 'action'])
    await expect(page.getByRole('cell', { name: 'No records in this dataset yet.' })).toBeVisible()
    await page.getByLabel('Dataset').selectOption('annotations')
    await expect(page.getByRole('region', { name: 'CSV preview' })).toContainText('Synthetic singing observation')
    await page.getByText('Export', { exact: true }).click()
    await expect(page.getByRole('link', { name: 'Annotations (CSV)' })).toBeVisible()
    await expect(page.getByText('Download database records or staff review data as CSV or JSON.')).toBeVisible()
    await page.getByText('Export', { exact: true }).click()
    await page.getByRole('link', { name: 'Dashboard', exact: true }).click()
    await page.getByRole('button', { name: 'Browse participants' }).click()
    await expect(page.getByLabel('Find an anonymous ID')).toBeVisible()
    await page.getByRole('link', { name: 'Review', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Review', level: 1 })).toBeVisible()
    const queueItem = page.getByRole('region', { name: 'Review queue' }).getByRole('listitem').first()
    await expect(queueItem).toContainText('1 participant · review priority 2.07')
    if (width >= 1280) {
      const link = await queueItem.getByRole('link').boundingBox()
      const metadata = await queueItem.locator('span').boundingBox()
      expect(link).not.toBeNull()
      expect(metadata).not.toBeNull()
      expect(Math.abs(link!.y - metadata!.y)).toBeLessThan(2)
      const nav = page.getByRole('navigation', { name: 'Main' })
      const dashboard = await nav.getByRole('link', { name: 'Dashboard' }).boundingBox()
      const review = await nav.getByRole('link', { name: 'Review' }).boundingBox()
      expect(review!.y).toBeGreaterThan(dashboard!.y + dashboard!.height)
    }
    await fits(page)
    await capture(page, `${name}-queue`)

    await page.goto('/videos/7?annotation=1&clip=3')
    const panel = page.getByRole('complementary', { name: 'Review annotation' })
    await expect(panel).toBeVisible()
    await expect(page.getByText('The video file is unavailable on this machine.')).toBeVisible()
    await fits(page)
    await readable(page)
    await capture(page, `${name}-review`)
    const presence = page.getByRole('button', { name: /Person_0001 on screen/ })
    await page.getByRole('button', { name: 'Clip #8 at 0:05', exact: true }).click()
    await expect(page.getByRole('complementary', { name: 'Database clip' })).toContainText('Synthetic singing')
    await expect(page.getByRole('complementary', { name: 'Database clip' })).toContainText('0.500')
    await capture(page, `${name}-database-clip`)
    await page.getByLabel('Clip filter').selectOption('impact')
    await expect(page.getByRole('region', { name: 'High-impact clips' })).toContainText('Impact score 0.550')
    await expect(page.getByRole('region', { name: 'High-impact clips' }).getByRole('listitem')).toHaveCount(1)
    await fits(page)
    await readable(page)
    await capture(page, `${name}-high-impact`)
    await page.getByLabel('Clip filter').selectOption('all')
    await page.goto('/videos/7?annotation=1&clip=3')
    await presence.focus()
    await page.keyboard.press('Enter')
    await expect(page.locator('.row--axis .row__label')).toHaveText('0:10')
    await expect(presence).toBeFocused()
    await expect(presence).toHaveAttribute('aria-current', 'time')
    await expect(presence).toHaveCSS('background-color', 'rgb(242, 94, 13)')
    expect(await presence.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe('solid')
    await panel.getByRole('button', { name: 'Edit…' }).click()
    await expect(panel.getByRole('button', { name: 'Save edit' })).toBeVisible()
    await fits(page)
    await capture(page, `${name}-edit`)
    await page.getByRole('button', { name: 'Add annotation' }).click()
    await expect(page.getByRole('button', { name: 'Save annotation' })).toBeVisible()
    await expect(page.getByRole('complementary', { name: 'Review annotation' })).toHaveCount(0)
    await expect(page.getByRole('complementary', { name: 'Review clip' })).toHaveCount(0)
    expect(new URL(page.url()).searchParams.has('annotation')).toBe(false)
    expect(new URL(page.url()).searchParams.has('clip')).toBe(false)
    await fits(page)
    await capture(page, `${name}-create`)

    await page.goto('/videos/7?clip=3')
    await expect(page.getByRole('complementary', { name: 'Review clip' })).toBeVisible()
    await fits(page)
    await capture(page, `${name}-clip`)
    await page.getByRole('button', { name: 'Back', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Dashboard', level: 1 })).toBeVisible()
    await page.goto('/participants/Person_0001')
    await expect(page.getByRole('heading', { name: 'Person_0001' })).toBeVisible()
    await fits(page)
    await capture(page, `${name}-participant`)

    await page.route((url) => ['/api/videos', '/api/clips', '/api/person-clips'].includes(url.pathname),
      (route) => route.fulfill({ json: [] }))
    await page.goto('/')
    await expect(page.getByText('No processed videos in the database.')).toBeVisible()
    await fits(page)
    await capture(page, `${name}-empty`)
    await page.getByRole('link', { name: 'Review', exact: true }).click()
    await expect(page.getByText('No review clips have been imported yet.')).toBeVisible()
    await capture(page, `${name}-queue-empty`)
    await page.route((url) => url.pathname === '/api/videos',
      (route) => route.fulfill({ status: 503, json: { detail: 'Synthetic service unavailable. Try again.' } }))
    await page.goto('/')
    await expect(page.getByRole('alert')).toContainText('Synthetic service unavailable.')
    await fits(page)
    await capture(page, `${name}-error`)

    await page.route((url) => url.pathname === '/api/auth/me',
      (route) => route.fulfill({ status: 401, json: { detail: 'Not signed in' } }))
    await page.goto('/')
    await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
    await expect(page.getByLabel('Username')).toBeFocused()
    await fits(page)
    await capture(page, `${name}-login`)
  })
}

test('playhead spans every participant row and remains aligned after scrolling', async ({ page }) => {
  await fixture(page)
  await page.route('**/api/videos/7/participants', (route) => route.fulfill({ json: Array.from({ length: 40 }, (_, index) => ({
    ...people[0], person_id: `Person_${String(index + 1).padStart(4, '0')}`,
  })) }))
  await page.goto('/videos/7')
  await expect(page.getByRole('link', { name: 'Person_0040', exact: true })).toHaveCount(1)
  const presence = page.getByRole('button', { name: /Person_0001 on screen/ })
  await presence.click()
  const geometry = await page.locator('.timeline').evaluate((timeline) => {
    timeline.scrollTop = timeline.scrollHeight
    const playhead = timeline.querySelector('.timeline__playhead')!.getBoundingClientRect()
    const track = timeline.querySelector('.timeline__people .row:last-child .row__track')!.getBoundingClientRect()
    return { height: playhead.height, viewport: timeline.clientHeight,
      bottom: playhead.bottom, trackBottom: track.bottom, x: playhead.left, expectedX: track.left + track.width * 0.1 }
  })
  expect(geometry.height).toBeGreaterThan(geometry.viewport)
  expect(Math.abs(geometry.bottom - geometry.trackBottom)).toBeLessThan(2)
  expect(Math.abs(geometry.x - geometry.expectedX)).toBeLessThan(2)
})
