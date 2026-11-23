import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PortfolioPage from '../src/modules/portfolio/views/PortfolioPage.vue'
import EntryForm from '../src/modules/portfolio/components/EntryForm.vue'
import LedgerPanel from '../src/modules/portfolio/components/LedgerPanel.vue'
import PositionsPanel from '../src/modules/portfolio/components/PositionsPanel.vue'
import { usePortfolio } from '../src/modules/portfolio/composables/usePortfolio'
import { entryPayload, newDraft } from '../src/modules/portfolio/composables/entryDraft'
import { decimalLabel } from '../src/modules/portfolio/composables/format'
import { useAuthStore } from '../src/modules/auth'
import * as api from '../src/modules/portfolio/api'
import { ApiError } from '../src/shared/api/client'
import type { PortfolioAccount, PortfolioEntry, PortfolioSummary } from '../src/modules/portfolio/types'
import type { SecurityDTO } from '../src/modules/securities'
vi.mock('../src/modules/portfolio/api', () => ({ getAccounts: vi.fn(), createAccount: vi.fn(), updateAccount: vi.fn(), getSummary: vi.fn(), getLedger: vi.fn(), getValuation: vi.fn(), createEntry: vi.fn(), reverseEntry: vi.fn() }))
const account: PortfolioAccount = { id: 'a', name: '测试人民币', currency: 'CNY', is_active: true, created_at: '', updated_at: '' }
const second: PortfolioAccount = { ...account, id: 'b', name: '另一账户' }
const security: SecurityDTO = { id: 'security', symbol: 'sh600000', name: '合成证券', currency: 'CNY', market: 'CN', exchange: 'SSE', security_type: 'STOCK', status: 'ACTIVE', source: 'TENCENT_LOOKUP', created_at: '', updated_at: '' }
const summary: PortfolioSummary = { account, cash_balance: '100', total_cost: '0', realized_pnl: '0', dividend_income: '0', standalone_fees: '0', external_net_flow: '100', internal_net_flow: '0', positions: [], entry_count: 0, checked_at: '2026-01-01T00:00:00Z', calculation_version: 'moving-average-v1', warnings: [] }
const entry: PortfolioEntry = { id: 'e', account_id: 'a', sequence: 1, request_id: 'r', kind: 'DEPOSIT', occurred_at: '2026-01-01T00:00:00Z', security_id: null, symbol: null, security_name: null, currency: 'CNY', quantity: '0', price: '0', amount: '100', fee: '0', tax: '0', gross_amount: '100', cash_delta: '100', status: 'ACTIVE', reversal_of_id: null, reversed_by_id: null, note: '', created_at: '' }
const searchStub = { emits: ['select'], template: '<div />' }
beforeEach(() => {
  setActivePinia(createPinia()); vi.resetAllMocks()
  vi.mocked(api.getAccounts).mockResolvedValue({ items: [account, second] })
  vi.mocked(api.getSummary).mockResolvedValue(summary)
  vi.mocked(api.getLedger).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
  vi.mocked(api.getValuation).mockRejectedValue(new Error('缓存未覆盖'))
})
function setupPortfolio() { let store!: ReturnType<typeof usePortfolio>; const wrapper = mount(defineComponent({ setup() { store = usePortfolio(); return () => null } })); return { store, wrapper } }
describe('资产组合账本', () => {
  it('金额显示精确千分位并去冗余零，交易金额使用成交总额', () => {
    expect(decimalLabel('9007199254740993.12345678')).toBe('9,007,199,254,740,993.12345678')
    expect(decimalLabel('-1494.00000000')).toBe('-1,494')
    expect(decimalLabel(null)).toBe('未覆盖')
    const wrapper = mount(LedgerPanel, { props: { ledger: { items: [{ ...entry, kind: 'BUY', amount: '0.00000000', gross_amount: '1000.00000000' }], total: 1, page: 1, page_size: 20 }, busy: false, reverse: vi.fn() } })
    expect(wrapper.get('tbody tr').findAll('td')[3]!.text()).toContain('1,000')
    wrapper.unmount()
  })
  it('创建并选择原币账户，进入真实账本', async () => {
    vi.mocked(api.getAccounts).mockResolvedValue({ items: [] })
    vi.mocked(api.createAccount).mockResolvedValue(account)
    const wrapper = mount(PortfolioPage, { global: { stubs: { SecuritySearch: true } } }); await flushPromises()
    expect(wrapper.text()).toContain('尚未创建账户')
    await wrapper.get('[aria-label="新账户名称"]').setValue('测试人民币')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(api.createAccount).toHaveBeenCalledWith({ name: '测试人民币', currency: 'CNY' }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(api.getSummary).toHaveBeenCalledWith('a', expect.anything())
    expect(wrapper.text()).toContain('100'); wrapper.unmount()
  })
  it('入出金与独立费用保持十进制字符串，时区不依赖系统', () => {
    for (const kind of ['DEPOSIT', 'WITHDRAWAL', 'FEE'] as const) {
      const body = entryPayload({ ...newDraft(), kind, amount: '123.12345678', occurred_at: '2026-01-01T12:30', fee: '99' }, null, account, 'same')
      expect(body).toMatchObject({ kind, amount: '123.12345678', quantity: '0', price: '0', fee: '0', tax: '0', security_id: null, occurred_at: '2026-01-01T04:30:00.000Z', request_id: 'same' })
    }
  })
  it('买卖证券、币种、整数数量与分红净额均有校验', () => {
    for (const kind of ['BUY', 'SELL'] as const) expect(entryPayload({ ...newDraft(), kind, quantity: '2', price: '12.12345678', fee: '0.1', tax: '0.2' }, security, account, 'r')).toMatchObject({ amount: '0', security_id: 'security', quantity: '2', price: '12.12345678', fee: '0.1', tax: '0.2' })
    const buy = { ...newDraft(), kind: 'BUY' as const, quantity: '1.5', price: '1' }
    expect(() => entryPayload(buy, security, account, 'r')).toThrow('整数')
    expect(() => entryPayload(buy, { ...security, currency: 'USD' }, account, 'r')).toThrow('币种')
    expect(entryPayload(buy, { ...security, currency: 'USD', market: 'US' }, { ...account, currency: 'USD' }, 'r').quantity).toBe('1.5')
    expect(() => entryPayload({ ...newDraft(), kind: 'DIVIDEND', amount: '0.3', fee: '0.2', tax: '0.10000001' }, security, account, 'r')).toThrow('不能超过')
    expect(() => entryPayload({ ...newDraft(), amount: '1', occurred_at: '2026-02-30T12:00' }, null, account, 'r')).toThrow('有效北京时间')
    expect(() => entryPayload({ ...newDraft(), amount: '1' }, null, { ...account, is_active: false }, 'r')).toThrow('停用')
  })
  it('网络失败重试原表单沿用同key，编辑后才更新', async () => {
    const submit = vi.fn().mockResolvedValue(false)
    const wrapper = mount(EntryForm, { props: { account, busy: false, submit }, global: { stubs: { SecuritySearch: searchStub } } })
    await wrapper.get('[aria-label="金额"]').setValue('100')
    await wrapper.get('form').trigger('submit'); await flushPromises(); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(submit.mock.calls[0]![0]).toEqual(submit.mock.calls[1]![0])
    await wrapper.get('[aria-label="金额"]').setValue('101'); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(submit.mock.calls[2]![0].request_id).not.toBe(submit.mock.calls[0]![0].request_id); wrapper.unmount()
  })
  it('冲正必须理由和明确确认，失败保留原流水、理由与key', async () => {
    const reverse = vi.fn().mockResolvedValue(false)
    const wrapper = mount(LedgerPanel, { props: { ledger: { items: [entry], total: 1, page: 1, page_size: 20 }, busy: false, reverse } })
    await wrapper.get('button').trigger('click'); expect(wrapper.text()).toContain('不是一笔反向市场成交')
    await wrapper.get('form').trigger('submit'); expect(reverse).not.toHaveBeenCalled()
    await wrapper.get('textarea').setValue(' 原金额录错 '); await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.get('form').trigger('submit'); await flushPromises(); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(reverse.mock.calls[0]).toEqual(reverse.mock.calls[1]); expect(reverse.mock.calls[0]![1].reason).toBe('原金额录错')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe(' 原金额录错 '); wrapper.unmount()
  })
  it('换账户阻止旧摘要回填；退出清空私人数据与迟到写响应', async () => {
    const { store, wrapper } = setupPortfolio()
    let resolve!: (value: PortfolioSummary) => void
    vi.mocked(api.getSummary).mockImplementationOnce(() => new Promise(done => { resolve = done })).mockResolvedValueOnce({ ...summary, account: second, cash_balance: '200' })
    const first = store.select('a'); await store.select('b'); resolve(summary); await first
    expect(store.selected.value).toBe('b'); expect(store.summary.value?.account.id).toBe('b'); expect(store.summary.value?.cash_balance).toBe('200')
    let finish!: (value: PortfolioEntry) => void
    vi.mocked(api.createEntry).mockImplementationOnce(() => new Promise(done => { finish = done }))
    store.accounts.value = [account]
    const pending = store.enter(entryPayload({ ...newDraft(), amount: '1' }, null, account, 'r'))
    const reads = vi.mocked(api.getSummary).mock.calls.length
    useAuthStore().logout(); finish(entry); expect(await pending).toBe(false)
    expect(store.accounts.value).toEqual([]); expect(store.summary.value).toBeNull(); expect(store.selected.value).toBe('')
    expect(api.getSummary).toHaveBeenCalledTimes(reads); wrapper.unmount()
  })
  it('缺价不会显示零市值，估值故障不阻塞流水提交', async () => {
    const wrapper = mount(PositionsPanel, { props: { summary: { ...summary, positions: [{ security_id: 's', symbol: 'sh600000', name: '合成证券', currency: 'CNY', quantity: '1', total_cost: '10', average_cost: '10', realized_pnl: '0', dividend_income: '0' }] }, valuation: null, valuationError: '缓存未覆盖' } })
    expect(wrapper.text()).toContain('市值 未覆盖'); expect(wrapper.text()).not.toContain('市值 0'); wrapper.unmount()
    const context = setupPortfolio(); await context.store.select('a')
    vi.mocked(api.createEntry).mockRejectedValue(new ApiError('连接失败', 0, 'NETWORK_ERROR', 'test'))
    await context.store.enter(entryPayload({ ...newDraft(), amount: '1' }, null, account, 'r'))
    expect(api.createEntry).toHaveBeenCalledTimes(1); expect(context.store.error.value).toContain('先核对流水'); context.wrapper.unmount()
  })
})
