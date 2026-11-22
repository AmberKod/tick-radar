import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../src/modules/auth'
import { useNotifications, canRetry } from '../src/modules/notifications/composables/useNotifications'
import * as api from '../src/modules/notifications/api'
import { ApiError } from '../src/shared/api/client'
import type { NotificationOutbox, NotificationDeliveryList } from '../src/modules/notifications/types'
vi.mock('../src/modules/notifications/api', () => ({ getInbox: vi.fn(), getOutbox: vi.fn(), markRead: vi.fn(), markAllRead: vi.fn(), getDeliveries: vi.fn(), retryOutbox: vi.fn(), testNotification: vi.fn() }))
const queue = { id: 'o1', event_id: 'e1', channel: 'IN_APP', title: '站内通知测试', body: '投递测试', status: 'RETRY', attempts: 1, max_attempts: 5, next_attempt_at: '', created_at: '', sent_at: null, last_error: null } as NotificationOutbox
beforeEach(() => { setActivePinia(createPinia()); useAuthStore().authenticated = true; vi.resetAllMocks(); vi.mocked(api.getInbox).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20, unread_count: 0 }); vi.mocked(api.getOutbox).mockResolvedValue({ items: [queue], total: 1, page: 1, page_size: 20 }) })
function setup() { let notifications!: ReturnType<typeof useNotifications>; const wrapper = mount(defineComponent({ setup() { notifications = useNotifications(); return () => null } })); return { notifications, wrapper } }
describe('站内通知', () => {
  it('请求适配器使用规定路径且已读与重试无请求体', async () => {
    const adapter = await vi.importActual<typeof api>('../src/modules/notifications/api')
    const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response('{}', { status: 200 }))
    await adapter.markRead('n1'); expect(fetcher.mock.calls[0]![0]).toContain('/notifications/inbox/n1/read'); expect(fetcher.mock.calls[0]![1]).toMatchObject({ method: 'PUT' }); expect(fetcher.mock.calls[0]![1]!.body).toBeUndefined()
    await adapter.retryOutbox('o1'); expect(fetcher.mock.calls[1]![0]).toContain('/notifications/outbox/o1/retry'); expect(fetcher.mock.calls[1]![1]!.body).toBeUndefined()
    await adapter.testNotification({ request_id: 'same-id' }); expect(JSON.parse(fetcher.mock.calls[2]![1]!.body as string)).toEqual({ request_id: 'same-id' })
    fetcher.mockRestore()
  })
  it('测试网络失败保留请求 UUID，成功后下次使用新 UUID，不自动重试写入', async () => {
    const { notifications, wrapper } = setup()
    vi.mocked(api.testNotification).mockRejectedValueOnce(new ApiError('网络失败', 0, 'NETWORK_ERROR', 'r')).mockResolvedValue(queue)
    await notifications.test(); expect(api.testNotification).toHaveBeenCalledTimes(1)
    const first = vi.mocked(api.testNotification).mock.calls[0]![0]
    await notifications.test(); expect(vi.mocked(api.testNotification).mock.calls[1]![0]).toEqual(first)
    expect(notifications.notice.value).toContain('后台完成后刷新收件箱')
    await notifications.test(); expect(vi.mocked(api.testNotification).mock.calls[2]![0].request_id).not.toBe(first.request_id)
    expect(first).toEqual({ request_id: expect.any(String) }); wrapper.unmount()
  })
  it('仅 RETRY/DEAD 且尚有尝试额度可重试，已投递不写入', async () => {
    const { notifications, wrapper } = setup(); vi.mocked(api.retryOutbox).mockResolvedValue(queue)
    expect(canRetry(queue)).toBe(true); expect(canRetry({ ...queue, status: 'DEAD', attempts: 5 })).toBe(true)
    await notifications.retry({ ...queue, status: 'SENT' }); expect(api.retryOutbox).not.toHaveBeenCalled()
    await notifications.retry(queue); expect(api.retryOutbox).toHaveBeenCalledTimes(1); wrapper.unmount()
  })
  it('已读与全部已读后读取真实收件箱，不客户端伪造', async () => {
    const { notifications, wrapper } = setup()
    await notifications.read('n1'); expect(api.markRead).toHaveBeenCalledWith('n1', expect.anything()); expect(api.getInbox).toHaveBeenCalledTimes(1)
    await notifications.readAll(); expect(api.markAllRead).toHaveBeenCalledTimes(1); expect(api.getInbox).toHaveBeenCalledTimes(2); wrapper.unmount()
  })
  it('切投递选择、退出和卸载阻止旧响应回填', async () => {
    const { notifications, wrapper } = setup()
    let finish!: (value: NotificationDeliveryList) => void
    vi.mocked(api.getDeliveries).mockImplementationOnce(() => new Promise(done => { finish = done })).mockResolvedValueOnce({ items: [] })
    const first = notifications.inspect('o1'); await notifications.inspect('o2'); finish({ items: [] }); await first
    expect(notifications.selected.value).toBe('o2')
    let list!: (value: Awaited<ReturnType<typeof api.getOutbox>>) => void
    vi.mocked(api.getOutbox).mockImplementationOnce(() => new Promise(done => { list = done }))
    const refresh = notifications.refresh(); useAuthStore().logout(); list({ items: [queue], total: 1, page: 1, page_size: 20 }); await refresh
    expect(notifications.outbox.value).toBeNull(); expect(notifications.inbox.value).toBeNull(); expect(notifications.selected.value).toBe(''); wrapper.unmount()
  })
})
