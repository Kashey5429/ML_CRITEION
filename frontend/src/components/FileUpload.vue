<script setup lang="ts">
import { ref, onBeforeUnmount } from 'vue'
import { UploadCloud } from 'lucide-vue-next'
import type { FileImport } from '../api'
const props = defineProps<{ datasetId?: string }>()
const emit = defineEmits<{ uploaded: [value: FileImport] }>()
const input = ref<HTMLInputElement>(),
  file = ref<File>(),
  busy = ref(false),
  progress = ref(0)
const error = ref(''),
  dragging = ref(false),
  encoding = ref('auto'),
  delimiter = ref('auto')
let request: XMLHttpRequest | undefined
onBeforeUnmount(() => request?.abort())
function choose(files: FileList | null) {
  if (!files?.length) return
  error.value = ''
  if (files.length !== 1) {
    error.value = 'Выберите один CSV-файл.'
    return
  }
  const candidate = files[0]!
  if (!candidate.name.toLowerCase().endsWith('.csv')) {
    error.value = 'Сохраните таблицу в формате CSV.'
    return
  }
  if (!candidate.size) {
    error.value = 'Файл пуст. Выберите CSV с данными.'
    return
  }
  file.value = candidate
}
function drop(event: DragEvent) {
  dragging.value = false
  if (!busy.value) choose(event.dataTransfer?.files ?? null)
}
function upload() {
  if (!file.value || busy.value) return
  busy.value = true
  error.value = ''
  progress.value = 0
  const query = new URLSearchParams({
    filename: file.value.name,
    encoding: encoding.value,
    delimiter: delimiter.value,
  })
  if (props.datasetId) query.set('dataset_id', props.datasetId)
  const xhr = new XMLHttpRequest()
  request = xhr
  xhr.open('POST', `/api/v1/imports?${query}`)
  // No overall transfer deadline: large files may take hours to upload.
  xhr.timeout = 0
  xhr.setRequestHeader('Content-Type', 'text/csv')
  xhr.upload.onprogress = (event) => {
    if (event.lengthComputable) progress.value = Math.round((event.loaded / event.total) * 100)
  }
  xhr.onload = () => {
    busy.value = false
    let data
    try {
      data = JSON.parse(xhr.responseText)
    } catch {
      error.value = 'Сервер не смог принять файл. Попробуйте ещё раз.'
      return
    }
    if (xhr.status >= 200 && xhr.status < 300) emit('uploaded', data)
    else error.value = data?.error?.code || 'Не удалось загрузить файл.'
  }
  xhr.onerror = xhr.ontimeout = () => {
    busy.value = false
    error.value = 'Соединение прервано. Повторите загрузку.'
  }
  xhr.onabort = () => {
    busy.value = false
  }
  xhr.send(file.value)
}
function example() {
  const rows = ['Площадь,Комнаты,Цена']
  for (let i = 1; i <= 100; i++)
    rows.push(`${30 + i},${1 + (i % 4)},${200 + i * 7 + (i % 4) * 12 + Math.sin(i) * 3}`)
  file.value = new File(['\ufeff' + rows.join('\n')], 'Пример квартир.csv', { type: 'text/csv' })
  upload()
}
function fileSize(bytes: number) {
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} ${units[index]}`
}
</script>
<template>
  <div
    class="upload-zone"
    :class="{ dragging }"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop.prevent="drop"
  >
    <UploadCloud :size="40" />
    <h2>{{ file ? file.name : 'Перетащите CSV-файл сюда' }}</h2>
    <p>
      {{ file ? `${fileSize(file.size)} · готов к загрузке` : 'или выберите его на компьютере' }}
    </p>
    <input
      ref="input"
      class="visually-hidden"
      type="file"
      accept=".csv,text/csv"
      aria-label="CSV-файл"
      :disabled="busy"
      @change="choose(($event.target as HTMLInputElement).files)"
    />
    <button class="button secondary" :disabled="busy" @click="input?.click()">
      {{ file ? 'Заменить файл' : 'Выбрать файл' }}
    </button>
    <button v-if="file" class="button primary" :disabled="busy" @click="upload">
      {{ busy ? 'Загрузка…' : 'Загрузить и проверить' }}
    </button>
    <button v-if="!file" class="button quiet" :disabled="busy" @click="example">
      Попробовать пример
    </button>
    <div v-if="busy" role="status">
      <progress :value="progress" max="100" /> {{ progress }}%
      <button class="button quiet" @click="request?.abort()">Отменить загрузку</button>
    </div>
  </div>
  <details class="import-options">
    <summary>Кодировка и разделитель CSV</summary>
    <p class="muted">
      Если заголовки или столбцы распознаны неверно, измените настройки и загрузите файл повторно.
    </p>
    <div class="form-grid">
      <label
        >Кодировка<select v-model="encoding" :disabled="busy">
          <option value="auto">Определить автоматически</option>
          <option value="utf-8-sig">UTF-8</option>
          <option value="cp1251">Windows-1251</option>
        </select></label
      >
      <label
        >Разделитель<select v-model="delimiter" :disabled="busy">
          <option value="auto">Определить автоматически</option>
          <option value=",">Запятая</option>
          <option value=";">Точка с запятой</option>
          <option :value="'\t'">Табуляция</option>
        </select></label
      >
    </div>
  </details>
  <p v-if="error" class="alert error" role="alert">{{ error }}</p>
</template>
