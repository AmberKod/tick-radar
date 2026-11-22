import { onBeforeUnmount, ref } from 'vue'
import { useAuthStore } from '../../auth'
import { ApiError, errorMessage } from '../../../shared/api/client'
import * as api from '../api'
import type { NotificationInboxPage, NotificationOutboxPage, NotificationDeliveryList, NotificationOutbox } from '../types'
export function canRetry(item: NotificationOutbox) { return item.status === 'RETRY' || item.status === 'DEAD' }
export function useNotifications() {
  const auth = useAuthStore(), inbox = ref<NotificationInboxPage | null>(null), outbox = ref<NotificationOutboxPage | null>(null), deliveries = ref<NotificationDeliveryList | null>(null)
  const selected = ref(''), unreadOnly = ref(false), status = ref(''), inboxPage = ref(1), outboxPage = ref(1), busy = ref(false), error = ref(''), notice = ref('')
  let controller = new AbortController(), revision = 0, testId = '', deliveryRevision = 0
  function rotate() { controller.abort(); controller = new AbortController(); revision++; busy.value = false }
  function clear() { rotate(); deliveryRevision++; inbox.value = null; outbox.value = null; deliveries.value = null; selected.value = ''; testId = ''; error.value = ''; notice.value = ''; unreadOnly.value = false; status.value = ''; inboxPage.value = 1; outboxPage.value = 1 }
  window.addEventListener('auth:cleared', clear)
  onBeforeUnmount(() => { clear(); window.removeEventListener('auth:cleared', clear) })
  async function run<T>(action: (signal: AbortSignal) => Promise<T>, done: (result: T) => void) {
    if (busy.value || !auth.authenticated) return false
    const version = revision, epoch = auth.epoch, signal = controller.signal
    const valid = () => version === revision && epoch === auth.epoch && !signal.aborted
    busy.value = true; error.value = ''
    try { const result = await action(signal); if (!valid()) return false; done(result); return true }
    catch (cause) { if (valid()) error.value = cause instanceof ApiError ? `${cause.message}（${cause.code}；请求 ID：${cause.requestId}）${cause.status === 0 ? ' 结果未确认；测试通知可手动重试并沿用同一请求编号。' : ''}` : errorMessage(cause); return false }
    finally { if (valid()) busy.value = false }
  }
  const refresh = () => run(signal => Promise.all([api.getInbox(inboxPage.value, unreadOnly.value, { signal }), api.getOutbox(outboxPage.value, status.value, { signal })]), ([messages, queue]) => { inbox.value = messages; outbox.value = queue })
  async function filter() { rotate(); inbox.value = null; outbox.value = null; deliveries.value = null; selected.value = ''; await refresh() }
  async function read(id: string) { const success = await run(signal => api.markRead(id, { signal }), () => {}); if (success) await refresh(); return success }
  async function readAll() { const success = await run(signal => api.markAllRead({ signal }), () => {}); if (success) await refresh(); return success }
  async function test() {
    if (!testId) testId = crypto.randomUUID()
    const requestId = testId
    const success = await run(signal => api.testNotification({ request_id: requestId }, { signal }), () => { testId = ''; notice.value = '测试写入待投递，后台完成后刷新收件箱。' })
    if (success) await refresh()
    return success
  }
  async function retry(item: NotificationOutbox) {
    if (!canRetry(item)) return false
    const success = await run(signal => api.retryOutbox(item.id, { signal }), () => { notice.value = '已申请重新投递，请稍后刷新状态。'; deliveries.value = null })
    if (success) await refresh()
    return success
  }
  async function inspect(id: string) {
    const request = ++deliveryRevision
    rotate(); selected.value = id; deliveries.value = null
    return run(signal => api.getDeliveries(id, { signal }), value => { if (request === deliveryRevision) deliveries.value = value })
  }
  return { inbox, outbox, deliveries, selected, unreadOnly, status, inboxPage, outboxPage, busy, error, notice, refresh, filter, read, readAll, test, retry, inspect }
}
