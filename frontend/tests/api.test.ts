import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiGet, apiDelete, getAccessToken, setAccessToken } from '../src/shared/api/client'
import { updateSecurity } from '../src/modules/securities/api'
import { addItem, getItems, moveItem, orderGroups, orderItems } from '../src/modules/watchlist/api'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); setAccessToken('') })
describe('UUID API 契约', () => {
  it('证券局部更新保留 UUID 路径且允许省略 name', async () => {
    const id = '00000000-0000-4000-8000-000000000001'
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}'))
    vi.stubGlobal('fetch', fetchMock)
    await updateSecurity(id, { status: 'INACTIVE' })
    expect(fetchMock).toHaveBeenCalledWith(`/api/v1/securities/${id}`, expect.objectContaining({ method: 'PUT', body: JSON.stringify({ status: 'INACTIVE' }) }))
  })
  it('成员添加、移动及排序均发送 UUID 字符串', async () => {
    const groupId = '00000000-0000-4000-8000-000000000001'
    const securityId = '00000000-0000-4000-8000-000000000002'
    const itemId = '00000000-0000-4000-8000-000000000003'
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}')))
    vi.stubGlobal('fetch', fetchMock)
    await getItems(groupId)
    await addItem(groupId, securityId)
    await moveItem(itemId, groupId)
    await orderGroups([groupId])
    await orderItems(groupId, [itemId])
    expect(fetchMock.mock.calls.map(([url, init]) => [url, init.body && JSON.parse(init.body)])).toEqual([
      [`/api/v1/watchlists?group_id=${groupId}`, undefined],
      ['/api/v1/watchlists', { group_id: groupId, security_id: securityId }],
      [`/api/v1/watchlists/${itemId}/move`, { group_id: groupId }],
      ['/api/v1/watchlist-groups/order', { ids: [groupId] }],
      ['/api/v1/watchlists/order', { group_id: groupId, ids: [itemId] }],
    ])
  })
})
describe('统一 API 客户端', () => {
  it('传递请求标识并返回真实响应', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })))
    vi.stubGlobal('fetch', fetchMock)
    await expect(apiGet('/test')).resolves.toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/test', expect.objectContaining({ headers: expect.objectContaining({ 'X-Request-ID': expect.any(String) }) }))
  })
  it('将503依赖错误转换为结构化异常', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'DEPENDENCY_UNAVAILABLE', message: '数据库不可用', trace_id: 'server-id' }), { status: 503 })))
    await expect(apiGet('/test')).rejects.toMatchObject({ status: 503, code: 'DEPENDENCY_UNAVAILABLE', message: '数据库不可用', requestId: 'server-id' })
  })
  it('请求超时会取消连接并返回明确错误', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn((_url, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })))
    const result = expect(apiGet('/test', { timeoutMs: 30 })).rejects.toMatchObject({ code: 'TIMEOUT', status: 0 })
    await vi.advanceTimersByTimeAsync(31)
    await result
  })
  it('删除成功的204不尝试解析JSON且发送内存Token', async () => {
    setAccessToken('synthetic-current-token')
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(apiDelete('/watchlists/fixture')).resolves.toBeUndefined()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/watchlists/fixture', expect.objectContaining({ method: 'DELETE', headers: expect.objectContaining({ Authorization: 'Bearer synthetic-current-token' }) }))
  })
  it('旧Token迟到的401不清除新会话', async () => {
    let finish!: (response: Response) => void
    setAccessToken('synthetic-old-token')
    vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { finish = resolve })))
    const oldRequest = expect(apiGet('/test')).rejects.toMatchObject({ status: 401 })
    setAccessToken('synthetic-new-token')
    finish(new Response('{}', { status: 401 }))
    await oldRequest
    expect(getAccessToken()).toBe('synthetic-new-token')
  })
  it('相同Token重新登录后旧请求迟到401不注销新会话', async () => {
    let finish!: (response: Response) => void
    setAccessToken('synthetic-reused-token')
    vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { finish = resolve })))
    const pending = expect(apiGet('/test')).rejects.toMatchObject({ status: 401 })
    setAccessToken(''); setAccessToken('synthetic-reused-token')
    finish(new Response('{}', { status: 401 })); await pending
    expect(getAccessToken()).toBe('synthetic-reused-token')
  })
  it('401响应体读取期间取消仍保留取消语义且不清除新会话', async () => {
    let rejectBody!: (reason: unknown) => void
    const serverResponse = new Response(null, { status: 401 })
    vi.spyOn(serverResponse, 'json').mockImplementation(() => new Promise((_resolve, reject) => { rejectBody = reject }))
    setAccessToken('synthetic-reused-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(serverResponse))
    const controller = new AbortController()
    const pending = expect(apiGet('/test', { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' })
    await vi.waitFor(() => expect(serverResponse.json).toHaveBeenCalledOnce())
    controller.abort(); setAccessToken(''); setAccessToken('synthetic-reused-token')
    rejectBody(new DOMException('Aborted', 'AbortError')); await pending
    expect(getAccessToken()).toBe('synthetic-reused-token')
  })
  it('401发出统一认证事件', async () => {
    const listener = vi.fn()
    window.addEventListener('api:unauthorized', listener)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })))
    await expect(apiGet('/test')).rejects.toMatchObject({ status: 401 })
    expect(listener).toHaveBeenCalledOnce()
    window.removeEventListener('api:unauthorized', listener)
  })
  it('外部取消保留取消语义', async () => {
    const controller = new AbortController()
    vi.stubGlobal('fetch', vi.fn((_url, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })))
    const result = expect(apiGet('/test', { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' })
    controller.abort()
    await result
  })
})
