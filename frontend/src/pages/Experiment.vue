<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  ArrowLeft,
  Download,
  Play,
  Square,
  Clock3,
  CheckCheck,
  Activity,
  ArrowUpRight,
  Info,
} from 'lucide-vue-next'
import { api, all, active, short, date, number, seconds, labels, reasons } from '../api'
import type { Experiment, Results, Run, Attempt } from '../api'
import { usePolling } from '../usePolling'
import Status from '../components/Status.vue'
const id = String(useRoute().params.id),
  experiment = ref<Experiment | null>(null),
  results = ref<Results | null>(null),
  runs = ref<Run[]>([]),
  attempts = ref<Attempt[]>([]),
  busy = ref(false),
  actionError = ref(''),
  confirmCancel = ref(false),
  tab = ref('overview'),
  caseId = ref('')
const { error, loading, refresh } = usePolling(async () => {
  const [e, res, r, a] = await Promise.all([
    api<Experiment>(`/experiments/${id}`),
    api<Results>(`/experiments/${id}/results`),
    api<Run[]>(`/experiments/${id}/runs?limit=200`),
    all<Attempt>(`/experiments/${id}/attempts`),
  ])
  experiment.value = e
  results.value = res
  runs.value = r
  attempts.value = a
  if (!caseId.value) caseId.value = res.analysis?.cases[0]?.case_id || ''
})
const selected = computed(() =>
  results.value?.analysis?.cases.find((c) => c.case_id === caseId.value),
)
const finished = computed(
  () =>
    runs.value.filter((r) => ['succeeded', 'failed', 'cancelled', 'interrupted'].includes(r.status))
      .length,
)
const progress = computed(() =>
  runs.value.length ? Math.round((finished.value / runs.value.length) * 100) : 0,
)
const failures = computed(() => attempts.value.filter((a) => a.error_code))
const maxTime = computed(() =>
  Math.max(
    selected.value?.statistics?.median_madlib_ns || 0,
    selected.value?.statistics?.median_sklearn_ns || 0,
    1,
  ),
)
const metric = (b: string, scope: string, name: string) =>
  selected.value?.resources[b]?.[scope]?.[name]?.median
