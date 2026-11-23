import { onBeforeUnmount, ref, watch } from 'vue'
import { useAuthStore } from '../../auth'
import { ApiError, errorMessage } from '../../../shared/api/client'
import * as api from '../api/schedules'
import type { Schedule, ScheduleCreate, SchedulePreview, ScheduleRunPage } from '../types/schedules'
export function useSchedules() {
  const auth = useAuthStore(), schedules = ref<Schedule[]>([]), selected = ref<Schedule | null>(null)
  const preview = ref<SchedulePreview | null>(null), runs = ref<ScheduleRunPage | null>(null), error = ref(''), busy = ref(false), revision = ref(0), runFilter = ref<'all' | 'selected'>('all')
  let controller = new AbortController(), listRevision = 0, runRevision = 0, runsController = new AbortController(), disposed = false
  function rotate() { controller.abort(); controller = new AbortController(); runsController.abort(); runsController = new AbortController(); revision.value++; listRevision++; runRevision++; busy.value = false; error.value = ''; preview.value = null; runs.value = null }
  function clear() { rotate(); schedules.value = []; selected.value = null }
  window.addEventListener('auth:cleared', clear)
  watch(() => auth.epoch, clear, { flush: 'sync' })
  onBeforeUnmount(() => { disposed = true; clear(); window.removeEventListener('auth:cleared', clear) })
  function report(cause: unknown) { error.value = cause instanceof ApiError && cause.status === 409 ? `版本冲突，草稿已保留。请先复制草稿，再刷新列表并重新选择提醒核对版本。（${cause.code}；请求 ID：${cause.requestId}）` : errorMessage(cause) }
  async function run<T>(action: (signal: AbortSignal) => Promise<T>, accept: (result: T) => void) {
    if (busy.value || !auth.authenticated || disposed) return false
    const request = revision.value, epoch = auth.epoch, signal = controller.signal
    const valid = () => !disposed && request === revision.value && epoch === auth.epoch && !signal.aborted
    busy.value = true; error.value = ''
    try { const value = await action(signal); if (!valid()) return false; accept(value); return true }
    catch (cause) { if (valid()) report(cause); return false }
    finally { if (valid()) busy.value = false }
  }
  async function load() {
    if (!auth.authenticated || disposed) return
    const request = ++listRevision, epoch = auth.epoch, signal = controller.signal
    try { const value = await api.listSchedules({ signal }); if (!disposed && request === listRevision && epoch === auth.epoch && !signal.aborted) schedules.value = value.items }
    catch (cause) { if (!disposed && request === listRevision && epoch === auth.epoch && !signal.aborted) report(cause) }
  }
  function select(value: Schedule | null) { rotate(); selected.value = value }
  function accept(value: Schedule) { listRevision++; runRevision++; runsController.abort(); runs.value = null; schedules.value = [...schedules.value.filter(item => item.id !== value.id), value]; selected.value = value; preview.value = null }
  const save = (body: ScheduleCreate) => { const value = selected.value; return run(signal => value ? api.updateSchedule(value.id, { ...body, version: value.version }, { signal }) : api.createSchedule(body, { signal }), accept) }
  const remove = () => { const value = selected.value; return value ? run(signal => api.deleteSchedule(value.id, value.version, { signal }), () => { listRevision++; schedules.value = schedules.value.filter(item => item.id !== value.id); selected.value = null; preview.value = null; runs.value = null; runRevision++; runsController.abort() }) : Promise.resolve(false) }
  const simulate = () => { const value = selected.value; return value ? run(signal => api.previewSchedule(value.id, { signal }), value => { preview.value = value }) : Promise.resolve(false) }
  async function loadRuns(page = 1) {
    runsController.abort(); runsController = new AbortController()
    const request = ++runRevision, epoch = auth.epoch, selection = revision.value, signal = runsController.signal, id = runFilter.value === 'selected' ? selected.value?.id : ''
    runs.value = null
    if (!auth.authenticated || disposed || (runFilter.value === 'selected' && !id)) return
    const valid = () => !disposed && request === runRevision && epoch === auth.epoch && selection === revision.value && !signal.aborted
    try { const value = await api.getScheduleRuns(page, id || '', { signal }); if (valid()) runs.value = value }
    catch (cause) { if (valid()) report(cause) }
  }
  return { schedules, selected, preview, runs, error, busy, revision, runFilter, load, select, save, remove, simulate, loadRuns }
}
