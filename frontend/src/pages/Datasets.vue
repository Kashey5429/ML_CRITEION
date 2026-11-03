<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import FileUpload from '../components/FileUpload.vue'
import type { FileImport } from '../api'
import { Plus, Database, Layers3, ArrowRight, RefreshCw } from 'lucide-vue-next'
import { all, api, date, short, number, humanError } from '../api'
import type { Dataset, Version } from '../api'
import { usePolling } from '../usePolling'
import Status from '../components/Status.vue'
const route = useRoute(),
  router = useRouter()
const imports = ref<FileImport[]>([])
const uploadOpen = ref(false)
const current = computed(() => datasets.value.find((d) => d.id === selected.value))
async function uploaded(item: FileImport) {
  await router.push({ path: '/experiments/new', query: { dataset: item.dataset_id } })
}
const datasets = ref<Dataset[]>([]),
  versions = ref<Version[]>([]),
  selected = ref(''),
  open = ref(!!route.query.connect),
  busy = ref(false),
  actionError = ref('')
const form = reactive({
  name: '',
  source_schema: 'public',
  source_table: '',
  id_column: 'id',
  features: '',
  target: '',
})
const { error, loading, refresh } = usePolling(async () => {
  datasets.value = await all<Dataset>('/datasets')
  if (!selected.value && datasets.value[0]) selected.value = datasets.value[0].id
  const id = selected.value
  if (id) {
    const data = await all<Version>(`/datasets/${id}/versions`)
    if (selected.value === id) {
      versions.value = data
      const items =
        current.value?.spec.kind === 'file'
          ? await api<FileImport[]>(`/datasets/${id}/imports`)
          : []
      if (selected.value === id) imports.value = items
    }
  }
})
async function select(id: string) {
  selected.value = id
  imports.value = []
  uploadOpen.value = false
  versions.value = []
  await refresh()
}
async function register() {
  busy.value = true
  actionError.value = ''
  try {
    const d = await api<Dataset>('/datasets', {
      ...form,
      features: form.features
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
    })
    selected.value = d.id
    versions.value = []
    open.value = false
    await refresh()
    await router.push({ path: '/experiments/new', query: { dataset: d.id } })
  } catch (e) {
    actionError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
async function snapshot() {
  busy.value = true
  actionError.value = ''
  try {
    await api(`/datasets/${selected.value}/prepare`, { refresh: true })
    await refresh()
  } catch (e) {
    actionError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">ИСТОЧНИКИ / 02</div>
      <h1>Мои данные</h1>
      <p>Загруженные файлы и подключённые таблицы для ваших сравнений.</p>
    </div>
    <button class="button primary" @click="open = !open">
      <Plus :size="18" />Подключить PostgreSQL
    </button>
  </div>
  <section class="panel wizard-panel"><FileUpload @uploaded="uploaded" /></section>
  <div v-if="error || actionError" role="alert" class="alert error">{{ actionError || error }}</div>
  <form v-if="open" class="panel form-panel" @submit.prevent="register">
    <div class="section-heading">
      <h2>Источник в PostgreSQL</h2>
      <button type="button" class="button quiet" @click="open = false">Закрыть</button>
    </div>
    <p class="muted">
      Таблица должна существовать в экспериментальной базе. Признаки и цель — числовые, без
      пропусков.
    </p>
    <div class="form-grid">
      <label
        >Название<input
          v-model="form.name"
          required
          maxlength="128"
          placeholder="Например, продажи магазинов" /></label
      ><label>Схема<input v-model="form.source_schema" required maxlength="63" /></label
      ><label
        >Таблица<input
          v-model="form.source_table"
          required
          maxlength="63"
          placeholder="criterion_demo" /></label
      ><label>Столбец ID<input v-model="form.id_column" required maxlength="63" /></label
      ><label
        >Признаки через запятую<input
          v-model="form.features"
          required
          placeholder="x1, x2" /></label
      ><label
        >Целевая переменная<input v-model="form.target" required maxlength="63" placeholder="y"
      /></label>
    </div>
    <button class="button primary" :disabled="busy">
      {{ busy ? 'Сохраняем…' : 'Зарегистрировать источник' }}
    </button>
  </form>
  <div v-if="loading" class="empty">Загружаем источники…</div>
  <div v-else-if="!datasets.length" class="panel empty">
    <Database :size="36" />
    <h3>Здесь будут ваши данные</h3>
    <p>
      Загрузите CSV-файл выше или подключите таблицу PostgreSQL. Программа автоматически сохранит
      данные для повторных сравнений.
    </p>
    <button class="button primary" @click="open = true">Подключить PostgreSQL</button>
  </div>
  <div v-else class="dataset-layout">
    <div class="dataset-list">
      <button
        v-for="d in datasets"
        :key="d.id"
        class="dataset-card"
        :class="{ selected: selected === d.id }"
        @click="select(d.id)"
      >
        <Database :size="20" />
        <div>
          <strong>{{ d.spec.name }}</strong
          ><small class="mono">{{
            d.spec.kind === 'file' ? 'CSV-файл' : `${d.spec.source_schema}.${d.spec.source_table}`
          }}</small
          ><span>{{
            d.spec.kind === 'file'
              ? 'Выбор столбцов при запуске'
              : `${d.spec.features.length} признаков · цель ${d.spec.target}`
          }}</span>
        </div>
        <ArrowRight :size="16" />
      </button>
    </div>
    <section class="panel wizard-panel">
      <div class="section-heading">
        <h2>{{ current?.spec.name }}</h2>
        <RouterLink
          class="button primary"
          :to="{ path: '/experiments/new', query: { dataset: selected } }"
          >Новое сравнение</RouterLink
        >
      </div>
      <template v-if="current?.spec.kind === 'file'">
        <p v-if="imports[0]">
          {{ imports[0].profile ? number(imports[0].profile.row_count, 0) + ' строк · ' : ''
          }}{{ date(imports[0].created_at) }} <Status :value="imports[0].status" />
        </p>
        <p v-if="imports[0]?.error_code" class="alert error">
          {{ humanError(imports[0].error_code!) }}
        </p>
        <button class="button secondary" @click="uploadOpen = !uploadOpen">
          Загрузить обновлённый файл
        </button>
        <FileUpload v-if="uploadOpen" :dataset-id="selected" @uploaded="uploaded" />
        <details>
          <summary>История обновлений</summary>
          <article v-for="item in imports" :key="item.id" class="version-row">
            <strong>{{ item.filename }}</strong>
            <p>{{ date(item.created_at) }} <Status :value="item.status" /></p>
            <p v-if="item.error_code" class="error-text">{{ humanError(item.error_code) }}</p>
          </article>
        </details>
      </template>
      <button v-else class="button secondary" :disabled="busy" @click="snapshot">
        Обновить данные из таблицы
      </button>
      <p class="muted small">Предыдущие результаты сохраняют связь с использованными данными.</p>
      <details>
        <summary>Сохранённые конфигурации данных</summary>
        <div class="panel-toolbar">
          <div>
            <h3>Подготовленные данные</h3>
            <p class="muted small">Изменение источника не меняет готовую версию.</p>
          </div>
        </div>
        <div v-if="!versions.length" class="empty">
          <Layers3 :size="30" />
          <h3>Данные будут подготовлены автоматически</h3>
          <p>Выберите «Новое сравнение», чтобы настроить цель и признаки.</p>
        </div>
        <div v-else class="versions">
          <article v-for="v in versions" :key="v.id" class="version-row">
            <div class="section-heading">
              <strong class="mono">{{ short(v.id) }}</strong
              ><Status :value="v.status" />
            </div>
            <p class="muted small">
              {{ date(v.created_at) }}
              <span v-if="v.manifest"
                >· {{ number(v.manifest.row_count, 0) }} строк ·
                {{ v.manifest.features.length }} признаков</span
              >
            </p>
            <p v-if="v.error_code" class="error-text">{{ humanError(v.error_code) }}</p>
            <div v-if="v.manifest" class="version-bottom">
              <span class="mono muted small" :title="v.manifest.checksum"
                >SHA-256 {{ v.manifest.checksum.slice(0, 16) }}…</span
              ><RouterLink
                class="text-link"
                :to="{ path: '/experiments/new', query: { dataset: selected, version: v.id } }"
                >Новое сравнение <ArrowRight :size="15"
              /></RouterLink>
            </div>
          </article>
        </div>
      </details>
      <div class="panel-foot muted small">
        <RefreshCw :size="13" /> Статус подготовки обновляется автоматически
      </div>
    </section>
  </div>
</template>