async function command(action: string) {
  busy.value = true
  actionError.value = ''
  try {
    await api(`/experiments/${id}/${action}`, {})
    confirmCancel.value = false
    await refresh()
  } catch (e) {
    actionError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
const quality = (backend: string) =>
  results.value?.summary.find((s) => s.case_id === caseId.value && s.backend === backend)
    ?.median_rmse
const rmse = (v: number | null | undefined) =>
  v == null ? '—' : v === 0 ? '0' : v.toExponential(3)
</script>
<template>
  <RouterLink class="back-link" to="/experiments"
    ><ArrowLeft :size="16" />Все эксперименты</RouterLink
  >
  <div v-if="error || actionError" class="alert error" role="alert">
    {{ actionError || error }} <button @click="refresh">Повторить</button>
  </div>
  <div v-if="loading" class="empty">Загружаем эксперимент…</div>
  <template v-if="experiment">
    <div class="page-heading">
      <div>
        <div class="eyebrow">
          ЭКСПЕРИМЕНТ / <span class="mono">{{ short(id) }}</span>
        </div>
        <h1>
          {{
            experiment.spec.kind === 'benchmark' ? 'Линейная регрессия' : 'Диагностическая проверка'
          }}
        </h1>
        <p>
          Создан {{ date(experiment.created_at) }}
          <span class="inline-status"><Status :value="experiment.status" /></span>
        </p>
      </div>
      <div class="actions">
        <a
          v-if="results?.analysis"
          class="button secondary"
          :href="`/api/v1/experiments/${id}/report`"
          download
          ><Download :size="17" />JSON-отчёт</a
        ><button
          v-if="experiment.status === 'draft'"
          class="button primary"
          :disabled="busy"
          @click="command('start')"
        >
          <Play :size="16" />Запустить</button
        ><button
          v-if="active(experiment.status) && experiment.status !== 'cancelling'"
          class="button danger"
          :disabled="busy"
          @click="confirmCancel = true"
        >
          <Square :size="14" />Отменить
        </button>
      </div>
    </div>
    <div v-if="confirmCancel" class="alert warning" role="alert">
      <span>Остановить эксперимент? Завершённые результаты сохранятся.</span>
      <div class="actions">
        <button class="button danger" :disabled="busy" @click="command('cancel')">
          Да, остановить</button
        ><button class="button quiet" @click="confirmCancel = false">Продолжить выполнение</button>
      </div>
    </div>
    <div v-if="experiment.status === 'draft'" class="alert info">
      <Info :size="20" /><span
        >Конфигурация сохранена. Нажмите «Запустить», чтобы поставить эксперимент в очередь.</span
      >
    </div>
    <section v-if="active(experiment.status) || runs.length" class="panel progress-panel">
      <div class="section-heading">
        <span
          ><strong>{{ finished }} / {{ runs.length }}</strong> запусков обработано</span
        ><span class="muted small"
          >{{ active(experiment.status) ? 'Обновляется автоматически' : 'Серия завершена' }} ·
          {{ progress }}%</span
        >
      </div>
      <div
        class="progress-track"
        role="progressbar"
        :aria-valuenow="progress"
        aria-valuemin="0"
        aria-valuemax="100"
        aria-label="Выполнение эксперимента"
      >
        <div :style="{ width: progress + '%' }"></div>
      </div>
      <div class="legend small">
        <span><i class="dot teal-bg"></i>{{ results?.completed_runs || 0 }} успешно</span
        ><span
          ><i class="dot orange-bg"></i>{{ runs.filter((r) => r.warmup).length }} прогревочных
          запусков</span
        ><span>{{ failures.length }} ошибок попыток</span>
      </div>
    </section>
    <div class="detail-tabs tabs">
      <button
        v-for="t in [
          ['overview', 'Результаты'],
          ['runs', 'Запуски и попытки'],
          ['config', 'Конфигурация'],
        ]"
        :key="t[0]"
        :class="{ chosen: tab === t[0] }"
        @click="tab = t[0]!"
      >
        {{ t[1] }}
      </button>
    </div>
    <template v-if="tab === 'overview'">
      <div v-if="!results?.analysis" class="panel empty">
        <Activity :size="34" />
        <h3>
          {{
            active(experiment.status) ? 'Измерения в процессе' : 'Парный отчёт пока не опубликован'
          }}
        </h3>
        <p>
          Рекомендация появится после завершения серии.<br />Для старых экспериментов отчёт может
          отсутствовать.
        </p>
        <button v-if="runs.length" class="button secondary" @click="tab = 'runs'">
          Посмотреть отдельные запуски
        </button>
      </div>
      <template v-else-if="selected"
        ><div class="case-toolbar">
          <h2>Сравнение подходов</h2>
          <label
            >Вариант<select v-model="caseId">
              <option v-for="c in results.analysis.cases" :key="c.case_id" :value="c.case_id">
                {{ number(c.config.sample_size, 0) }} строк ·
                {{ c.config.fit_intercept ? 'с intercept' : 'без intercept' }}
              </option>
            </select></label
          >
        </div>
        <div class="result-grid">
          <section class="panel chart-panel">
            <div class="section-heading">
              <h2>Время выполнения</h2>
              <Clock3 :size="18" class="muted" />
            </div>
            <p class="muted small">Медиана model wall · только измеряемые пары</p>
            <div v-for="b in ['madlib', 'sklearn']" :key="b" class="bar-row">
              <div>
                <span class="engine" :class="b">{{ labels[b] }}</span
                ><strong>{{
                  seconds(
                    b === 'madlib'
                      ? selected.statistics?.median_madlib_ns
                      : selected.statistics?.median_sklearn_ns,
                  )
                }}</strong>
              </div>
              <div class="bar-track">
                <div
                  :class="b"
                  :style="{
                    width:
                      (((b === 'madlib'
                        ? selected.statistics?.median_madlib_ns
                        : selected.statistics?.median_sklearn_ns) || 0) /
                        maxTime) *
                        100 +
                      '%',
                  }"
                ></div>
              </div>
            </div>
            <div class="chart-foot">
              <span>Подготовка адаптера → обучение → предсказания → запись</span
              ><small>Общая подготовка данных и оценка качества не входят.</small>
            </div>
          </section>
          <section
            class="recommend-card"
            :class="{ neutral: !['madlib', 'sklearn'].includes(selected.verdict) }"
          >
            <div class="eyebrow"><CheckCheck :size="16" />РЕКОМЕНДАЦИЯ</div>
            <h2>{{ labels[selected.verdict] || selected.verdict }}</h2>
            <p v-for="r in selected.reasons" :key="r">{{ reasons[r] || r }}</p>
            <div v-if="selected.statistics" class="recommend-facts">
              <div>
                <strong>{{ number(selected.statistics.median_ratio) }}×</strong
                ><span>время MADlib / scikit-learn</span>
              </div>
              <div>
                <strong
                  >{{ number(selected.statistics.ci95[0]) }} –
                  {{ number(selected.statistics.ci95[1]) }}</strong
                ><span>95% bootstrap-интервал</span>
              </div>
            </div>
            <div class="small">
              {{ selected.statistics?.pairs || 0 }} из {{ selected.expected_pairs }} полных пар ·
              {{ selected.excluded_pairs.length }} исключено
            </div>
          </section>
        </div>
        <section class="panel">
          <div class="panel-toolbar">
            <div>
              <h2>Ресурсы и качество</h2>
              <p class="muted small">
                Две области измерений. Память Python и PostgreSQL не суммируется.
              </p>
            </div>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Показатель</th>
                  <th><span class="engine madlib">MADlib</span></th>
                  <th><span class="engine sklearn">scikit-learn</span></th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>RMSE <small>Медиана успешных измеряемых запусков</small></td>
                  <td v-for="b in ['madlib', 'sklearn']" :key="b" class="mono">
                    {{ rmse(quality(b)) }}
                  </td>
                </tr>
                <template
                  v-for="scope in [
                    ['python_process', 'Python-исполнитель'],
                    ['bench_container', 'Контейнер PostgreSQL'],
                  ]"
                  :key="scope[0]"
                  ><tr>
                    <td>CPU · {{ scope[1] }}<small>Процессорное время, секунды</small></td>
                    <td v-for="b in ['madlib', 'sklearn']" :key="b">
                      {{ number(metric(b, scope[0]!, 'cpu_seconds'), 4)
                      }}<small
                        >{{
                          selected.resources[b]?.[scope[0]!]?.cpu_seconds?.available_pairs || 0
                        }}
                        измерений</small
                      >
                    </td>
                  </tr>
                  <tr>
                    <td>
                      RAM · {{ scope[1]
                      }}<small
                        >{{
                          scope[0] === 'python_process'
                            ? 'Наблюдаемый пик RSS'
                            : 'Наблюдаемый пик memory.current'
                        }}, MiB</small
                      >
                    </td>
                    <td v-for="b in ['madlib', 'sklearn']" :key="b">
                      {{
                        metric(b, scope[0]!, 'peak_memory_bytes') == null
                          ? '—'
                          : number(metric(b, scope[0]!, 'peak_memory_bytes')! / 1024 ** 2)
                      }}<small
                        >{{
                          selected.resources[b]?.[scope[0]!]?.peak_memory_bytes?.available_pairs ||
                          0
                        }}
                        измерений</small
                      >
                    </td>
                  </tr></template
                >
              </tbody>
            </table>
          </div>
          <div class="panel-foot small muted">
            <Info :size="16" />«—» означает отсутствие измерения. Короткие пики могут быть
            пропущены; контейнер БД включает кеш и фоновую активность.
          </div>
        </section>
        <details class="panel form-panel">
          <summary>Ограничения и основания вывода</summary>
          <p class="muted">
            Вывод относится только к этой выборке и окружению. Интервал рассчитан отдельно для
            варианта; коррекция множественных сравнений не выполняется.
          </p>
          <div v-for="(c, b) in selected.constraints" :key="b">
            <strong>{{ labels[b] || b }}</strong
            >:
            {{
              c.status === 'feasible'
                ? 'ограничения соблюдены'
                : c.status === 'unknown'
                  ? 'не все ограничения проверены'
                  : 'ограничения нарушены'
            }}
            <ul v-if="c.violations.length || c.unknown.length">
              <li v-for="v in [...c.violations, ...c.unknown]" :key="v">{{ v }}</li>
            </ul>
          </div>
          <ul v-if="selected.excluded_pairs.length">
            <li v-for="p in selected.excluded_pairs" :key="p.pair_id">
              Пара {{ short(p.pair_id) }}: {{ p.reason }}
            </li>
          </ul>
        </details>
      </template>
    </template>
    <template v-if="tab === 'runs'"
      ><section class="panel">
        <div class="panel-toolbar">
          <h2>
            Запуски <span class="muted">{{ runs.length }}</span>
          </h2>
          <span class="small muted">Прогревы исключены из парной статистики</span>
        </div>
        <div v-if="!runs.length" class="empty">Запуски появятся после постановки в очередь.</div>
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Подход</th>
                <th>Выборка</th>
                <th>Повтор</th>
                <th>Статус</th>
                <th>Время</th>
                <th>RMSE</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in runs" :key="r.id">
                <td>
                  <span class="engine" :class="r.backend">{{ labels[r.backend] }}</span>
                </td>
                <td>
                  {{ number(r.config.sample_size, 0)
                  }}<small>{{ r.config.fit_intercept ? 'с intercept' : 'без intercept' }}</small>
                </td>
                <td>{{ r.warmup ? 'Прогрев' : 'Измерение' }} {{ r.repeat_index + 1 }}</td>
                <td><Status :value="r.status" /></td>
                <td>{{ seconds(r.result?.timings.model_wall_ns) }}</td>
                <td class="mono">{{ rmse(r.result?.quality.rmse) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <section class="panel form-panel">
        <h2>Технические попытки</h2>
        <p class="muted small">
          Включая подготовку общей выборки. Здесь доступны артефакты и причины ошибок.
        </p>
        <div v-if="!attempts.length" class="muted">Попыток пока нет.</div>
        <div v-for="a in attempts" :key="a.id" class="attempt-row">
          <span class="mono">{{ short(a.id) }}</span
          ><Status :value="a.status" /><span v-if="a.error_code" class="error-text">{{
            a.error_code
          }}</span
          ><a
            v-if="a.result?.artifact"
            class="text-link"
            :href="`/api/v1/attempts/${a.id}/artifact`"
            download
            >JSON <ArrowUpRight :size="14"
          /></a>
        </div></section
    ></template>
    <section v-if="tab === 'config'" class="panel form-panel">
      <h2>Сохранённая конфигурация</h2>
      <p class="muted">Конфигурация неизменяема. Для других условий создайте новый эксперимент.</p>
      <pre>{{ JSON.stringify(experiment.spec, null, 2) }}</pre>
      <p class="muted small mono">ID: {{ id }}</p>
    </section>
  </template>
</template>
