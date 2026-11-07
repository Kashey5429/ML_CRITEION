<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight } from 'lucide-vue-next'
import { all, api, date, number, humanError } from '../api'
import type { Dataset, Experiment, FileImport, Version } from '../api'
import { usePolling } from '../usePolling'
import FileUpload from '../components/FileUpload.vue'
import AdvancedSettings from '../components/AdvancedSettings.vue'
import Status from '../components/Status.vue'
const route = useRoute(),
  router = useRouter()
const step = ref(1),
  datasets = ref<Dataset[]>([]),
  recent = ref<Experiment[]>([])
const datasetId = ref(''),
  imported = ref<FileImport | null>(null),
  version = ref<Version | null>(null)
const target = ref(''),
  features = ref<string[]>([]),
  error = ref(''),
  busy = ref(false),
  initialized = ref(false)
const launchKey = ref(crypto.randomUUID()),
  launchBody = ref<string | null>(null)
const form = ref({
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
const selected = computed(() => datasets.value.find((d) => d.id === datasetId.value))
const columns = computed(() => imported.value?.profile?.columns || [])
const validSelection = computed(
  () => !!target.value && features.value.length > 0 && !features.value.includes(target.value),
)
const selectableFeatures = computed(() =>
  columns.value.filter((c) => c.usable && c.key !== target.value),
)
const allFeaturesSelected = computed(
  () =>
    selectableFeatures.value.length > 0 &&
    selectableFeatures.value.every((c) => features.value.includes(c.key)),
)
function toggleAllFeatures() {
  features.value = allFeaturesSelected.value ? [] : selectableFeatures.value.map((c) => c.key)
}
const preparing = computed(
  () => !!version.value && ['queued', 'running'].includes(version.value.status),
)
const nullable = (v: string) => (v.trim() ? Number(v) : null)
const spec = computed(() => ({
  kind: 'benchmark',
  dataset_version_id: version.value?.id,
  backends: ['madlib', 'sklearn'],
  sample_sizes: form.value.sizes.trim()
    ? form.value.sizes.split(',').map((s) => Number(s.trim()))
    : [null],
  fit_intercepts:
    form.value.intercepts === 'both' ? [true, false] : [form.value.intercepts === 'yes'],
  repeats: form.value.repeats,
  warmups: form.value.warmups,
  test_fraction: form.value.test / 100,
  seed: form.value.seed,
  threads: form.value.threads,
  timeout_seconds: form.value.timeout,
  recommendation: {
    min_pairs: form.value.minPairs,
    practical_speedup: form.value.speedup / 100,
    max_rmse: nullable(form.value.maxRmse),
    max_model_seconds: nullable(form.value.maxTime),
    max_python_rss_bytes: form.value.pythonMemory
      ? Math.round(Number(form.value.pythonMemory) * 1024 ** 2)
      : null,
    max_bench_memory_bytes: form.value.dbMemory
      ? Math.round(Number(form.value.dbMemory) * 1024 ** 2)
      : null,
  },
}))
const count = computed(
  () =>
    spec.value.sample_sizes.length *
    spec.value.fit_intercepts.length *
    (Number(form.value.repeats) + Number(form.value.warmups)) *
    2,
)
function remember() {
  if (!initialized.value) return
  sessionStorage.setItem(
    'comparison-draft',
    JSON.stringify({
      path: route.fullPath,
      step: step.value,
      datasetId: datasetId.value,
      importId: imported.value?.id,
      versionId: version.value?.id,
      target: target.value,
      features: features.value,
      form: form.value,
      launchKey: launchKey.value,
      launchBody: launchBody.value,
    }),
  )
}
watch(
  [step, datasetId, imported, version, target, features, form, launchKey, launchBody],
  remember,
  { deep: true },
)
watch(target, (value) => {
  features.value = features.value.filter((c) => c !== value)
})
async function uploaded(item: FileImport) {
  imported.value = item
  datasetId.value = item.dataset_id
  version.value = null
  target.value = ''
  features.value = []
  step.value = 2
  error.value = ''
  try {
    datasets.value = await all<Dataset>('/datasets')
  } catch (e) {
    error.value = (e as Error).message
  }
}
async function chooseDataset() {
  version.value = null
  imported.value = null
  target.value = ''
  features.value = []
  error.value = ''
  try {
    if (selected.value?.spec.kind === 'file') {
      const items = await api<FileImport[]>(`/datasets/${datasetId.value}/imports`)
      imported.value = items[0] || null
      if (!imported.value) throw new Error('Для этого источника ещё нет загрузок.')
    }
    step.value = 2
  } catch (e) {
    error.value = (e as Error).message
  }
}
const { error: pollError } = usePolling(async () => {
  if (imported.value && ['queued', 'running'].includes(imported.value.status)) {
    const id = imported.value.id
    const value = await api<FileImport>(`/imports/${id}`)
    if (imported.value?.id === id) imported.value = value
  }
  if (preparing.value) {
    const id = version.value!.id
    const value = await api<Version>(`/dataset-versions/${id}`)
    if (version.value?.id === id) version.value = value
  }
})
async function retryImport() {
  if (!imported.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const item = await api<FileImport>(`/imports/${imported.value.id}/retry`, {})
    await uploaded(item)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
async function prepare() {
  busy.value = true
  error.value = ''
  try {
    const result = await api<{ id: string }>(
      `/datasets/${datasetId.value}/prepare`,
      imported.value
        ? { import_id: imported.value.id, features: features.value, target: target.value }
        : {},
    )
    version.value = await api<Version>(`/dataset-versions/${result.id}`)
    step.value = 3
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
async function launch() {
  if (busy.value || version.value?.status !== 'ready') return
  busy.value = true
  error.value = ''
  const body = JSON.stringify(spec.value)
  if (launchBody.value !== body) {
    launchKey.value = crypto.randomUUID()
    launchBody.value = body
  }
  remember()
  try {
    const result = await api<Experiment>('/comparisons', JSON.parse(body), {
      'Idempotency-Key': launchKey.value,
    })
    initialized.value = false
    sessionStorage.removeItem('comparison-draft')
    await router.push(`/experiments/${result.id}`)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
function reset() {
  step.value = 1
  imported.value = null
  version.value = null
  datasetId.value = ''
  target.value = ''
  features.value = []
  error.value = ''
}
onMounted(async () => {
  try {
    datasets.value = await all<Dataset>('/datasets')
    recent.value = await api<Experiment[]>('/experiments?limit=3')
    const saved = JSON.parse(sessionStorage.getItem('comparison-draft') || 'null')
    if (saved?.path === route.fullPath) {
      datasetId.value = saved.datasetId
      target.value = saved.target
      features.value = saved.features
      form.value = { ...form.value, ...saved.form }
      launchKey.value = saved.launchKey
      launchBody.value = saved.launchBody
      if (saved.importId) imported.value = await api<FileImport>(`/imports/${saved.importId}`)
      if (saved.versionId)
        version.value = await api<Version>(`/dataset-versions/${saved.versionId}`)
      step.value = saved.step
    } else if (route.query.repeat) {
      const previous = await api<Experiment>(`/experiments/${route.query.repeat}`)
      version.value = await api<Version>(`/dataset-versions/${previous.spec.dataset_version_id}`)
      datasetId.value = version.value.dataset_id
      step.value = 3
      const s = previous.spec as any,
        policy = s.recommendation || {}
      Object.assign(form.value, {
        sizes: s.sample_sizes?.filter((n: number | null) => n != null).join(', ') || '',
        intercepts:
          s.fit_intercepts?.length === 2 ? 'both' : s.fit_intercepts?.[0] === false ? 'no' : 'yes',
        repeats: s.repeats ?? 5,
        warmups: s.warmups ?? 1,
        test: (s.test_fraction ?? 0.2) * 100,
        seed: s.seed ?? 42,
        threads: s.threads ?? 1,
        timeout: s.timeout_seconds ?? 300,
        minPairs: policy.min_pairs ?? 5,
        speedup: (policy.practical_speedup ?? 0.05) * 100,
        maxRmse: String(policy.max_rmse ?? ''),
        maxTime: String(policy.max_model_seconds ?? ''),
        pythonMemory:
          policy.max_python_rss_bytes == null
            ? ''
            : String(policy.max_python_rss_bytes / 1024 ** 2),
        dbMemory:
          policy.max_bench_memory_bytes == null
            ? ''
            : String(policy.max_bench_memory_bytes / 1024 ** 2),
      })
      if (version.value.selection) {
        imported.value = await api<FileImport>(`/imports/${version.value.selection.import_id}`)
        target.value = version.value.selection.target
        features.value = version.value.selection.features
      }
    } else if (route.query.version) {
      version.value = await api<Version>(`/dataset-versions/${route.query.version}`)
      datasetId.value = version.value.dataset_id
      step.value = 3
      if (version.value.selection) {
        imported.value = await api<FileImport>(`/imports/${version.value.selection.import_id}`)
        target.value = version.value.selection.target
        features.value = version.value.selection.features
      }
    } else if (route.query.dataset) {
      datasetId.value = String(route.query.dataset)
      await chooseDataset()
    }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    initialized.value = true
  }
})
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">MADlib + SCIKIT-LEARN</div>
      <h1>Новое сравнение</h1>
      <p>Загрузите данные и узнайте, где модель обучается быстрее.</p>
    </div>
    <button v-if="step > 1" class="button quiet" :disabled="busy" @click="reset">
      Начать заново
    </button>
  </div>
  <ol class="wizard-steps" aria-label="Этапы сравнения">
    <li
      v-for="(label, i) in ['Данные', 'Столбцы', 'Сравнение']"
      :key="label"
      :class="{ current: step === i + 1, complete: step > i + 1 }"
      :aria-current="step === i + 1 ? 'step' : undefined"
    >
      <span>{{ i + 1 }}</span
      >{{ label }}
    </li>
  </ol>
  <div v-if="error || pollError" class="alert error" role="alert">{{ error || pollError }}</div>
  <section v-if="step === 1" class="panel wizard-panel">
    <FileUpload @uploaded="uploaded" />
    <div v-if="datasets.length" class="saved-source">
      <label
        >Или используйте сохранённые данные<select v-model="datasetId">
          <option value="">Выберите источник</option>
          <option v-for="d in datasets" :key="d.id" :value="d.id">{{ d.spec.name }}</option>
        </select></label
      ><button class="button secondary" :disabled="!datasetId" @click="chooseDataset">
        Продолжить <ArrowRight :size="16" />
      </button>
    </div>
    <RouterLink class="text-link" to="/datasets?connect=1"
      >Подключить таблицу PostgreSQL</RouterLink
    >
  </section>
  <section v-if="step === 2" class="panel wizard-panel">
    <h2>{{ imported?.filename || selected?.spec.name }}</h2>
    <template v-if="imported">
      <div v-if="['queued', 'running'].includes(imported.status)" class="empty" role="status">
        <Status :value="imported.status" />
        <h3>Проверяем файл целиком</h3>
        <p>Можно обновить страницу: загрузка сохранена.</p>
      </div>
      <div v-else-if="imported.status !== 'ready'" class="alert error" role="alert">
        {{
          humanError(imported.error_code || 'Не удалось обработать файл. Загрузите его повторно.')
        }}
      </div>
      <template v-else-if="imported.profile">
        <p class="muted">
          {{ number(imported.profile.row_count, 0) }} строк · {{ columns.length }} столбцов ·
          {{ imported.profile.encoding }}
        </p>
        <div class="table-wrap preview-table">
          <table>
            <caption>
              Первые 10 строк файла
            </caption>
            <thead>
              <tr>
                <th v-for="c in columns" :key="c.key">{{ c.name }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in imported.profile.preview" :key="i">
                <td v-for="(cell, j) in row" :key="j">{{ cell || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <label class="target-picker"
          >Что предсказываем?<select v-model="target">
            <option value="">Выберите целевой столбец</option>
            <option v-for="c in columns" :key="c.key" :value="c.key" :disabled="!c.usable">
              {{ c.name }}{{ c.usable ? '' : ' — есть пропуски или текст' }}
            </option>
          </select></label
        >
        <fieldset class="feature-picker">
          <div class="feature-picker-heading">
            <legend>На основе каких данных?</legend>
            <button
              type="button"
              class="button quiet"
              :disabled="!selectableFeatures.length"
              @click="toggleAllFeatures"
            >
              {{ allFeaturesSelected ? 'Снять выделение' : 'Выбрать все' }}
            </button>
          </div>
          <p class="muted">Отметьте признаки. Цель и столбцы с ошибками исключены.</p>
          <label v-for="c in columns" :key="c.key" class="column-choice"
            ><input
              v-model="features"
              type="checkbox"
              :value="c.key"
              :disabled="!c.usable || c.key === target"
            /><span
              ><strong>{{ c.name }}</strong
              ><small>{{
                c.usable
                  ? 'Числовой столбец'
                  : `Пропуски: ${c.missing}, нечисловые значения: ${c.invalid}`
              }}</small
              ><small v-for="example in c.examples" :key="example" class="error-text">{{
                example
              }}</small></span
            ></label
          >
        </fieldset>
      </template>
      <details class="import-options">
        <summary>Заменить файл или исправить распознавание</summary>
        <p>Дробные числа могут быть записаны с точкой или запятой.</p>
        <button
          class="button secondary"
          :disabled="busy || ['queued', 'running'].includes(imported.status)"
          @click="retryImport"
        >
          Повторить проверку без загрузки
        </button>
        <p class="muted small">
          Используем сохранённый исходный файл. Предыдущие результаты не изменятся.
        </p>
        <FileUpload :dataset-id="datasetId" @uploaded="uploaded" />
      </details>
    </template>
    <div v-else>
      <p>
        Цель: <strong>{{ selected?.spec.target }}</strong>
      </p>
      <p>Признаки: {{ selected?.spec.features?.join(', ') }}</p>
      <p class="muted">Программа автоматически сохранит данные для повторных сравнений.</p>
    </div>
    <div class="wizard-actions">
      <button class="button secondary" :disabled="busy" @click="step = 1">Назад</button
      ><button
        class="button primary"
        :disabled="busy || (!!imported && (imported.status !== 'ready' || !validSelection))"
        @click="prepare"
      >
        {{ busy ? 'Подготавливаем…' : 'Продолжить' }} <ArrowRight :size="16" />
      </button>
    </div>
  </section>
  <form v-if="step === 3" class="panel wizard-panel" @submit.prevent="launch">
    <h2>Настройки сравнения</h2>
    <p>{{ version?.manifest?.source_name || imported?.filename || selected?.spec.name }}</p>
    <div v-if="preparing" class="info-note" role="status">
      Подготавливаем сохранённую копию данных. Настройки можно проверить уже сейчас.
    </div>
    <div v-else-if="version?.status !== 'ready'" class="alert error" role="alert">
      {{ humanError(version?.error_code || 'Данные ещё не готовы.') }}
      <button type="button" @click="prepare">Повторить подготовку</button>
    </div>
    <div class="comparison-summary">
      <div>
        <strong>{{ number(version?.manifest?.row_count, 0) }}</strong
        ><span>строк данных</span>
      </div>
      <div><strong>MADlib + Python</strong><span>одинаковая выборка для двух подходов</span></div>
      <div>
        <strong>{{ count }}</strong
        ><span>запусков, включая прогрев</span>
      </div>
    </div>
    <p v-if="version?.manifest" class="muted">
      Цель:
      {{
        version.manifest.display_columns?.[version.manifest.target || ''] ||
        version.manifest.target
      }}. Признаки:
      {{
        version.manifest.features
          .map((c) => version?.manifest?.display_columns?.[c] || c)
          .join(', ')
      }}.
    </p>
    <p class="info-note">
      {{ form.repeats }} повторов · {{ form.test }}% данных для проверки · линейная регрессия
    </p>
    <details class="advanced-settings">
      <summary>Расширенные настройки</summary>
      <AdvancedSettings v-model="form" />
    </details>
    <p v-if="count > 200" class="error-text">
      Максимум 200 запусков. Уменьшите число повторов или вариантов.
    </p>
    <p v-if="form.repeats < form.minPairs" class="warning-text">
      Повторов меньше минимума для уверенного вывода.
    </p>
    <div class="wizard-actions">
      <button type="button" class="button secondary" :disabled="busy" @click="step = 2">
        Назад</button
      ><button
        class="button primary"
        :disabled="busy || version?.status !== 'ready' || count > 200"
      >
        {{ busy ? 'Запускаем…' : 'Запустить сравнение' }} <ArrowRight :size="16" />
      </button>
    </div>
  </form>
  <section v-if="step === 1 && recent.length" class="recent-comparisons">
    <div class="section-heading">
      <h2>Последние сравнения</h2>
      <RouterLink to="/experiments" class="text-link">Вся история</RouterLink>
    </div>
    <RouterLink v-for="e in recent" :key="e.id" :to="`/experiments/${e.id}`" class="recent-row"
      ><span>{{ e.data_name || 'Линейная регрессия' }} · {{ date(e.created_at) }}</span
      ><Status :value="e.status" /><ArrowRight :size="16"
    /></RouterLink>
  </section>
</template>
