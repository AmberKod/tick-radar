import { onBeforeUnmount, ref } from 'vue'
import { useAuthStore } from '../../auth'
import { ApiError, errorMessage } from '../../../shared/api/client'
import * as api from '../api'
import type { PortfolioAccount, PortfolioAccountCreate, PortfolioAccountUpdate, PortfolioEntryCreate, PortfolioEntryPage, PortfolioReversalCreate, PortfolioSummary, PortfolioValuationResponse } from '../types'
export function portfolioError(cause: unknown) {
  if (cause instanceof ApiError) return `${cause.message}（${cause.code}；请求 ID：${cause.requestId}）${cause.status === 0 ? ' 结果尚未确认，请先核对流水；如需重试，请保持原表单，重试会沿用同一请求编号。' : ''}`
  return errorMessage(cause)
}
export function usePortfolio() {
  const auth = useAuthStore()
  const accounts = ref<PortfolioAccount[]>([]), selected = ref(''), summary = ref<PortfolioSummary | null>(null), ledger = ref<PortfolioEntryPage | null>(null), valuation = ref<PortfolioValuationResponse | null>(null)
  const loading = ref(false), saving = ref(false), error = ref(''), valuationError = ref(''), revision = ref(0), page = ref(1)
  let controller = new AbortController(), listRevision = 0, readRevision = 0
  const rotate = () => { controller.abort(); controller = new AbortController(); revision.value++; loading.value = false; saving.value = false }
  function clear() { rotate(); listRevision++; accounts.value = []; selected.value = ''; summary.value = null; ledger.value = null; valuation.value = null; error.value = ''; valuationError.value = ''; page.value = 1 }
  window.addEventListener('auth:cleared', clear)
  onBeforeUnmount(() => { clear(); window.removeEventListener('auth:cleared', clear) })
  async function refresh() {
    if (!selected.value) return
    const read = ++readRevision, version = revision.value, epoch = auth.epoch, id = selected.value, signal = controller.signal
    const valid = () => read === readRevision && version === revision.value && epoch === auth.epoch && !signal.aborted
    loading.value = true; error.value = ''; valuationError.value = ''; valuation.value = null
    await Promise.all([
      api.getSummary(id, { signal }).then(value => { if (valid()) summary.value = value }).catch(cause => { if (valid()) { summary.value = null; error.value = portfolioError(cause) } }),
      api.getLedger(id, page.value, { signal }).then(value => { if (valid()) ledger.value = value }).catch(cause => { if (valid()) { ledger.value = null; error.value = portfolioError(cause) } }),
      api.getValuation(id, { signal }).then(value => { if (valid()) valuation.value = value }).catch(cause => { if (valid()) valuationError.value = portfolioError(cause) }),
    ])
    if (valid()) loading.value = false
  }
  async function select(id: string) { rotate(); selected.value = id; page.value = 1; summary.value = null; ledger.value = null; valuation.value = null; error.value = ''; await refresh() }
  async function load() {
    const version = ++listRevision, epoch = auth.epoch, signal = controller.signal
    loading.value = true; error.value = ''
    try { const value = await api.getAccounts({ signal }); if (version !== listRevision || epoch !== auth.epoch || signal.aborted) return; accounts.value = value.items; if (!selected.value && value.items[0]) await select(value.items[0].id) }
    catch (cause) { if (version === listRevision && epoch === auth.epoch && !signal.aborted) error.value = portfolioError(cause) }
    finally { if (version === listRevision && epoch === auth.epoch && !signal.aborted) loading.value = false }
  }
  async function write(action: (signal: AbortSignal) => Promise<unknown>, done?: (value: unknown) => Promise<void> | void) {
    if (saving.value) return false
    rotate()
    const version = revision.value, epoch = auth.epoch, signal = controller.signal
    const valid = () => version === revision.value && epoch === auth.epoch && !signal.aborted
    saving.value = true; error.value = ''
    try { const result = await action(signal); if (!valid()) return false; await done?.(result); return valid() }
    catch (cause) { if (valid()) error.value = portfolioError(cause); return false }
    finally { if (valid()) saving.value = false }
  }
  async function create(body: PortfolioAccountCreate) {
    let created: PortfolioAccount | undefined
    const success = await write(signal => api.createAccount(body, { signal }), value => { created = value as PortfolioAccount; accounts.value.push(created) })
    if (success && created) await select(created.id)
    return success
  }
  async function update(body: PortfolioAccountUpdate) {
    const id = selected.value
    return write(signal => api.updateAccount(id, body, { signal }), value => { const account = value as PortfolioAccount; accounts.value = accounts.value.map(item => item.id === id ? account : item); if (summary.value) summary.value.account = account })
  }
  const enter = (body: PortfolioEntryCreate) => { const id = selected.value; return write(signal => api.createEntry(id, body, { signal }), refresh) }
  const reverse = (entry: string, body: PortfolioReversalCreate) => { const id = selected.value; return write(signal => api.reverseEntry(id, entry, body, { signal }), refresh) }
  async function changePage(value: number) { rotate(); page.value = value; await refresh() }
  return { accounts, selected, summary, ledger, valuation, loading, saving, error, valuationError, revision, page, load, select, refresh, create, update, enter, reverse, changePage }
}
