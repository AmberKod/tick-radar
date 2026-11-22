import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../src/modules/auth/stores/auth'
import { useWatchlistStore } from '../src/modules/watchlist/stores/watchlist'
import { useSecuritiesStore } from '../src/modules/securities/stores/securities'
import * as authApi from '../src/modules/auth/api'
import * as watchlistApi from '../src/modules/watchlist/api'
import * as securitiesApi from '../src/modules/securities/api'
import { ApiError, getAccessToken, setAccessToken } from '../src/shared/api/client'

vi.mock('../src/modules/auth/api', () => ({ verifySession: vi.fn() }))
vi.mock('../src/modules/watchlist/api', () => ({ getGroups: vi.fn(), getItems: vi.fn(), orderGroups: vi.fn(), orderItems: vi.fn() }))
vi.mock('../src/modules/securities/api', () => ({ searchSecurities: vi.fn(), createSecurity: vi.fn(), updateSecurity: vi.fn() }))
const groupA = { id: '03a4fb6a-1e16-48a7-9bce-e4262e846b11', name: '合成A组', position: 0 }
const groupB = { id: '3ada8ad6-03ba-4d90-b1dd-9d470f85f5f3', name: '合成B组', position: 1 }

beforeEach(() => { setActivePinia(createPinia()); vi.resetAllMocks(); setAccessToken('') })

describe('业务会话和迟到请求', () => {
  it('未配置认证时不保留 Token 或假登录', async () => {
    vi.mocked(authApi.verifySession).mockRejectedValue(new ApiError('未配置', 503, 'AUTH_NOT_CONFIGURED', 'fixture'))
    const auth = useAuthStore()
    await auth.login('synthetic-token')
    expect(auth.authenticated).toBe(false)
    expect(getAccessToken()).toBe('')
    expect(auth.error).toContain('AUTH_NOT_CONFIGURED')
  })

  it('退出时清空两模块数据，旧证券响应不能回填', async () => {
    let finish!: (value: Awaited<ReturnType<typeof securitiesApi.searchSecurities>>) => void
    vi.mocked(securitiesApi.searchSecurities).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const auth = useAuthStore(), securities = useSecuritiesStore(), watchlist = useWatchlistStore()
    watchlist.groups = [groupA]
    const request = securities.load()
    setAccessToken('synthetic-token')
    auth.logout()
    finish({ items: [], total: 99, page: 1, page_size: 20 })
    await request
    expect(getAccessToken()).toBe('')
    expect(watchlist.groups).toEqual([])
    expect(securities.total).toBe(0)
    expect(securities.loading).toBe(false)
  })

  it('退出后迟到的自选写响应不重新拉取', async () => {
    let finish!: (value: unknown) => void
    const action = vi.fn(() => new Promise(resolve => { finish = resolve }))
    const auth = useAuthStore(), store = useWatchlistStore()
    store.groups = [groupA]
    store.selected = groupA.id
    const mutation = store.mutate(action)
    auth.logout()
    finish({ ok: true })
    expect(await mutation).toBe(false)
    expect(store.groups).toEqual([])
    expect(watchlistApi.getGroups).not.toHaveBeenCalled()
  })

  it('加载时阻止跨组选择，重置后迟到的成员不能回填', async () => {
    let finish!: (value: Awaited<ReturnType<typeof watchlistApi.getItems>>) => void
    vi.mocked(watchlistApi.getItems).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const store = useWatchlistStore()
    store.groups = [groupA, groupB]
    store.selected = groupA.id
    const request = store.load(false)
    store.select(groupB.id)
    expect(store.selected).toBe(groupA.id)
    store.clear()
    finish({ items: [] })
    await request
    expect(store.selected).toBeNull()
    expect(store.items).toEqual([])
    expect(store.loading).toBe(false)
  })

  it('非空删除冲突显示错误且保留原列表', async () => {
    const store = useWatchlistStore()
    store.groups = [groupA]
    store.selected = groupA.id
    const action = vi.fn().mockRejectedValue(new ApiError('非空分组', 409, 'GROUP_NOT_EMPTY', 'fixture'))
    expect(await store.mutate(action)).toBe(false)
    expect(store.groups).toEqual([groupA])
    expect(store.error).toContain('GROUP_NOT_EMPTY')
    expect(watchlistApi.getGroups).not.toHaveBeenCalled()
  })

  it('排序提交完整 UUID 集合且成功后重新读取', async () => {
    const store = useWatchlistStore()
    store.groups = [groupA, groupB]
    store.selected = groupA.id
    vi.mocked(watchlistApi.orderGroups).mockResolvedValue({ groups: [groupB, groupA] })
    vi.mocked(watchlistApi.getGroups).mockResolvedValue({ groups: [{ ...groupB, position: 0 }, { ...groupA, position: 1 }] })
    vi.mocked(watchlistApi.getItems).mockResolvedValue({ items: [] })
    await store.reorder('groups', 0, 1)
    expect(watchlistApi.orderGroups).toHaveBeenCalledWith([groupB.id, groupA.id])
    expect(store.groups[0]?.id).toBe(groupB.id)
  })
})
