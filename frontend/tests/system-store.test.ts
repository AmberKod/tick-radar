import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { systemApi } from '../src/modules/system/api'
import { useSystemStore } from '../src/modules/system/stores/system'
import { modulesFixture, statusFixture } from './fixtures'
vi.mock('../src/modules/system/api', () => ({ systemApi: { status: vi.fn(), modules: vi.fn() } }))
beforeEach(() => { setActivePinia(createPinia()); vi.resetAllMocks() })
describe('系统状态管理', () => {
  it('正常获取降级状态与模块目录', async () => {
    vi.mocked(systemApi.status).mockResolvedValue(statusFixture)
    vi.mocked(systemApi.modules).mockResolvedValue(modulesFixture)
    const store = useSystemStore()
    await store.refresh()
    expect(store.status?.status).toBe('degraded')
    expect(store.connected).toBe(true)
    expect(store.modules).toHaveLength(2)
    expect(store.loading).toBe(false)
  })
  it('模块请求失败仍保留成功的系统状态', async () => {
    vi.mocked(systemApi.status).mockResolvedValue(statusFixture)
    vi.mocked(systemApi.modules).mockRejectedValue(new Error('目录不可用'))
    const store = useSystemStore()
    await store.refresh()
    expect(store.connected).toBe(true)
    expect(store.modulesError?.message).toBe('目录不可用')
  })
  it('系统失败保留上次结果并明确断开连接', async () => {
    vi.mocked(systemApi.status).mockResolvedValueOnce(statusFixture).mockRejectedValueOnce(new Error('网络断开'))
    vi.mocked(systemApi.modules).mockResolvedValue(modulesFixture)
    const store = useSystemStore()
    await store.refresh()
    await store.refresh()
    expect(store.status?.version).toBe('0.1.0')
    expect(store.connected).toBe(false)
    expect(store.error?.message).toBe('网络断开')
  })
  it('并发刷新不允许旧响应覆盖新状态', async () => {
    let resolveOld!: (value: typeof statusFixture) => void
    vi.mocked(systemApi.status).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve })).mockResolvedValueOnce({ ...statusFixture, version: 'new' })
    vi.mocked(systemApi.modules).mockResolvedValue(modulesFixture)
    const store = useSystemStore()
    const old = store.refresh()
    await store.refresh()
    resolveOld({ ...statusFixture, version: 'old' })
    await old
    expect(store.status?.version).toBe('new')
  })
  it('取消后忽略已完成的请求', async () => {
    let finish!: (value: typeof statusFixture) => void
    vi.mocked(systemApi.status).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    vi.mocked(systemApi.modules).mockResolvedValue(modulesFixture)
    const store = useSystemStore()
    const request = store.refresh()
    store.cancel()
    finish(statusFixture)
    await request
    expect(store.status).toBeNull()
    expect(store.loading).toBe(false)
  })
})
