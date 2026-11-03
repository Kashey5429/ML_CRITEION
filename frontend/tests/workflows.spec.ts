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
  await expect(page.getByRole('heading', { name: 'История сравнений', exact: true })).toBeVisible()
  await expect(page.getByText('#experim')).toBeVisible()
  await page.getByRole('textbox', { name: 'Поиск экспериментов' }).fill('нет такой записи')
  await expect(page.getByRole('heading', { name: 'Ничего не найдено' })).toBeVisible()
})
test('saved PostgreSQL data prepares automatically and starts with one action', async ({
  page,
}) => {
  let submitted: any
  await page.route('**/api/v1/datasets/dataset-1/prepare', (r) => r.fulfill({ json: version }))
  await page.route('**/api/v1/dataset-versions/version-1', (r) => r.fulfill({ json: version }))
  await page.route('**/api/v1/comparisons', (r) => {
    submitted = r.request().postDataJSON()
    expect(r.request().headers()['idempotency-key']).toBeTruthy()
    return r.fulfill({ json: { ...experiment, status: 'queued' } })
  })
  await page.goto('/experiments/new')
  await page.getByLabel('Или используйте сохранённые данные').selectOption(dataset.id)
  await page.getByRole('button', { name: 'Продолжить', exact: true }).click()
  await expect(page.getByText('Цель:', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Продолжить', exact: true }).click()
  await page.getByRole('button', { name: 'Запустить сравнение' }).click()
  await expect(page).toHaveURL(/\/experiments\/experiment-1$/)
  expect(submitted).toMatchObject({ dataset_version_id: version.id, repeats: 5, warmups: 1 })
})

const fileImport = {
  id: 'import-1',
  dataset_id: dataset.id,
  filename: 'Мои данные.csv',
  status: 'ready',
  created_at: dataset.created_at,
  error_code: null,
  profile: {
    row_count: 12,
    encoding: 'utf-8-sig',
    delimiter: ',',
    preview: [['1', '2', 'дом']],
    columns: [
      { key: 'c0', name: 'Площадь', usable: true, missing: 0, invalid: 0, examples: [] },
      { key: 'c1', name: 'Цена', usable: true, missing: 0, invalid: 0, examples: [] },
      {
        key: 'c2',
        name: 'Описание',
        usable: false,
        missing: 0,
        invalid: 12,
        examples: ['Строка 2: не является конечным числом'],
      },
    ],
  },
}

test('CSV upload, column validation, refresh recovery and launch retry', async ({ page }) => {
  await page.route('**/api/v1/imports?*', (r) => r.fulfill({ status: 202, json: fileImport }))
  await page.route('**/api/v1/imports/import-1', (r) => r.fulfill({ json: fileImport }))
  await page.route('**/api/v1/datasets/dataset-1/prepare', (r) => {
    expect(r.request().postDataJSON()).toEqual({
      import_id: 'import-1',
      features: ['c0'],
      target: 'c1',
    })
    return r.fulfill({ json: version })
  })
  await page.route('**/api/v1/dataset-versions/version-1', (r) => r.fulfill({ json: version }))
  const keys: string[] = []
  await page.route('**/api/v1/comparisons', (r) => {
    keys.push(r.request().headers()['idempotency-key']!)
    return keys.length === 1
      ? r.fulfill({ status: 503, json: { error: { code: 'Попробуйте ещё раз' } } })
      : r.fulfill({ json: experiment })
  })
  await page.goto('/')
  await page.getByLabel('CSV-файл').setInputFiles({
    name: 'Мои данные.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('Площадь,Цена\n1,2\n2,4\n3,6\n4,8'),
  })
  await page.getByRole('button', { name: 'Загрузить и проверить' }).click()
  await expect(page.getByRole('heading', { name: 'Мои данные.csv' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Продолжить', exact: true })).toBeDisabled()
  await page.getByLabel('Что предсказываем?').selectOption('c1')
  await page.getByRole('checkbox', { name: /Площадь/ }).check()
  await expect(page.getByRole('checkbox', { name: /Описание/ })).toBeDisabled()
  await page.reload()
  await expect(page.getByLabel('Что предсказываем?')).toHaveValue('c1')
  await expect(page.getByRole('checkbox', { name: /Площадь/ })).toBeChecked()
  await page.getByRole('button', { name: 'Продолжить', exact: true }).click()
  await page.getByRole('button', { name: 'Запустить сравнение' }).click()
  await expect(page.getByRole('alert')).toContainText('Попробуйте ещё раз')
  await page.reload()
  await page.getByRole('button', { name: 'Запустить сравнение' }).click()
  await expect(page).toHaveURL(/\/experiments\/experiment-1$/)
  expect(keys).toHaveLength(2)
  expect(keys[0]).toBe(keys[1])
})

test('drag and drop accepts large file metadata and rejects unsupported formats', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByLabel('CSV-файл').setInputFiles({
    name: 'book.xlsx',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('x'),
  })
  await expect(page.getByRole('alert')).toContainText('CSV')
  const data = await page.evaluateHandle(() => {
    const transfer = new DataTransfer()
    const file = new File(['x,y\n1,2'], 'drop.csv', { type: 'text/csv' })
    // Exercise client validation without allocating or uploading a 100 GiB fixture.
    Object.defineProperty(file, 'size', { value: 100 * 1024 ** 3 })
    transfer.items.add(file)
    return transfer
  })
  await page.locator('.upload-zone').dispatchEvent('drop', { dataTransfer: data })
  await expect(page.getByRole('heading', { name: 'drop.csv' })).toBeVisible()
  await expect(page.getByText('100 ГБ · готов к загрузке')).toBeVisible()
})

test('retry stored CSV without uploading the file again', async ({ page }) => {
  let uploads = 0
  await page.route('**/api/v1/imports?*', (r) => {
    uploads++
    return r.fulfill({ status: 202, json: fileImport })
  })
  let retried = false
  await page.route('**/api/v1/imports/import-1/retry', (r) => {
    retried = true
    return r.fulfill({ status: 202, json: { ...fileImport, id: 'import-2' } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Попробовать пример' }).click()
  await expect(page.getByLabel('Что предсказываем?')).toBeVisible()
  await page.getByText('Заменить файл или исправить распознавание', { exact: true }).click()
  await page.getByRole('button', { name: 'Повторить проверку без загрузки' }).click()
  await expect.poll(() => retried).toBe(true)
  await expect(page.getByLabel('Что предсказываем?')).toBeVisible()
  expect(uploads).toBe(1)
})

test('backend error is visible and retry works', async ({ page }) => {
  await page.route('**/api/v1/experiments?*', (r) =>
    r.fulfill({ status: 503, json: { error: { code: 'metadata_unavailable' } } }),
  )
  await page.goto('/experiments')
  await expect(page.getByRole('alert')).toContainText('База данных временно недоступна')
  await page.unroute('**/api/v1/experiments?*')
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
})
test('mobile navigation, no page overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/experiments')
  await page.getByRole('button', { name: 'Открыть меню' }).click()
  await page.getByRole('navigation').getByRole('link', { name: 'Мои данные' }).click()
  await expect(page.getByRole('heading', { name: 'Мои данные', exact: true })).toBeVisible()
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
