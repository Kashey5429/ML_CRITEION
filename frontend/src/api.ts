export interface Dataset {
  id: string
  spec: {
    name: string
    source_schema: string
    source_table: string
    id_column: string
    features: string[]
    target: string
  }
  created_at: string
}
export interface Version {
  id: string
  dataset_id: string
  status: string
  manifest: null | { row_count: number; checksum: string; features: string[] }
  error_code: string | null
  created_at: string
}
export interface Spec {
  kind: string
  dataset_version_id?: string
  repeats?: number
  warmups?: number
  sample_sizes?: (number | null)[]
  backends?: string[]
  [key: string]: unknown
}
export interface Experiment {
  id: string
  status: string
  created_at: string
  spec: Spec
}
export interface Metric {
  median: number | null
  available_pairs: number
  unavailable_pairs: number
}
export interface Case {
  case_id: string
  verdict: string
  reasons: string[]
  expected_pairs: number
  config: { sample_size: number; fit_intercept: boolean }
  excluded_pairs: { pair_id: string; reason: string }[]
  statistics: null | {
    pairs: number
    median_ratio: number
    ci95: [number, number]
    median_madlib_ns: number
    median_sklearn_ns: number
    ratios_madlib_over_sklearn: number[]
  }
  resources: Record<string, Record<string, Record<string, Metric>>>
  constraints: Record<string, { status: string; violations: string[]; unknown: string[] }>
}
export interface Results {
  status: string
  total_runs: number
  completed_runs: number
  summary: {
    case_id: string
    backend: string
    count: number
    median_model_wall_ns: number
    median_rmse: number
  }[]
  analysis: null | { cases: Case[]; policy: Record<string, unknown> }
}
export interface Run {
  id: string
  backend: string
  status: string
  warmup: boolean
  repeat_index: number
  case_id: string
  config: { sample_size: number; fit_intercept: boolean }
  result: null | {
    timings: { model_wall_ns: number }
    quality: { rmse: number }
    resources?: {
      scopes: Record<
        string,
        { status: string; cpu_seconds: number | null; peak_memory_bytes: number | null }
      >
    }
  }
}
export interface Attempt {
  id: string
  status: string
  error_code: string | null
  result: null | { artifact?: unknown }
}
export async function api<T>(
  path: string,
  body?: unknown,
  headers: Record<string, string> = {},
): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15000)
  try {
    const response = await fetch(`/api/v1${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      const detail = Array.isArray(data?.detail)
        ? data.detail
            .map((d: { loc: string[]; msg: string }) => `${d.loc.slice(1).join('.')}: ${d.msg}`)
            .join('; ')
        : ''
      throw new Error(data?.error?.code || detail || `Ошибка сервера (${response.status})`)
    }
    return (await response.json()) as T
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError')
      throw new Error('Сервер не ответил вовремя. Повторите запрос.')
    throw e
  } finally {
    clearTimeout(timeout)
  }
}
export async function all<T>(path: string): Promise<T[]> {
  const rows: T[] = []
  for (let offset = 0; ; offset += 100) {
    const page = await api<T[]>(`${path}?limit=100&offset=${offset}`)
    rows.push(...page)
    if (page.length < 100) return rows
  }
}
export const active = (s: string) => ['queued', 'preparing', 'running', 'cancelling'].includes(s)
export const short = (id: string) => id.slice(0, 8)
export const number = (v: number | null | undefined, digits = 2) =>
  v == null ? '—' : new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(v)
export const seconds = (ns: number | null | undefined) =>
  ns == null ? '—' : `${number(ns / 1e9, 3)} с`
export const date = (v: string) =>
  new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(v))
export const labels: Record<string, string> = {
  draft: 'Черновик',
  queued: 'В очереди',
  preparing: 'Подготовка',
  running: 'Выполняется',
  cancelling: 'Отмена…',
  succeeded: 'Завершён',
  failed: 'Ошибка',
  partial: 'Частично',
  cancelled: 'Отменён',
  interrupted: 'Прерван',
  ready: 'Готова',
  pending: 'Ожидает',
  madlib: 'MADlib',
  sklearn: 'scikit-learn',
  comparable: 'Сопоставимы',
  inconclusive: 'Недостаточно оснований',
  no_feasible_backend: 'Нет подходящего варианта',
}
export const reasons: Record<string, string> = {
  paired_speedup_above_threshold:
    'Парный интервал подтверждает практически значимый выигрыш во времени.',
  only_backend_meeting_constraints: 'Только этот подход удовлетворяет заданным ограничениям.',
  interval_within_practical_equivalence_band:
    'Весь доверительный интервал находится внутри границ практической эквивалентности.',
  insufficient_pairs: 'Недостаточно измеряемых пар для уверенного вывода.',
  incomplete_pairs: 'Есть неполные или неуспешные пары.',
  required_resources_unavailable:
    'Не удалось измерить ресурсы, необходимые для проверки ограничений.',
  uncertainty_overlaps_decision_threshold:
    'Доверительный интервал пересекает границу принятия решения.',
  constraints_violated: 'Оба подхода нарушают ограничения.',
  experiment_cancelled: 'Эксперимент отменён.',
  experiment_interrupted: 'Эксперимент прерван.',
}
