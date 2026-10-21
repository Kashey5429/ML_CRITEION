<script setup lang="ts">
import { ref, reactive } from 'vue'
import { Plus, Database, Layers3, ArrowRight, RefreshCw } from 'lucide-vue-next'
import { all, api, date, short, number } from '../api'
import type { Dataset, Version } from '../api'
import { usePolling } from '../usePolling'
import Status from '../components/Status.vue'
const datasets = ref<Dataset[]>([]),
  versions = ref<Version[]>([]),
  selected = ref(''),
  open = ref(false),
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
    if (selected.value === id) versions.value = data
  }
})
async function select(id: string) {
  selected.value = id
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
    await api(`/datasets/${selected.value}/versions`, {})
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
      <h1>Датасеты</h1>
      <p>Зафиксируйте данные, чтобы сравнение можно было повторить.</p>
    </div>
    <button class="button primary" @click="open = !open">
      <Plus :size="18" />Добавить источник
    </button>
  </div>
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
      Зарегистрируйте таблицу из экспериментальной PostgreSQL.<br />Затем создайте её версию —
      неизменяемый снимок для обучения.
    </p>
    <button class="button primary" @click="open = true">Добавить первый источник</button>
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
          ><small class="mono">{{ d.spec.source_schema }}.{{ d.spec.source_table }}</small
          ><span>{{ d.spec.features.length }} признаков · цель {{ d.spec.target }}</span>
        </div>
        <ArrowRight :size="16" />
      </button>
    </div>
    <section class="panel">
      <div class="panel-toolbar">
        <div>
          <h2>Версии данных</h2>
          <p class="muted small">Изменение источника не меняет готовую версию.</p>
        </div>
        <button class="button secondary" :disabled="busy" @click="snapshot">
          <Plus :size="16" />Создать версию
        </button>
      </div>
      <div v-if="!versions.length" class="empty">
        <Layers3 :size="30" />
        <h3>Зафиксируйте первую версию</h3>
        <p>Worker скопирует данные и проверит их перед обучением.</p>
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
          <p v-if="v.error_code" class="error-text">{{ v.error_code }}</p>
          <div v-if="v.manifest" class="version-bottom">
            <span class="mono muted small" :title="v.manifest.checksum"
              >SHA-256 {{ v.manifest.checksum.slice(0, 16) }}…</span
            ><RouterLink
              class="text-link"
              :to="{ path: '/experiments/new', query: { dataset: selected, version: v.id } }"
              >Создать эксперимент <ArrowRight :size="15"
            /></RouterLink>
          </div>
        </article>
      </div>
      <div class="panel-foot muted small">
        <RefreshCw :size="13" /> Статусы версий обновляются автоматически
      </div>
    </section>
  </div>
</template>
