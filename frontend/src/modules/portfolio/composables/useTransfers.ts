import { onBeforeUnmount, ref } from 'vue'
import { useAuthStore } from '../../auth'
import { portfolioError } from './usePortfolio'
import * as api from '../api/transfers'
import type { PortfolioReversalCreate } from '../types'
import type { PortfolioTransferCreate, PortfolioTransferPage } from '../types/transfers'
export function useTransfers(changed: () => void) {
  const auth = useAuthStore(), ledger = ref<PortfolioTransferPage | null>(null), page = ref(1), filter = ref(''), loading = ref(false), saving = ref(false), error = ref('')
  let controller = new AbortController(), revision = 0, readRevision = 0
  const rotate = () => { controller.abort(); controller = new AbortController(); revision++; loading.value = false; saving.value = false }
  function clear() { rotate(); readRevision++; ledger.value = null; error.value = ''; page.value = 1; filter.value = '' }
  window.addEventListener('auth:cleared', clear)
  onBeforeUnmount(() => { clear(); window.removeEventListener('auth:cleared', clear) })
  async function load() {
    const read = ++readRevision, version = revision, epoch = auth.epoch, signal = controller.signal, selectedFilter = filter.value
    const valid = () => !signal.aborted && version === revision && epoch === auth.epoch && read === readRevision && selectedFilter === filter.value
    loading.value = true; error.value = ''
    try { const value = await api.getTransfers(page.value, selectedFilter, { signal }); if (valid()) ledger.value = value }
    catch (cause) { if (valid()) { ledger.value = null; error.value = portfolioError(cause) } }
    finally { if (valid()) loading.value = false }
  }
  async function select(value: string) { if (saving.value) return; rotate(); filter.value = value; page.value = 1; ledger.value = null; await load() }
  async function changePage(value: number) { if (saving.value) return; rotate(); page.value = value; ledger.value = null; await load() }
  async function write(action: (signal: AbortSignal) => Promise<unknown>) {
    if (saving.value) return false
    rotate()
    const version = revision, epoch = auth.epoch, signal = controller.signal
    const valid = () => !signal.aborted && version === revision && epoch === auth.epoch
    saving.value = true; error.value = ''
    try { await action(signal); if (!valid()) return false; changed(); await load(); return valid() }
    catch (cause) { if (valid()) error.value = portfolioError(cause); return false }
    finally { if (valid()) saving.value = false }
  }
  return { ledger, page, filter, loading, saving, error, load, select, changePage, create: (body: PortfolioTransferCreate) => write(signal => api.createTransfer(body, { signal })), reverse: (id: string, body: PortfolioReversalCreate) => write(signal => api.reverseTransfer(id, body, { signal })) }
}
