<script setup lang="ts">
import { Check } from 'lucide-vue-next'
const form = defineModel<any>({ required: true })
</script>
<template>
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
</template>
