import { test, expect } from '@playwright/test'
const dataset = {
  id: 'dataset-1',
  created_at: '2026-10-21T12:00:00Z',
  spec: {
    name: 'Продажи',
    source_schema: 'public',
    source_table: 'sales',
    features: ['x1', 'x2'],
    target: 'y',
    id_column: 'id',
  },
}
const version = {
  id: 'version-1',
  dataset_id: 'dataset-1',
  status: 'ready',
  created_at: dataset.created_at,
  manifest: { row_count: 100, checksum: 'a'.repeat(64), features: ['x1', 'x2'] },
  error_code: null,
}
const experiment = {
  id: 'experiment-1',
  created_at: dataset.created_at,
  status: 'draft',
  spec: { kind: 'benchmark', backends: ['madlib', 'sklearn'], repeats: 5, warmups: 1 },
}
test.beforeEach(async ({ page }) => {
  await page.route('**/health/ready', (r) => r.fulfill({ json: { status: 'ready' } }))
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    const data: Record<string, unknown> = {
      '/datasets': [dataset],
      '/datasets/dataset-1/versions': [version],
      '/experiments': [experiment],
      '/experiments/experiment-1': experiment,
      '/experiments/experiment-1/results': {
        status: 'draft',
        total_runs: 0,
        completed_runs: 0,
        summary: [],
        analysis: null,
      },
      '/experiments/experiment-1/runs': [],
      '/experiments/experiment-1/attempts': [],
    }
    if (path in data) return route.fulfill({ json: data[path] })
    return route.fulfill({ status: 404, json: { error: { code: 'not_found' } } })
  })
})
test('history, filters and empty search', async ({ page }) => {
  await page.goto('/experiments')
  await expect(page.getByRole('heading', { name: 'Эксперименты', exact: true })).toBeVisible()
  await expect(page.getByText('#experim')).toBeVisible()
  await page.getByRole('textbox', { name: 'Поиск экспериментов' }).fill('нет такой записи')
  await expect(page.getByRole('heading', { name: 'Ничего не найдено' })).toBeVisible()
})
test('validate immutable configuration, create draft and start explicitly', async ({ page }) => {
  let created: unknown
  await page.route('**/api/v1/experiments', async (r) => {
    if (r.request().method() === 'POST') {
      created = r.request().postDataJSON()
      return r.fulfill({ json: experiment })
    }
    return r.fallback()
  })
  await page.route('**/api/v1/experiments/validate', async (r) => {
    expect(r.request().postDataJSON().dataset_version_id).toBe(version.id)
    await r.fulfill({ json: { cases: 1, runs: 12, measured_runs: 10 } })
  })
  await page.goto('/experiments/new')
  await expect(page.getByRole('combobox', { name: 'Версия', exact: true })).toHaveValue(version.id)
  await page.getByRole('button', { name: 'Проверить конфигурацию' }).click()
  await expect(page.getByText('1 вариантов · 10 измеряемых запусков')).toBeVisible()
  await page.getByRole('button', { name: 'Создать эксперимент', exact: true }).click()
  await expect(page).toHaveURL(/\/experiments\/experiment-1$/)
  expect(created).toMatchObject({ repeats: 5, warmups: 1, backends: ['madlib', 'sklearn'] })
  let started = false
  await page.route('**/api/v1/experiments/experiment-1/start', (r) => {
    started = true
    return r.fulfill({ json: { ...experiment, status: 'queued' } })
  })
  await page.getByRole('button', { name: 'Запустить', exact: true }).click()
  await expect.poll(() => started).toBe(true)
})
test('dataset registration and version creation are separate', async ({ page }) => {
  let submitted: unknown,
    versionCreated = false
  await page.route('**/api/v1/datasets', (r) => {
    if (r.request().method() === 'POST') {
      submitted = r.request().postDataJSON()
      return r.fulfill({ json: dataset })
    }
    return r.fallback()
  })
  await page.route('**/api/v1/datasets/dataset-1/versions', (r) => {
    if (r.request().method() === 'POST') {
      versionCreated = true
      return r.fulfill({ json: version })
    }
    return r.fallback()
  })
  await page.goto('/datasets')
  await page.getByRole('button', { name: 'Добавить источник', exact: true }).click()
  await page.getByLabel('Название', { exact: true }).fill('Продажи')
  await page.getByLabel('Таблица', { exact: true }).fill('sales')
  await page.getByLabel('Признаки через запятую').fill('x1, x2')
  await page.getByLabel('Целевая переменная').fill('y')
  await page.getByRole('button', { name: 'Зарегистрировать источник' }).click()
  await expect
    .poll(() => submitted)
    .toMatchObject({ features: ['x1', 'x2'], source_table: 'sales' })
  expect(versionCreated).toBe(false)
  await page.getByRole('button', { name: 'Создать версию', exact: true }).click()
  await expect.poll(() => versionCreated).toBe(true)
})
test('backend error is visible and retry works', async ({ page }) => {
  await page.route('**/api/v1/experiments?*', (r) =>
    r.fulfill({ status: 503, json: { error: { code: 'metadata_unavailable' } } }),
  )
  await page.goto('/experiments')
  await expect(page.getByRole('alert')).toContainText('metadata_unavailable')
  await page.unroute('**/api/v1/experiments?*')
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
})
test('mobile navigation, no page overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/experiments')
  await page.getByRole('button', { name: 'Открыть меню' }).click()
  await page.getByRole('navigation').getByRole('link', { name: 'Датасеты' }).click()
  await expect(page.getByRole('heading', { name: 'Датасеты', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
})

test('cancellation requires explicit confirmation', async ({ page }) => {
  let cancelled = false
  await page.route('**/api/v1/experiments/experiment-1', (r) =>
    r.fulfill({ json: { ...experiment, status: 'running' } }),
  )
  await page.route('**/api/v1/experiments/experiment-1/cancel', (r) => {
    cancelled = true
    return r.fulfill({ json: { ...experiment, status: 'cancelling' } })
  })
  await page.goto('/experiments/experiment-1')
  await page.getByRole('button', { name: 'Отменить', exact: true }).click()
  await expect(
    page.getByText('Остановить эксперимент? Завершённые результаты сохранятся.'),
  ).toBeVisible()
  expect(cancelled).toBe(false)
  await page.getByRole('button', { name: 'Да, остановить' }).click()
  await expect.poll(() => cancelled).toBe(true)
})
test('results show case recommendation and unavailable resources, not zeros', async ({ page }) => {
  const m = { median: null, available_pairs: 0, unavailable_pairs: 5 }
  const resources = {
    python_process: { cpu_seconds: m, peak_memory_bytes: m },
    bench_container: { cpu_seconds: m, peak_memory_bytes: m },
  }
  await page.route('**/api/v1/experiments/experiment-1/results', (r) =>
    r.fulfill({
      json: {
        status: 'succeeded',
        total_runs: 12,
        completed_runs: 12,
        summary: [],
        analysis: {
          policy: {},
          cases: [
            {
              case_id: 'case-1',
              config: { sample_size: 100, fit_intercept: true },
              verdict: 'inconclusive',
              reasons: ['required_resources_unavailable'],
              statistics: {
                pairs: 5,
                median_ratio: 1,
                ci95: [0.8, 1.2],
                median_madlib_ns: 1000000,
                median_sklearn_ns: 1000000,
              },
              expected_pairs: 5,
              excluded_pairs: [],
              resources: { madlib: resources, sklearn: resources },
              constraints: {},
            },
          ],
        },
      },
    }),
  )
  await page.goto('/experiments/experiment-1')
  await expect(page.getByRole('heading', { name: 'Недостаточно оснований' })).toBeVisible()
  await expect(page.getByRole('cell', { name: '— 0 измерений', exact: true })).toHaveCount(8)
  await expect(page.getByRole('link', { name: 'JSON-отчёт' })).toHaveAttribute(
    'href',
    '/api/v1/experiments/experiment-1/report',
  )
})
