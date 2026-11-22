import { ref } from 'vue'
import { defineStore } from 'pinia'
import { searchSecurities, createSecurity, updateSecurity } from '../api'
import type { CreateSecurity, Market, SecurityDTO, UpdateSecurity } from '../types'
import { errorMessage } from '../../../shared/api/client'
export const useSecuritiesStore = defineStore('securities', () => {
  const items = ref<SecurityDTO[]>([]), total = ref(0), page = ref(1), q = ref(''), market = ref<Market | ''>('')
  const loading = ref(false), saving = ref(false), error = ref('')
  let revision = 0
  let controller: AbortController | undefined
  function clear() { revision++; controller?.abort(); items.value = []; total.value = 0; error.value = ''; loading.value = false }
  async function load() {
    const version = ++revision
    controller?.abort()
    controller = new AbortController()
    loading.value = true; error.value = ''
    try {
      const result = await searchSecurities(q.value, market.value, page.value, { signal: controller.signal })
      if (version !== revision) return
      items.value = result.items; total.value = result.total
    } catch (cause) { if (version === revision) { items.value = []; total.value = 0; error.value = errorMessage(cause) } }
    finally { if (version === revision) loading.value = false }
  }
  async function save(body: CreateSecurity | UpdateSecurity, id?: string) {
    if (saving.value) return false
    const version = revision
    saving.value = true; error.value = ''
    try {
      if (id !== undefined) await updateSecurity(id, body as UpdateSecurity)
      else await createSecurity(body as CreateSecurity)
      if (version !== revision) return false
      await load(); return true
    } catch (cause) { if (version === revision) error.value = errorMessage(cause); return false }
    finally { saving.value = false }
  }
  window.addEventListener('auth:cleared', clear)
  return { items, total, page, q, market, loading, saving, error, load, save, clear }
})
