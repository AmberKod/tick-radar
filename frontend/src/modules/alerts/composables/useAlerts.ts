import { onBeforeUnmount, ref } from 'vue'
import { useAuthStore } from '../../auth'
import { ApiError, errorMessage } from '../../../shared/api/client'
import * as api from '../api'
import type { AlertRule, AlertRuleCreate, AlertEventPage, AlertPreview } from '../types'
export function useAlerts() {
  const auth = useAuthStore(), rules = ref<AlertRule[]>([]), selected = ref<AlertRule | null>(null), events = ref<AlertEventPage | null>(null), preview = ref<AlertPreview | null>(null)
  const error = ref(''), busy = ref(false), revision = ref(0)
  let controller = new AbortController(), listRevision = 0
  function rotate() { controller.abort(); controller = new AbortController(); revision.value++; busy.value = false; error.value = ''; preview.value = null }
  function clear() { rotate(); listRevision++; rules.value = []; selected.value = null; events.value = null }
  window.addEventListener('auth:cleared', clear)
  onBeforeUnmount(() => { clear(); window.removeEventListener('auth:cleared', clear) })
  async function run<T>(action: (signal: AbortSignal) => Promise<T>, done: (result: T) => void) {
    if (busy.value || !auth.authenticated) return false
    const version = revision.value, epoch = auth.epoch, signal = controller.signal
    const valid = () => version === revision.value && epoch === auth.epoch && !signal.aborted
    busy.value = true; error.value = ''
    try { const result = await action(signal); if (!valid()) return false; done(result); return true }
    catch (cause) { if (valid()) error.value = cause instanceof ApiError ? `${cause.status === 409 ? '版本冲突，草稿已保留。请先复制草稿，再手动刷新列表并重新选择规则核对最新版本。' : cause.message}（${cause.code}；请求 ID：${cause.requestId}）` : errorMessage(cause); return false }
    finally { if (valid()) busy.value = false }
  }
  async function load() {
    const request = ++listRevision, epoch = auth.epoch, signal = controller.signal
    if (!auth.authenticated) return
    try { const result = await api.listRules({ signal }); if (request === listRevision && epoch === auth.epoch && !signal.aborted) rules.value = result.items }
    catch (cause) { if (request === listRevision && epoch === auth.epoch && !signal.aborted) error.value = errorMessage(cause) }
  }
  function select(rule: AlertRule | null) { rotate(); listRevision++; selected.value = rule; events.value = null }
  function accept(rule: AlertRule) { rules.value = [...rules.value.filter(item => item.id !== rule.id), rule]; selected.value = rule }
  const save = (body: AlertRuleCreate) => { const rule = selected.value; return run(signal => rule ? api.updateRule(rule.id, { ...body, version: rule.version }, { signal }) : api.createRule(body, { signal }), accept) }
  const reset = () => { const rule = selected.value; return rule ? run(signal => api.resetRule(rule.id, rule.version, { signal }), accept) : Promise.resolve(false) }
  const remove = () => { const rule = selected.value; return rule ? run(signal => api.deleteRule(rule.id, rule.version, { signal }), () => { rules.value = rules.value.filter(item => item.id !== rule.id); selected.value = null }) : Promise.resolve(false) }
  const simulate = () => { const rule = selected.value; return rule ? run(signal => api.previewRule(rule.id, { signal }), value => { preview.value = value }) : Promise.resolve(false) }
  const loadEvents = (page = 1, ruleId = '') => { rotate(); events.value = null; return run(signal => api.getEvents(page, ruleId, { signal }), value => { events.value = value }) }
  return { rules, selected, events, preview, error, busy, revision, load, select, save, reset, remove, simulate, loadEvents }
}
