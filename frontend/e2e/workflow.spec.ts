import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

// Runs against a fresh copy of the real data: 12 videos, 100 anonymous participants, no
// staff annotations yet; stored analysis and person clips come directly from the database.
test.describe.configure({ mode: 'serial' })

// Participant footage must never appear in saved artifacts (Constitution I): players and thumbnails are masked.
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `test-results/screens/${name}.png`, fullPage: true, mask: [page.locator('video, .clip-tile__thumb')] })

async function signIn(page: Page) {
  await page.goto('/')
  await page.getByLabel('Username').fill('e2e')
  await page.getByLabel('Password').fill('e2e-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
}

/** Wait for the player to know its duration, so seeks are applied. */
async function playerReady(page: Page) {
  await page.waitForFunction(() => (document.querySelector('video')?.readyState ?? 0) >= 1)
}

const currentTime = (page: Page) => page.locator('video').evaluate((v: HTMLVideoElement) => v.currentTime)

test('sign-in is required and failures are generic', async ({ page }) => {
  await page.goto('/participants')
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
  await page.getByLabel('Username').fill('e2e')
  await page.getByLabel('Password').fill('wrong password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toHaveText('invalid username or password')
  await shot(page, '01-login')
})

test('dashboard lists the real footage', async ({ page }) => {
  await signIn(page)
  await expect(page.locator('table.videos tbody tr')).toHaveCount(12)
  await expect(page.getByText(/No review clips or suggested annotations yet/)).toHaveCount(0)
  const summaries = await (await page.request.get('/api/videos')).json()
  const total = summaries.reduce((sum: number, video: { person_clip_count: number }) => sum + video.person_clip_count, 0)
  expect(total).toBeGreaterThan(0)
  await expect(page.locator('.stat').filter({ has: page.getByText('Clips', { exact: true }) })).toContainText(String(total))
  await expect(page.getByRole('region', { name: 'Review queue' })).toHaveCount(0)
  await expect(page.getByText('No pipeline output has been imported yet.')).toHaveCount(0)
  await expect(page.locator('.stat', { hasText: 'Participants' })).toContainText('100')
  await shot(page, '02-dashboard')
  await page.getByRole('link', { name: 'Review', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Review', level: 1 })).toBeVisible()
  await expect(page.getByText('No review clips have been imported yet.')).toBeVisible()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
})

test('video view plays, shows who is on screen, and seeks on click', async ({ page }) => {
  await signIn(page)
  await page.getByRole('link', { name: 'this is me-songwriting-camp2-reese' }).click()
  await expect(page.getByRole('heading', { name: 'this is me-songwriting-camp2-reese' })).toBeVisible()
  await expect(page.locator('.timeline__people .row')).toHaveCount(5)
  await expect(page.locator('.timeline .bar--annotation')).toHaveCount(0) // no labels are fabricated
  expect(await page.locator('.timeline .bar--clip').count()).toBeGreaterThan(0)
  await page.getByRole('button', { name: /^Clip #/ }).first().click()
  await expect(page.getByRole('complementary', { name: 'Database clip' })).toBeVisible()
  await playerReady(page)
  const bar = page.locator('.row', { has: page.getByRole('link', { name: 'Person_0045' }) }).locator('.bar--presence').nth(2)
  const title = await bar.getAttribute('title')
  const [m, s] = /on screen (\d+):(\d+)/.exec(title!)!.slice(1).map(Number)
  await bar.click()
  // The title shows whole seconds; the seek lands on the exact interval start.
  await expect.poll(async () => Math.abs((await currentTime(page)) - (m * 60 + s))).toBeLessThan(1)
  await shot(page, '03-video')
})

test('review opens one excerpt and restricts playback to its stored bounds', async ({ page }) => {
  await signIn(page)
  const [clip] = await (await page.request.get('/api/person-clips?limit=1')).json()
  await page.getByRole('link', { name: 'Review', exact: true }).click()
  await page.getByRole('region', { name: 'Database clips' }).getByRole('link').first().click()
  await expect(page).toHaveURL(new RegExp(`/review/clips/${clip.clip_id}$`))
  await playerReady(page)
  await expect(page.locator('video')).not.toHaveAttribute('controls')
  await expect(page.locator('.timeline')).toHaveCount(0)
  await expect.poll(() => currentTime(page)).toBeCloseTo(clip.start_seconds, 2)
  const slider = page.getByRole('slider', { name: 'Clip position' })
  await expect(slider).toHaveAttribute('max', String(clip.end_seconds - clip.start_seconds))
  await page.locator('video').evaluate((video: HTMLVideoElement, end: number) => { video.currentTime = end + 1 }, clip.end_seconds)
  await expect.poll(() => currentTime(page)).toBeCloseTo(clip.end_seconds, 2)
  await page.getByRole('button', { name: 'Play clip', exact: true }).click()
  await expect.poll(() => currentTime(page)).toBeLessThan(clip.end_seconds)
  await page.getByRole('button', { name: 'Pause clip', exact: true }).click()
  await page.getByRole('button', { name: 'Back to clips' }).click()
  await expect(page.getByRole('heading', { name: 'Review', exact: true })).toBeVisible()
})

test('participant view follows one person across videos', async ({ page }) => {
  await signIn(page)
  await page.getByRole('link', { name: 'Participants', exact: true }).click()
  await page.getByLabel('Find an anonymous ID').fill('0001')
  await page.getByRole('link', { name: /Person_0001/ }).click()
  await expect(page.getByRole('heading', { name: 'Person_0001' })).toBeVisible()
  await expect(page.locator('article.appearance')).toHaveCount(6)
  await shot(page, '04-participant')
  await page.getByRole('link', { name: 'this is me-songwriting-camp2-reese' }).click()
  await expect(page).toHaveURL(/\/videos\/7\?t=0\.46/)
  await playerReady(page)
  await expect.poll(() => currentTime(page)).toBeCloseTo(0.46, 1)
})

test('create, edit, history, reject, and export a human annotation', async ({ page }) => {
  await signIn(page)
  await page.goto('/videos/7')
  await page.getByRole('button', { name: 'Add annotation' }).click()
  const form = page.getByRole('complementary', { name: 'Add annotation' })
  await form.getByLabel('Label').selectOption({ label: 'Singing' })
  await form.getByLabel('Start (s)').fill('1')
  await form.getByLabel('End (s)').fill('6')
  await form.getByLabel('Participant').selectOption('Person_0001')
  await form.getByLabel('Note (optional)').fill('missed by the pipeline')
  await form.getByRole('button', { name: 'Save annotation' }).click()

  const panel = page.getByRole('complementary', { name: 'Review annotation' })
  await expect(panel.getByRole('heading', { name: 'Singing' })).toBeVisible()
  await expect(panel.getByText('Source: HUMAN')).toBeVisible()
  await expect(panel.locator('.badges').getByText('ACCEPTED', { exact: true })).toBeVisible()
  await expect(panel.getByText('None (human value)')).toBeVisible()

  await panel.getByRole('button', { name: 'Edit…' }).click()
  await panel.getByLabel('Label').selectOption({ label: 'Spoken Performance' })
  await panel.getByRole('button', { name: 'Save edit' }).click()
  await expect(panel.locator('.badges').getByText('EDITED', { exact: true })).toBeVisible()
  await expect(panel.locator('.history li')).toHaveCount(2)
  await expect(panel.locator('.history')).toContainText('CREATED by e2e')
  await expect(panel.locator('.history')).toContainText('label Singing → Spoken Performance')
  await expect(page.locator('.timeline').getByRole('button', { name: /^Spoken Performance/ })).toBeVisible()
  await shot(page, '05-review')

  // The participant view reads the same record.
  await page.goto('/participants/Person_0001')
  await expect(page.getByRole('link', { name: /Spoken Performance/ })).toBeVisible()
  await expect(page.locator('.moment-list').getByText('EDITED')).toBeVisible()

  // Export current annotations.
  await page.goto('/')
  await page.getByRole('link', { name: 'Data view', exact: true }).click()
  await page.getByLabel('Dataset').selectOption('annotations')
  await expect(page.getByRole('region', { name: 'CSV preview' })).toContainText('Spoken Performance')
  await page.getByText('Export', { exact: true }).click()
  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'CSV', exact: true }).click()
  const csv = readFileSync(await (await download).path(), 'utf8')
  expect(csv).toContain('Spoken Performance,activity')
  expect(csv).toContain('HUMAN,EDITED')

  // Rejected annotations leave the video view; their history keeps them auditable.
  await page.goto('/participants/Person_0001')
  await page.getByRole('link', { name: /Spoken Performance/ }).click()
  await page.getByRole('complementary', { name: 'Review annotation' }).getByRole('button', { name: 'Reject' }).click()
  await expect(page.getByRole('complementary', { name: 'Review annotation' }).locator('.badges').getByText('REJECTED', { exact: true })).toBeVisible()
  await expect(page.locator('.timeline').getByRole('button', { name: /^Spoken Performance/ })).toHaveCount(0)
  await expect(page.getByLabel('Show rejected annotations')).toHaveCount(0)
  await expect(page.getByRole('complementary', { name: 'Review annotation' }).locator('.history')).toContainText('REJECTED')
})
