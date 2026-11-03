import { test, expect } from '@playwright/test'

test('real CSV to MADlib and sklearn results', async ({ page }, testInfo) => {
  test.skip(!process.env.LIVE_APP_URL, 'Set LIVE_APP_URL to test the running Docker application')
  test.setTimeout(120000)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto(process.env.LIVE_APP_URL!)
  await expect(page.getByRole('heading', { name: 'Новое сравнение' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('wizard.png'), fullPage: true })
  await page.getByRole('button', { name: 'Попробовать пример' }).click()
  await expect(page.getByLabel('Что предсказываем?')).toBeVisible({ timeout: 30000 })
  await page.getByLabel('Что предсказываем?').selectOption({ label: 'Цена' })
  await page.getByRole('checkbox', { name: /Площадь/ }).check()
  await page.getByRole('checkbox', { name: /Комнаты/ }).check()
  await page.screenshot({ path: testInfo.outputPath('columns.png'), fullPage: true })
  await page.getByRole('button', { name: 'Продолжить', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Запустить сравнение' })).toBeEnabled({
    timeout: 30000,
  })
  await page.getByRole('button', { name: 'Запустить сравнение' }).click()
  await expect(page).toHaveURL(/\/experiments\/[0-9a-f-]+$/)
  await expect(page.getByRole('link', { name: 'JSON-отчёт' })).toBeVisible({ timeout: 90000 })
  await expect(page.getByText('12 / 12')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('results.png'), fullPage: true })
  await page.getByRole('link', { name: 'Повторить / изменить настройки' }).click()
  await expect(page.getByRole('button', { name: 'Запустить сравнение' })).toBeEnabled()
  expect(errors).toEqual([])
})
