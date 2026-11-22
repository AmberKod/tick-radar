import { ref } from 'vue'
import { defineStore } from 'pinia'
import * as api from '../api'
import type { Group, Item } from '../types'
import { errorMessage } from '../../../shared/api/client'
export const useWatchlistStore = defineStore('watchlist', () => {
  const groups = ref<Group[]>([]), items = ref<Item[]>([]), selected = ref<string | null>(null)
  const loading = ref(false), saving = ref(false), error = ref('')
  let revision = 0, session = 0
  let controller: AbortController | undefined
  function clear() { session++; revision++; controller?.abort(); groups.value = []; items.value = []; selected.value = null; loading.value = false; error.value = '' }
  async function load(includeGroups = true) {
    const version = ++revision
    controller?.abort(); controller = new AbortController()
    const signal = controller.signal
    loading.value = true; error.value = ''
    try {
      if (includeGroups) {
        const result = await api.getGroups({ signal })
        if (version !== revision) return
        groups.value = [...result.groups].sort((a, b) => a.position - b.position)
        if (!groups.value.some(group => group.id === selected.value)) { selected.value = groups.value[0]?.id ?? null; items.value = [] }
      }
      if (selected.value !== null) {
        const result = await api.getItems(selected.value, { signal })
        if (version !== revision) return
        items.value = [...result.items].sort((a, b) => a.position - b.position)
      }
    } catch (cause) { if (version === revision) error.value = errorMessage(cause) }
    finally { if (version === revision) loading.value = false }
  }
  function select(id: string) { if (saving.value || loading.value) return; selected.value = id; items.value = []; void load(false) }
  async function mutate(action: () => Promise<unknown>) {
    if (saving.value || loading.value) return false
    const version = session
    saving.value = true; error.value = ''
    try { await action(); if (version !== session) return false; await load(); return true }
    catch (cause) { if (version === session) error.value = errorMessage(cause); return false }
    finally { saving.value = false }
  }
  function reorder(kind: 'groups' | 'items', index: number, direction: number) {
    const list = kind === 'groups' ? groups.value : items.value
    const destination = index + direction
    if (destination < 0 || destination >= list.length || selected.value === null) return
    const ids = list.map(item => item.id)
    ;[ids[index], ids[destination]] = [ids[destination]!, ids[index]!]
    return mutate(() => kind === 'groups' ? api.orderGroups(ids) : api.orderItems(selected.value!, ids))
  }
  window.addEventListener('auth:cleared', clear)
  return { groups, items, selected, loading, saving, error, load, select, mutate, reorder, clear }
})
