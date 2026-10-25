import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Disposable copy of the real data plus the clearly synthetic fixture e2e/fixtures/synthetic-import.json
// (pipeline "synthetic-fixture"). Proves the future state: imported clips, AI suggestions, review.
test.describe.configure({ mode: 'serial' })

const backend = fileURLToPath(new URL('../../backend', import.meta.url))
const fixture = fileURLToPath(new URL('./fixtures/synthetic-import.json', import.meta.url))
const database = fileURLToPath(new URL('./.tmp/e2e-8002.sqlite', import.meta.url))

async function signIn(page: Page) {
  await page.goto('/')
  await page.getByLabel('Username').fill('e2e')
  await page.getByLabel('Password').fill('e2e-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
}

const reviewPanel = (page: Page) => page.getByRole('complementary', { name: 'Review annotation' })

test('dashboard shows imported counts, the review queue, and the latest import', async ({ page }) => {
  await signIn(page)
  await expect(page.locator('.stat', { hasText: 'Review clips' })).toContainText('4')
  await expect(page.locator('.stat', { hasText: /^\d+Human annotations/ })).toContainText('0')
  await expect(page.getByText(/No review clips or suggested annotations yet/)).toHaveCount(0)
  await expect(page.getByText(/Latest pipeline import/)).toContainText('synthetic-fixture e2e')
  await page.getByRole('link', { name: 'Review', exact: true }).click()
  const queue = page.getByRole('region', { name: 'Review queue' }).getByRole('listitem')
  await expect(queue).toHaveCount(4)
  await expect(queue.first()).toContainText('review priority 2.31')
  await expect(queue.last()).toContainText('review priority not computed')
})

test('clip panel lists participants, priority, and annotations; accept keeps AI', async ({ page }) => {
  await signIn(page)
  await page.getByRole('link', { name: 'Review', exact: true }).click()
  await page.getByRole('region', { name: 'Review queue' }).getByRole('link').first().click()
  const clip = page.getByRole('complementary', { name: 'Review clip' })
  await expect(clip).toContainText('2.31')
  await expect(clip).toContainText('synthetic-fixture@1')
  for (const id of ['Person_0001', 'Person_0033', 'Person_0074']) {
    await expect(clip.getByRole('link', { name: id })).toBeVisible()
  }
  await expect(clip).not.toContainText('%')
  await expect(page.getByRole('button', { name: /^Review clip at/ })).toHaveCount(3)
  await expect(page.locator('.timeline .bar--suggestion')).toHaveCount(5)

  await clip.getByRole('button', { name: /Group Performance · whole clip/ }).click()
  await expect(reviewPanel(page).getByText('Source: AI')).toBeVisible()
  await expect(reviewPanel(page).locator('.badges').getByText('UNREVIEWED')).toBeVisible()
  await expect(reviewPanel(page)).toContainText('0.55') // model confidence, labeled as such
  await reviewPanel(page).getByRole('button', { name: 'Accept' }).click()
  await expect(reviewPanel(page).locator('.badges').getByText('ACCEPTED', { exact: true })).toBeVisible()
  await expect(reviewPanel(page).getByText('Source: AI')).toBeVisible()
  await expect(reviewPanel(page).locator('.history')).toContainText('ACCEPTED by e2e')
})

test('editing an AI affect suggestion makes it HUMAN and survives a re-import', async ({ page }) => {
  await signIn(page)
  await page.goto('/videos/7')
  await page.locator('.timeline').getByRole('button', { name: /^Visible Positive Affect/ }).click()
  await reviewPanel(page).getByRole('button', { name: 'Edit…' }).click()
  await reviewPanel(page).getByLabel('Label').selectOption({ label: 'Visible Neutral Affect' })
  await reviewPanel(page).getByRole('button', { name: 'Save edit' }).click()
  await expect(reviewPanel(page).getByText('Source: HUMAN')).toBeVisible()
  await expect(reviewPanel(page).locator('.badges').getByText('EDITED', { exact: true })).toBeVisible()
  await expect(reviewPanel(page)).toContainText('None (human value)')
  await expect(reviewPanel(page).locator('.history')).toContainText('EDITED by e2e')
  await expect(reviewPanel(page).locator('.history')).toContainText('original model confidence 0.64')

  // Same pipeline file again: reviewed work is protected, nothing duplicated or deleted.
  const output = execFileSync('uv', ['run', '--locked', 'python', 'scripts/import_pipeline_output.py',
    '--input', fixture, '--db', database], { cwd: backend, encoding: 'utf8' })
  expect(output).toContain('inserted: 0')
  expect(output).toContain('skipped_protected: 2')
  await page.reload()
  await expect(reviewPanel(page).getByRole('heading', { name: 'Visible Neutral Affect' })).toBeVisible()
  await expect(reviewPanel(page).getByText('Source: HUMAN')).toBeVisible()
  await expect(page.getByRole('button', { name: /^Review clip at/ })).toHaveCount(3)
})

test('participant view shows imported clips and annotations across videos', async ({ page }) => {
  await signIn(page)
  await page.goto('/participants/Person_0001')
  await expect(page.getByRole('heading', { name: 'Person_0001' })).toBeVisible()
  const reese = page.locator('article.appearance', { hasText: 'this is me-songwriting-camp2-reese' })
  await expect(reese.locator('.chip[href*="&clip="]')).toHaveCount(3)
  await expect(reese.getByRole('link', { name: /Visible Neutral Affect/ })).toBeVisible()
  const final = page.locator('article.appearance', { hasText: 'THIS IS ME 2025-FINAL VIDEO-1080p' })
  await expect(final.locator('.chip[href*="&clip="]')).toHaveCount(1)
  await expect(final.getByRole('link', { name: /Visible Positive Affect/ })).toBeVisible()
  await final.locator('.chip[href*="&clip="]').click()
  await expect(page.getByRole('complementary', { name: 'Review clip' })).toContainText('0.90')
})

test('exports carry the current state of imported and reviewed annotations', async ({ page }) => {
  await signIn(page)
  await page.getByRole('link', { name: 'Data view', exact: true }).click()
  await page.getByLabel('Dataset').selectOption('annotations')
  await expect(page.getByRole('region', { name: 'CSV preview' })).toContainText('Visible Neutral Affect')
  await page.getByText('Export', { exact: true }).click()
  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Annotations (JSON)' }).click()
  const rows: { label_name: string; source: string; review_status: string; confidence: number | null }[] =
    JSON.parse(readFileSync(await (await download).path(), 'utf8'))
  expect(rows).toHaveLength(6)
  expect(rows).toContainEqual(expect.objectContaining({ label_name: 'Group Performance', source: 'AI', review_status: 'ACCEPTED' }))
  expect(rows).toContainEqual(expect.objectContaining({ label_name: 'Visible Neutral Affect', source: 'HUMAN', review_status: 'EDITED', confidence: null }))
  expect(rows.filter((r) => r.review_status === 'UNREVIEWED')).toHaveLength(4)
})
