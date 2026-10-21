<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  Plus,
  Search,
  ArrowUpRight,
  FlaskConical,
  CheckCheck,
  Clock3,
  Layers3,
  RefreshCw,
} from 'lucide-vue-next'
import { api, active, date, short, labels } from '../api'
import type { Experiment } from '../api'
import { usePolling } from '../usePolling'
import Status from '../components/Status.vue'
const rows = ref<Experiment[]>([]),
  page = ref(0),
  search = ref(''),
  tab = ref('all')
const { error, loading, refresh } = usePolling(async () => {
  rows.value = await api<Experiment[]>(`/experiments?limit=30&offset=${page.value * 30}`)
})
const shown = computed(() =>
  rows.value.filter(
    (e) =>
      (tab.value === 'all' ||
        (tab.value === 'active' ? active(e.status) : e.status === 'succeeded')) &&
      `${e.id} ${labels[e.status]} ${e.spec.kind}`
        .toLowerCase()
        .includes(search.value.toLowerCase()),
  ),
)
const running = computed(() => rows.value.filter((e) => active(e.status)).length)
async function turn(delta: number) {
  page.value += delta
  await refresh()
}
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">ИССЛЕДОВАНИЯ / 01</div>
      <h1>Эксперименты</h1>
      <p>От гипотезы до измеримого результата.</p>
    </div>
    <RouterLink class="button primary" to="/experiments/new"
      ><Plus :size="18" />Новый эксперимент</RouterLink
    >
  </div>
  <section class="intro-banner">
    <div>
      <span class="tag">ПОСТРОЕН ДЛЯ СРАВНЕНИЙ</span>
      <h2>Где вашей модели<br />работается быстрее?</h2>
      <p>Одинаковые данные. Парные запуски.<br />Время, ресурсы и качество — в одном отчёте.</p>
    </div>
    <div class="comparison-art" aria-hidden="true">
      <div class="art-grid"></div>
      <div class="art-node db">
        <DatabaseIcon /><span>PostgreSQL<small>MADlib</small></span>
      </div>
      <div class="art-link"><span>vs</span></div>
      <div class="art-node py">
        <span class="py-symbol">py</span><span>Python<small>scikit-learn</small></span>
      </div>
      <span class="art-caption">ОДНА ВЫБОРКА · ДВА ПОДХОДА</span>
    </div>
  </section>
  <div class="stats-grid">
    <div class="stat">
      <span>На этой странице <Layers3 :size="17" /></span><strong>{{ rows.length }}</strong
      ><small>сохранённых экспериментов</small>
    </div>
    <div class="stat">
      <span>В работе <Clock3 :size="17" /></span><strong>{{ running }}</strong
      ><small>в очереди или выполняются</small>
    </div>
    <div class="stat">
      <span>Завершено <CheckCheck :size="17" /></span
      ><strong>{{ rows.filter((e) => e.status === 'succeeded').length }}</strong
      ><small>успешных серий</small>
    </div>
  </div>
  <div v-if="error" class="alert error" role="alert">
    {{ error }} <button @click="refresh">Повторить</button>
  </div>
  <section class="panel">
    <div class="panel-toolbar">
      <div class="tabs">
        <button
          v-for="t in [
            ['all', 'Все'],
            ['active', 'Активные'],
            ['done', 'Завершённые'],
          ]"
          :key="t[0]"
          :class="{ chosen: tab === t[0] }"
          @click="tab = t[0]!"
        >
          {{ t[1] }}
        </button>
      </div>
      <div class="toolbar-right">
        <label class="search"
          ><Search :size="16" /><input
            v-model="search"
            placeholder="Найти по ID или статусу"
            aria-label="Поиск экспериментов" /></label
        ><button class="icon-button" aria-label="Обновить эксперименты" @click="refresh">
          <RefreshCw :size="17" />
        </button>
      </div>
    </div>
    <div v-if="loading" class="empty">Загружаем историю…</div>
    <div v-else-if="!shown.length" class="empty">
      <FlaskConical :size="34" />
      <h3>{{ rows.length ? 'Ничего не найдено' : 'Начните с первого эксперимента' }}</h3>
      <p>
        {{
          rows.length
            ? 'Измените поиск или фильтр.'
            : 'Добавьте датасет и сравните два подхода на одной выборке.'
        }}
      </p>
      <RouterLink v-if="!rows.length" to="/datasets" class="button secondary"
        >Перейти к датасетам <ArrowUpRight :size="16"
      /></RouterLink>
    </div>
    <div v-else class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Эксперимент</th>
            <th>Подходы</th>
            <th>Статус</th>
            <th>Создан</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in shown" :key="e.id">
            <td>
              <RouterLink class="record-link" :to="`/experiments/${e.id}`"
                ><span class="record-icon"><FlaskConical :size="19" /></span
                ><span
                  >{{ e.spec.kind === 'benchmark' ? 'Линейная регрессия' : 'Диагностика'
                  }}<small class="mono">#{{ short(e.id) }}</small></span
                ></RouterLink
              >
            </td>
            <td>
              <div class="chips">
                <span v-for="b in e.spec.backends" :key="b" :class="['engine', b]">{{
                  labels[b]
                }}</span
                ><span v-if="!e.spec.backends" class="muted">—</span>
              </div>
            </td>
            <td><Status :value="e.status" /></td>
            <td class="muted">{{ date(e.created_at) }}</td>
            <td>
              <RouterLink
                :to="`/experiments/${e.id}`"
                :aria-label="`Открыть эксперимент ${short(e.id)}`"
                class="icon-button"
                ><ArrowUpRight :size="18"
              /></RouterLink>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="pagination">
      <span>Страница {{ page + 1 }} · до 30 записей</span>
      <div>
        <button class="button quiet" :disabled="page === 0" @click="turn(-1)">Назад</button
        ><button class="button quiet" :disabled="rows.length < 30" @click="turn(1)">Далее</button>
      </div>
    </div>
  </section>
</template>
<script lang="ts">
import { Database as DatabaseIcon } from 'lucide-vue-next'
</script>
