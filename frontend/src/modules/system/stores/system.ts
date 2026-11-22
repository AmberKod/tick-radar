import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { systemApi } from '../api'
import type { SystemModule, SystemStatus } from '../types'

export const useSystemStore = defineStore('system', () => {
  const status = ref<SystemStatus | null>(null)
  const modules = ref<SystemModule[]>([])
  const loading = ref(false)
  const error = ref<Error | null>(null)
  const modulesError = ref<Error | null>(null)
  const updatedAt = ref<Date | null>(null)
  const connected = computed(() => status.value !== null && !error.value)
  let active: AbortController | undefined
  let generation = 0

  async function refresh() {
    active?.abort()
    const controller = new AbortController()
    active = controller
    const current = ++generation
    loading.value = true
    error.value = null
    modulesError.value = null
    const [statusResult, modulesResult] = await Promise.allSettled([
      systemApi.status(controller.signal), systemApi.modules(controller.signal),
    ])
    if (current !== generation || controller.signal.aborted) return
    if (statusResult.status === 'fulfilled') {
      status.value = statusResult.value
      updatedAt.value = new Date()
    } else error.value = asError(statusResult.reason)
    if (modulesResult.status === 'fulfilled') modules.value = modulesResult.value.modules
    else modulesError.value = asError(modulesResult.reason)
    loading.value = false
    active = undefined
  }

  function cancel() {
    generation++
    active?.abort()
    active = undefined
    loading.value = false
  }

  return { status, modules, loading, error, modulesError, updatedAt, connected, refresh, cancel }
})

function asError(value: unknown): Error {
  return value instanceof Error ? value : new Error('服务返回异常，请稍后重试')
}
