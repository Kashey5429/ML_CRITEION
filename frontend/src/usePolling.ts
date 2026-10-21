import { ref, onMounted, onUnmounted } from 'vue'
export function usePolling(load: () => Promise<void>, interval = 4000) {
  const error = ref(''),
    loading = ref(true)
  let disposed = false,
    busy = false,
    timer: ReturnType<typeof setTimeout>
  async function refresh() {
    if (busy || disposed) return
    busy = true
    try {
      await load()
      error.value = ''
    } catch (e) {
      if (!disposed) error.value = e instanceof Error ? e.message : 'Не удалось загрузить данные'
    } finally {
      busy = false
      loading.value = false
    }
  }
  async function tick() {
    await refresh()
    if (!disposed) timer = setTimeout(tick, interval)
  }
  onMounted(tick)
  onUnmounted(() => {
    disposed = true
    clearTimeout(timer)
  })
  return { error, loading, refresh }
}
