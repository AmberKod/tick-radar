import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import MarketDashboard from '../src/modules/market/views/MarketDashboard.vue'
import { useAuthStore } from '../src/modules/auth'
import { verifySession } from '../src/modules/auth/api'
vi.mock('../src/modules/auth/api', () => ({ verifySession: vi.fn() }))
import { useMarketStore } from '../src/modules/market/stores/market'
import * as api from '../src/modules/market/api'
import QuoteTable from '../src/modules/market/components/QuoteTable.vue'
import { ApiError } from '../src/shared/api/client'
import type { QuoteDTO } from '../src/modules/market/types'
vi.mock('../src/modules/market/api', () => ({ getQuote: vi.fn(), getQuotes: vi.fn(), refreshQuotes: vi.fn(), getGroups: vi.fn(), getItems: vi.fn(), createGroup: vi.fn(), createSecurityFromQuote: vi.fn(), addItem: vi.fn() }))
const quote: QuoteDTO = { symbol: 'US:AAPL', name: null, market: 'US', currency: 'USD', currency_basis: 'MARKET_METADATA', timestamp_semantics: 'VENDOR_UPDATE_UNVERIFIED', timestamp_timezone_basis: 'UNVERIFIED', source: 'tencent_public', provider_symbol: 'usAAPL', price: null, prev_close: null, change: null, change_percent: null, market_timestamp: null, source_time_raw: null, received_at: null, cache_age_seconds: null, market_status: 'UNKNOWN', delay_status: 'UNKNOWN', quality_status: 'UNKNOWN', error: null, observation_only: true, warnings: [] }
const group = { id: 'g1', name: '自选', position: 0 }
const usable = { ...quote, name: 'Apple', price: '100' }
vi.mock('naive-ui', () => ({
  NButton: { props: ['disabled', 'attrType'], template: '<button :disabled="disabled" :type="attrType || \'button\'"><slot /></button>' },
  NSelect: { props: ['value', 'options'], emits: ['update:value'], template: '<select :value="value" @change="$emit(\'update:value\', $event.target.value)"><option value="">请选择</option><option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option></select>' },
  NModal: { props: ['show'], template: '<div v-if="show"><slot /></div>' },
  NInput: { props: ['value'], emits: ['update:value'], template: '<input :value="value" @input="$emit(\'update:value\', $event.target.value)" />' }, NAlert: { template: '<div><slot /></div>' }, NTabs: { template: '<div><slot /></div>' }, NTab: { template: '<div><slot /></div>' },
}))
function dashboard() { return mount(MarketDashboard) }
beforeEach(() => { setActivePinia(createPinia()); vi.resetAllMocks(); vi.mocked(api.getGroups).mockResolvedValue({ groups: [group] }); vi.mocked(api.getItems).mockResolvedValue({ items: [] }) })
describe('行情观察', () => {
  it('查询与看板并发不会取消彼此或留下 loading', async () => {
    let finish!: (result: QuoteDTO) => void
    vi.mocked(api.getQuote).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const store = useMarketStore(); store.groupId = group.id
    const pending = store.lookup('US:AAPL')
    await store.loadBoard()
    expect(vi.mocked(api.getQuote).mock.calls[0]?.[1]?.signal?.aborted).toBe(false)
    finish(usable); await pending
    expect(store.quote).toEqual(usable); expect(store.loading).toBe(false)
    store.clear()
  })
  it('退出后晚返回的分组不能回填，公共报价仍保留', async () => {
    let finish!: (result: { groups: typeof group[] }) => void
    vi.mocked(api.getGroups).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const store = useMarketStore(); store.quote = usable
    const pending = store.loadGroups()
    window.dispatchEvent(new CustomEvent('auth:cleared'))
    finish({ groups: [group] }); await pending
    expect(store.groups).toEqual([]); expect(store.groupId).toBe(''); expect(store.quote).toEqual(usable)
    expect(vi.mocked(api.getGroups).mock.calls.at(-1)?.[0]?.signal?.aborted).toBe(true)
  })
  it('匿名查询登录后保留报价，必须手动选择美股交易所才能加入', async () => {
    const wrapper = dashboard(), store = useMarketStore(), auth = useAuthStore()
    vi.mocked(api.getQuote).mockResolvedValue(usable)
    await store.lookup('US:AAPL'); await nextTick()
    await wrapper.findAll('button').find(button => button.text() === '加入自选')!.trigger('click')
    expect(wrapper.html()).toContain('加入自选需要验证')
    vi.mocked(verifySession).mockResolvedValue({ authenticated: true })
    await auth.login('test-token'); await flushPromises()
    expect(store.quote).toEqual(usable)
    expect(wrapper.text()).toContain('确认加入自选')
    const confirm = () => wrapper.findAll('button').find(button => button.text() === '确认加入自选')!
    expect(confirm().attributes('disabled')).toBeUndefined()
    await confirm().trigger('click'); expect(api.createSecurityFromQuote).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('美股交易所需要手动确认')
    await wrapper.find('select[aria-label="证券交易所"]').setValue('NASDAQ')
    vi.mocked(api.createSecurityFromQuote).mockResolvedValue({ id: 's1', symbol: 'US:AAPL' } as Awaited<ReturnType<typeof api.createSecurityFromQuote>>)
    vi.mocked(api.addItem).mockResolvedValue({} as Awaited<ReturnType<typeof api.addItem>>)
    await confirm().trigger('click'); await flushPromises()
    expect(api.createSecurityFromQuote).toHaveBeenCalledWith({ symbol: 'US:AAPL', exchange: 'NASDAQ', security_type: 'STOCK' })
    expect(api.addItem).toHaveBeenCalledWith('g1', 's1'); expect(store.actionMessage).toContain('已加入')
    wrapper.unmount()
  })
  it.each([['CN:000001', 'SZSE', 'STOCK'], ['CN:510300', 'SSE', 'ETF'], ['CN:159915', 'SZSE', 'ETF'], ['CN:920001', 'BSE', 'STOCK']])('从代码 %s 初始化交易所及类型', async (symbol, exchange, type) => {
    const wrapper = dashboard(), store = useMarketStore(), auth = useAuthStore()
    auth.authenticated = true; await flushPromises()
    store.quote = { ...usable, symbol, market: 'CN', currency: 'CNY' }; await nextTick()
    await wrapper.findAll('button').find(button => button.text() === '加入自选')!.trigger('click')
    expect((wrapper.find('select[aria-label="证券交易所"]').element as HTMLSelectElement).value).toBe(exchange)
    expect((wrapper.find('select[aria-label="证券类型"]').element as HTMLSelectElement).value).toBe(type)
    wrapper.unmount()
  })
  it('已有分组仍可创建新组且创建期间禁止重复提交', async () => {
    const wrapper = dashboard(), store = useMarketStore(), auth = useAuthStore()
    auth.authenticated = true; await flushPromises(); store.quote = usable; await nextTick()
    await wrapper.findAll('button').find(button => button.text() === '加入自选')!.trigger('click')
    let finish!: (result: typeof group) => void
    vi.mocked(api.createGroup).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    await wrapper.find('input[aria-label="新分组名称"]').setValue('新分组')
    const form = wrapper.find('input[aria-label="新分组名称"]').element.closest('form')!
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    expect(api.createGroup).toHaveBeenCalledTimes(1)
    const newGroup = { ...group, id: 'g2', name: '新分组' }
    vi.mocked(api.getGroups).mockResolvedValue({ groups: [group, newGroup] }); finish(newGroup); await flushPromises()
    expect((wrapper.find('select[aria-label="选择自选分组"]').element as HTMLSelectElement).value).toBe('g2')
    expect(store.groupId).toBe('g2'); wrapper.unmount()
  })
  it('证券登记成功但分组失败时不显示成功', async () => {
    const wrapper = dashboard(), store = useMarketStore(), auth = useAuthStore()
    auth.authenticated = true; await flushPromises(); store.quote = usable; await nextTick()
    await wrapper.findAll('button').find(button => button.text() === '加入自选')!.trigger('click')
    await wrapper.find('select[aria-label="证券交易所"]').setValue('NASDAQ')
    vi.mocked(api.createSecurityFromQuote).mockResolvedValue({ id: 's1', symbol: 'US:AAPL' } as Awaited<ReturnType<typeof api.createSecurityFromQuote>>)
    vi.mocked(api.addItem).mockRejectedValue(new Error('分组请求失败'))
    await wrapper.findAll('button').find(button => button.text() === '确认加入自选')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('证券已登记，但加入分组失败'); expect(store.actionMessage).toBe('')
    wrapper.unmount()
  })
  it('提交中退出后晚返回不能提示成功或继续加入分组', async () => {
    const wrapper = dashboard(), store = useMarketStore(), auth = useAuthStore()
    auth.authenticated = true; await flushPromises(); store.quote = usable; await nextTick()
    await wrapper.findAll('button').find(button => button.text() === '加入自选')!.trigger('click')
    await wrapper.find('select[aria-label="证券交易所"]').setValue('NASDAQ')
    let finish!: (result: Awaited<ReturnType<typeof api.createSecurityFromQuote>>) => void
    vi.mocked(api.createSecurityFromQuote).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    await wrapper.findAll('button').find(button => button.text() === '确认加入自选')!.trigger('click')
    auth.logout(); finish({ id: 's1', symbol: 'US:AAPL' } as Awaited<ReturnType<typeof api.createSecurityFromQuote>>); await flushPromises()
    expect(api.addItem).not.toHaveBeenCalled(); expect(store.actionMessage).toBe('')
    wrapper.unmount()
  })
  it('有旧价格但请求失败的报价禁止加入', async () => {
    const wrapper = dashboard(), store = useMarketStore()
    store.quote = { ...usable, error: { code: 'UPSTREAM_ERROR', message: '失败' }, quality_status: 'STALE' }
    await nextTick()
    expect(wrapper.findAll('button').find(button => button.text() === '加入自选')!.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('上次请求失败')
    wrapper.unmount()
  })
  it('旧分组刷新失败不污染新分组', async () => {
    let fail!: (cause: Error) => void
    vi.mocked(api.refreshQuotes).mockImplementation(() => new Promise((_, reject) => { fail = reject }))
    const store = useMarketStore(); store.groupId = 'g1'; store.quotes = [usable]
    const pending = store.refresh(); store.groupId = 'g2'
    expect(store.quotes).toEqual([])
    fail(new Error('旧组失败')); await pending
    expect(store.quoteError).toBe(''); store.clear()
  })
  it('报价异常清空旧报价并给出可见错误', async () => {
    const store = useMarketStore(); store.quote = quote
    vi.mocked(api.getQuote).mockRejectedValue(new ApiError('服务不可用', 503, 'UNAVAILABLE', 'trace'))
    await store.lookup('US:AAPL')
    expect(store.quote).toBeNull(); expect(store.error).toContain('UNAVAILABLE')
  })
  it('前一个慢查询被取消，不能覆盖后续结果', async () => {
    let finish!: (result: QuoteDTO) => void
    vi.mocked(api.getQuote).mockImplementationOnce(() => new Promise(resolve => { finish = resolve })).mockResolvedValueOnce({ ...quote, symbol: 'US:MSFT' })
    const store = useMarketStore(), first = store.lookup('US:AAPL')
    await store.lookup('US:MSFT'); finish({ ...quote, symbol: 'US:AAPL' }); await first
    expect(store.quote?.symbol).toBe('US:MSFT')
  })
  it('未知时效与休市状态明确呈现且未知数值留空', () => {
    const wrapper = mount(QuoteTable, { props: { quotes: [{ ...quote, quality_status: 'UNKNOWN' }, { ...quote, symbol: 'CN:600519', market: 'CN', currency: 'CNY', quality_status: 'MARKET_CLOSED', market_status: 'MARKET_CLOSED' }] } })
    expect(wrapper.text()).toContain('时效未知'); expect(wrapper.text()).toContain('休市'); expect(wrapper.text()).toContain('源端时间未知'); expect(wrapper.text()).toContain('—')
  })
})
