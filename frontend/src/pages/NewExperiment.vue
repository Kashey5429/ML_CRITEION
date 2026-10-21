<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowRight, Check, Info, Layers3 } from 'lucide-vue-next'
import { all, api, short, number } from '../api'
import type { Dataset, Version, Experiment } from '../api'
const route = useRoute(),
  router = useRouter(),
  datasets = ref<Dataset[]>([]),
  versions = ref<Version[]>([]),
  error = ref(''),
  busy = ref(false),
  versionLoading = ref(false),
  preview = ref<{ cases: number; runs: number; measured_runs: number } | null>(null)
const form = reactive({
  dataset: String(route.query.dataset || ''),
  version: '',
  sizes: '',
  intercepts: 'yes',
  repeats: 5,
  warmups: 1,
  test: 20,
  seed: 42,
  threads: 1,
  timeout: 300,
  minPairs: 5,
  speedup: 5,
  maxRmse: '',
  maxTime: '',
  pythonMemory: '',
  dbMemory: '',
})
const nullable = (v: string) => (v.trim() === '' ? null : Number(v))
const spec = computed(() => ({
  kind: 'benchmark',
  dataset_version_id: form.version,
  backends: ['madlib', 'sklearn'],
  sample_sizes: form.sizes.trim() ? form.sizes.split(',').map((s) => Number(s.trim())) : [null],
  fit_intercepts: form.intercepts === 'both' ? [true, false] : [form.intercepts === 'yes'],
  repeats: form.repeats,
  warmups: form.warmups,
  test_fraction: form.test / 100,
  seed: form.seed,
  threads: form.threads,
  timeout_seconds: form.timeout,
  recommendation: {
    min_pairs: form.minPairs,
    practical_speedup: form.speedup / 100,
    max_rmse: nullable(form.maxRmse),
    max_model_seconds: nullable(form.maxTime),
    max_python_rss_bytes: form.pythonMemory
      ? Math.round(Number(form.pythonMemory) * 1024 ** 2)
      : null,
    max_bench_memory_bytes: form.dbMemory ? Math.round(Number(form.dbMemory) * 1024 ** 2) : null,
  },
}))
const count = computed(
  () =>
    spec.value.sample_sizes.length *
    spec.value.fit_intercepts.length *
    (Number(form.repeats) + Number(form.warmups)) *
    2,
)
let key = crypto.randomUUID()
watch(
  spec,
  () => {
    preview.value = null
    key = crypto.randomUUID()
  },
  { deep: true },
)
async function loadVersions(id: string) {
  form.version = ''
  versions.value = []
  versionLoading.value = true
  try {
    const data = await all<Version>(`/datasets/${id}/versions`)
    if (form.dataset !== id) return
    versions.value = data.filter((v) => v.status === 'ready')
    form.version =
      versions.value.find((v) => v.id === route.query.version)?.id || versions.value[0]?.id || ''
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    if (form.dataset === id) versionLoading.value = false
  }
}
watch(
  () => form.dataset,
  (id) => {
    if (id) void loadVersions(id)
  },
)
onMounted(async () => {
  try {
    datasets.value = await all<Dataset>('/datasets')
    if (form.dataset) await loadVersions(form.dataset)
    else form.dataset = datasets.value[0]?.id || ''
  } catch (e) {
    error.value = (e as Error).message
  }
})
async function validate() {
  busy.value = true
  error.value = ''
  const frozen = JSON.stringify(spec.value)
  try {
    const data = await api<{ cases: number; runs: number; measured_runs: number }>(
      '/experiments/validate',
      JSON.parse(frozen),
    )
    if (frozen === JSON.stringify(spec.value)) preview.value = data
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
async function create() {
  busy.value = true
  error.value = ''
  try {
    const e = await api<Experiment>('/experiments', spec.value, { 'Idempotency-Key': key })
    await router.push(`/experiments/${e.id}`)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <RouterLink to="/experiments" class="back-link"><ArrowLeft :size="16" />Эксперименты</RouterLink>
  <div class="page-heading">
    <div>
      <div class="eyebrow">НОВОЕ ИССЛЕДОВАНИЕ</div>
      <h1>Настроить эксперимент</h1>
      <p>Один набор условий для MADlib и scikit-learn.</p>
    </div>
  </div>
  <div v-if="error" class="alert error" role="alert">{{ error }}</div>
  <form class="builder-layout" @submit.prevent="validate">
    <div class="builder-main">
      <section class="panel form-panel">
        <div class="numbered-title">
          <span>01</span>
          <div>
            <h2>Данные</h2>
            <p>Выберите готовую версию датасета.</p>
          </div>
        </div>
        <div class="form-grid">
          <label
            >Источник<select v-model="form.dataset" required>
              <option disabled value="">Выберите датасет</option>
              <option v-for="d in datasets" :key="d.id" :value="d.id">{{ d.spec.name }}</option>
            </select></label
          ><label
            >Версия<select v-model="form.version" required :disabled="versionLoading">
              <option disabled value="">
                {{ versionLoading ? 'Загрузка…' : 'Нет готовых версий' }}
              </option>
              <option v-for="v in versions" :key="v.id" :value="v.id">
                {{ short(v.id) }} · {{ number(v.manifest?.row_count, 0) }} строк
              </option>
            </select></label
          >
        </div>
        <RouterLink class="text-link small" to="/datasets"
          >Управление источниками и версиями <ArrowRight :size="14"
        /></RouterLink>
      </section>
      <section class="panel form-panel">
        <div class="numbered-title">
          <span>02</span>
          <div>
            <h2>Модель и матрица</h2>
            <p>Линейная регрессия · плотные числовые признаки.</p>
          </div>
        </div>
        <div class="engine-choice">
          <div>
            <span class="engine madlib">MADlib</span><small>Обучение в PostgreSQL</small
            ><Check :size="16" />
          </div>
          <div>
            <span class="engine sklearn">scikit-learn</span><small>Обучение в Python</small
            ><Check :size="16" />
          </div>
        </div>
        <div class="form-grid">
          <label
            >Размеры выборки<input
              v-model="form.sizes"
              placeholder="Все строки или: 1000, 10000"
              pattern="\s*\d+\s*(,\s*\d+\s*)*"
            /><small>Пустое поле — все строки версии.</small></label
          ><label
            >Свободный член<select v-model="form.intercepts">
              <option value="yes">С intercept</option>
              <option value="no">Без intercept</option>
              <option value="both">Оба варианта</option>
            </select></label
          ><label
            >Измеряемых пар<input
              v-model.number="form.repeats"
              type="number"
              min="1"
              max="100"
              required /></label
          ><label
            >Прогревочных пар<input
              v-model.number="form.warmups"
              type="number"
              min="0"
              max="5"
              required /></label
          ><label
            >Тестовая доля, %<input
              v-model.number="form.test"
              type="number"
              min="1"
              max="99"
              required /></label
          ><label
            >Seed<input v-model.number="form.seed" type="number" min="0" max="4294967295" required
          /></label>
        </div>
      </section>
      <section class="panel form-panel">
        <div class="numbered-title">
          <span>03</span>
          <div>
            <h2>Ресурсы и критерии</h2>
            <p>Условия рекомендации фиксируются до запуска.</p>
          </div>
        </div>
        <div class="form-grid">
          <label
            >Потоки Python BLAS<input
              v-model.number="form.threads"
              type="number"
              min="1"
              max="16"
              required /></label
          ><label
            >Тайм-аут попытки, с<input
              v-model.number="form.timeout"
              type="number"
              min="1"
              max="3600"
              required /></label
          ><label
            >Минимум пар для вывода<input
              v-model.number="form.minPairs"
              type="number"
              min="3"
              max="100"
              required /></label
          ><label
            >Практически значимый выигрыш, %<input
              v-model.number="form.speedup"
              type="number"
              min="0.1"
              max="100"
              step="0.1"
              required
          /></label>
        </div>
        <details>
          <summary>Ограничения качества и ресурсов</summary>
          <p class="muted small">
            Пустое поле — без ограничения. Память проверяется по наблюдаемым пикам.
          </p>
          <div class="form-grid">
            <label
              >Максимальный RMSE<input
                v-model="form.maxRmse"
                type="number"
                min="0"
                step="any"
                placeholder="Не задан" /></label
            ><label
              >Максимальное время модели, с<input
                v-model="form.maxTime"
                type="number"
                min="0.001"
                step="any"
                placeholder="Не задан" /></label
            ><label
              >Память Python, MiB<input
                v-model="form.pythonMemory"
                type="number"
                min="1"
                placeholder="Не задана" /></label
            ><label
              >Память PostgreSQL, MiB<input
                v-model="form.dbMemory"
                type="number"
                min="1"
                placeholder="Не задана"
            /></label>
          </div>
        </details>
      </section>
    </div>
    <aside class="builder-summary">
      <section class="panel form-panel">
        <Layers3 :size="24" class="teal" />
        <h2>План запуска</h2>
        <div class="big-number">{{ count }}<span>запусков</span></div>
        <dl class="summary-list">
          <div>
            <dt>Подходов</dt>
            <dd>2</dd>
          </div>
          <div>
            <dt>Размеров выборки</dt>
            <dd>{{ spec.sample_sizes.length }}</dd>
          </div>
          <div>
            <dt>Вариантов intercept</dt>
            <dd>{{ spec.fit_intercepts.length }}</dd>
          </div>
          <div>
            <dt>Пар в каждом варианте</dt>
            <dd>{{ form.repeats }} + {{ form.warmups }} прогрев.</dd>
          </div>
        </dl>
        <div class="info-note">
          <Info :size="17" /><span
            >Запуски выполняются последовательно. Прогревы не входят в статистику.</span
          >
        </div>
        <p v-if="count > 200" class="error-text">Лимит — 200 запусков. Уменьшите матрицу.</p>
        <p v-if="form.repeats < form.minPairs" class="warning-text">
          Пар меньше заданного минимума: рекомендация будет неопределённой.
        </p>
        <button class="button secondary full" :disabled="busy || !form.version || count > 200">
          {{ busy ? 'Проверяем…' : 'Проверить конфигурацию' }}</button
        ><template v-if="preview"
          ><p class="validation-ok">
            <Check :size="16" />{{ preview.cases }} вариантов ·
            {{ preview.measured_runs }} измеряемых запусков
          </p>
          <button type="button" class="button primary full" :disabled="busy" @click="create">
            Создать эксперимент <ArrowRight :size="16" /></button
        ></template>
        <p class="small muted">
          После создания вы сможете проверить настройки и запустить обучение.
        </p>
      </section>
    </aside>
  </form>
</template>
