// Drive the real UI, without mocks. State is checkpointed after every mutation.
// node scripts/run-series.mjs ../artifacts/series-....json
import { chromium, expect } from '@playwright/test'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import path from 'node:path'

const input = process.argv[2]
if (!input) throw new Error('Pass the generated dataset manifest path')
const statePath = input.replace(/\.json$/, '-state.json')
let state
try {
  state = JSON.parse(await readFile(statePath, 'utf8'))
} catch (e) {
  if (e.code !== 'ENOENT') throw e
  state = JSON.parse((await readFile(input, 'utf8')).replace(/^\uFEFF/, ''))
}
const save = () => writeFile(statePath, JSON.stringify(state, null, 2))
const base = process.env.FRONTEND_URL || 'http://localhost:8080'
const browser = await chromium.launch({
  channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge',
  headless: true,
})
const page = await browser.newPage({
  viewport: { width: 1440, height: 1000 },
  acceptDownloads: true,
})
const errors = []
page.on('pageerror', (error) => errors.push(error.message))
const post = (pathname) =>
  page.waitForResponse(
    (r) => new URL(r.url()).pathname === pathname && r.request().method() === 'POST' && r.ok(),
  )
try {
  for (const d of state.datasets) {
    await page.goto(base + '/datasets')
    if (!d.dataset_id) {
      await page.getByRole('button', { name: 'Добавить источник', exact: true }).click()
      await page.getByLabel('Название', { exact: true }).fill(d.name)
      await page.getByLabel('Схема', { exact: true }).fill('public')
      await page.getByLabel('Таблица', { exact: true }).fill(d.table)
      await page.getByLabel('Столбец ID', { exact: true }).fill('id')
      await page.getByLabel('Признаки через запятую').fill(d.features.join(', '))
      await page.getByLabel('Целевая переменная').fill('y')
      const response = post('/api/v1/datasets')
      await page.getByRole('button', { name: 'Зарегистрировать источник' }).click()
      d.dataset_id = (await (await response).json()).id
      await save()
    } else {
      await page.locator('.dataset-card').filter({ hasText: d.table }).click()
    }
    if (!d.version_id) {
      const response = post(`/api/v1/datasets/${d.dataset_id}/versions`)
      await page.getByRole('button', { name: 'Создать версию', exact: true }).click()
      d.version_id = (await (await response).json()).id
      await save()
    }
    await expect(
      page
        .locator('.version-row')
        .filter({ hasText: d.version_id.slice(0, 8) })
        .locator('.badge'),
    ).toHaveText('Готова', { timeout: 180000 })
    console.log(
      JSON.stringify({
        event: 'dataset_ready',
        rows: d.rows,
        features: d.features.length,
        version: d.version_id,
      }),
    )
  }
  for (const d of state.datasets) {
    if (!d.experiment_id) {
      await page.goto(`${base}/experiments/new?dataset=${d.dataset_id}&version=${d.version_id}`)
      await expect(page.getByRole('combobox', { name: 'Версия', exact: true })).toHaveValue(
        d.version_id,
      )
      await page.getByLabel('Измеряемых пар', { exact: true }).fill('10')
      await page.getByLabel('Прогревочных пар', { exact: true }).fill('1')
      await page.getByLabel('Минимум пар для вывода', { exact: true }).fill('10')
      await page.getByLabel('Потоки Python BLAS', { exact: true }).fill('1')
      await page.getByLabel('Seed', { exact: true }).fill('42')
      await page.getByLabel('Тайм-аут попытки, с', { exact: true }).fill('300')
      await page.getByText('Ограничения качества и ресурсов', { exact: true }).click()
      await page.getByLabel('Максимальный RMSE', { exact: true }).fill('0.15')
      await page.getByRole('button', { name: 'Проверить конфигурацию' }).click()
      await expect(page.getByText('1 вариантов · 20 измеряемых запусков')).toBeVisible()
      const response = post('/api/v1/experiments')
      await page.getByRole('button', { name: 'Создать эксперимент', exact: true }).click()
      d.experiment_id = (await (await response).json()).id
      await save()
    } else await page.goto(`${base}/experiments/${d.experiment_id}`)
    const current = await (
      await page.request.get(`${base}/api/v1/experiments/${d.experiment_id}`)
    ).json()
    if (current.status === 'draft') {
      const response = post(`/api/v1/experiments/${d.experiment_id}/start`)
      await page.getByRole('button', { name: 'Запустить', exact: true }).click()
      await response
    }
    console.log(
      JSON.stringify({
        event: 'experiment_started',
        rows: d.rows,
        features: d.features.length,
        id: d.experiment_id,
      }),
    )
  }
  // Keep the browser on real results while waiting; the worker serializes workloads.
  const deadline = Date.now() + 30 * 60 * 1000
  while (Date.now() < deadline) {
    let terminal = 0
    for (const d of state.datasets) {
      const res = await (
        await page.request.get(`${base}/api/v1/experiments/${d.experiment_id}/results`)
      ).json()
      d.status = res.status
      d.completed = res.completed_runs
      if (['succeeded', 'partial', 'failed', 'cancelled', 'interrupted'].includes(res.status))
        terminal++
    }
    await save()
    console.log(
      JSON.stringify({
        event: 'progress',
        terminal,
        runs: state.datasets.map((d) => ({
          rows: d.rows,
          p: d.features.length,
          status: d.status,
          completed: d.completed,
        })),
      }),
    )
    if (terminal === state.datasets.length) break
    await new Promise((resolve) => setTimeout(resolve, 20000))
  }
  const directory = path.join(path.dirname(input), `series-${state.series}-ui`)
  await mkdir(directory, { recursive: true })
  for (const d of state.datasets) {
    await page.goto(`${base}/experiments/${d.experiment_id}`)
    await expect(
      page.getByRole('heading', { name: 'Ресурсы и качество', exact: true }),
    ).toBeVisible({ timeout: 15000 })
    await expect(page.getByText('10 из 10 полных пар · 0 исключено', { exact: true })).toBeVisible()
    const results = await (
      await page.request.get(`${base}/api/v1/experiments/${d.experiment_id}/results`)
    ).json()
    const analysis = results.analysis.cases[0]
    const format = (value, digits = 2) =>
      new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(value)
    const verdicts = {
      madlib: 'MADlib',
      sklearn: 'scikit-learn',
      comparable: 'Сопоставимы',
      inconclusive: 'Недостаточно оснований',
      no_feasible_backend: 'Нет подходящего варианта',
    }
    await expect(page.locator('.recommend-card h2')).toHaveText(verdicts[analysis.verdict])
    await expect(page.locator('.recommend-facts strong').nth(0)).toHaveText(
      `${format(analysis.statistics.median_ratio)}×`,
    )
    await expect(page.locator('.recommend-facts strong').nth(1)).toHaveText(
      `${format(analysis.statistics.ci95[0])} – ${format(analysis.statistics.ci95[1])}`,
    )
    for (const [index, backend] of ['madlib', 'sklearn'].entries()) {
      await expect(page.locator('.bar-row strong').nth(index)).toHaveText(
        `${format(analysis.statistics[`median_${backend}_ns`] / 1e9, 3)} с`,
      )
      for (const [scopeIndex, scope] of ['python_process', 'bench_container'].entries()) {
        for (const [metricIndex, metric] of ['cpu_seconds', 'peak_memory_bytes'].entries()) {
          const measured = analysis.resources[backend][scope][metric]
          const cell = page
            .locator('tbody tr')
            .nth(1 + scopeIndex * 2 + metricIndex)
            .locator('td')
            .nth(index + 1)
          const value =
            metricIndex === 0 ? format(measured.median, 4) : format(measured.median / 1024 ** 2)
          await expect(cell).toHaveText(`${value}${measured.available_pairs} измерений`)
        }
      }
    }
    await page.screenshot({
      path: path.join(directory, `${d.rows}-${d.features.length}.png`),
      fullPage: true,
    })
    const download = page.waitForEvent('download')
    await page.getByRole('link', { name: 'JSON-отчёт' }).click()
    await (
      await download
    ).saveAs(path.join(directory, `${d.rows}-${d.features.length}-report.json`))
    const exported = JSON.parse(
      await readFile(path.join(directory, `${d.rows}-${d.features.length}-report.json`), 'utf8'),
    )
    expect(exported.analysis).toEqual(results.analysis)
    await page.getByRole('button', { name: 'Запуски и попытки', exact: true }).click()
    await expect(page.locator('tbody tr')).toHaveCount(22)
    await expect(page.locator('tbody .badge.succeeded')).toHaveCount(22)
    d.ui_verified = true
    console.log(
      JSON.stringify({
        event: 'ui_verified',
        id: d.experiment_id,
        rows: d.rows,
        features: d.features.length,
      }),
    )
    await save()
  }
  state.browser_errors = errors
  await save()
  if (errors.length) throw new Error(JSON.stringify(errors))
} finally {
  await browser.close()
}
