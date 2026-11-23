import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../src/modules/auth'
import { useTransfers } from '../src/modules/portfolio/composables/useTransfers'
import { actualRate, newTransferDraft, rateLabel, sourceTotal, transferPayload } from '../src/modules/portfolio/composables/transferDraft'
import TransferForm from '../src/modules/portfolio/components/TransferForm.vue'
import TransferHistory from '../src/modules/portfolio/components/TransferHistory.vue'
import * as api from '../src/modules/portfolio/api/transfers'
import type { PortfolioAccount } from '../src/modules/portfolio/types'
import type { PortfolioTransfer, PortfolioTransferPage } from '../src/modules/portfolio/types/transfers'
vi.mock('../src/modules/portfolio/api/transfers', () => ({ getTransfers: vi.fn(), createTransfer: vi.fn(), reverseTransfer: vi.fn() }))
const source: PortfolioAccount = { id: 'a', name: '源账户', currency: 'CNY', is_active: true, created_at: '', updated_at: '' }
const target: PortfolioAccount = { ...source, id: 'b', name: '目标账户', currency: 'USD' }
const item: PortfolioTransfer = { id: 't', request_id: 'r', source_account_id: 'a', target_account_id: 'b', source_account_name: '源账户', target_account_name: '目标账户', source_currency: 'CNY', target_currency: 'USD', source_amount: '7', target_amount: '1', source_fee: '0.1', implied_rate: '0.142857142857', rate_basis: 'ACTUAL_AMOUNTS', occurred_at: '2026-01-01T00:00:00Z', status: 'ACTIVE', note: '', source_entry_id: 's', target_entry_id: 'd', source_reversal_entry_id: null, target_reversal_entry_id: null, reversal_reason: null, reversed_at: null, created_at: '2026-01-01T00:00:00Z' }
const page: PortfolioTransferPage = { items: [item], total: 1, page: 1, page_size: 20 }
const draft = () => ({ ...newTransferDraft('a'), target_account_id: 'b', source_amount: '7', target_amount: '1', occurred_at: '2026-01-01T08:00' })
beforeEach(() => { setActivePinia(createPinia()); vi.resetAllMocks(); vi.mocked(api.getTransfers).mockResolvedValue(page) })
function setup() { let store!: ReturnType<typeof useTransfers>; const changed = vi.fn(); const wrapper = mount(defineComponent({ setup() { store = useTransfers(changed); return () => null } })); return { store, changed, wrapper } }
describe('内部划转与换汇', () => {
  it('按实际金额生成同币种和跨币种字符串载荷，复用北京时间有效性校验', () => {
    expect(transferPayload(draft(), [source, target], 'r')).toMatchObject({ source_amount: '7', target_amount: '1', source_fee: '0', occurred_at: '2026-01-01T00:00:00.000Z' })
    expect(transferPayload(draft(), [source, { ...target, currency: 'CNY' }], 'r').target_amount).toBe('7')
    expect(() => transferPayload({ ...draft(), target_account_id: 'a' }, [source, target], 'r')).toThrow('不能相同')
    expect(() => transferPayload(draft(), [source, { ...target, is_active: false }], 'r')).toThrow('启用')
    expect(() => transferPayload({ ...draft(), occurred_at: '2026-02-30T00:00' }, [source, target], 'r')).toThrow('有效北京时间')
  })
  it('大金额与极小手续费精确相加，实际汇率使用12位半偶舍入', () => {
    expect(sourceTotal('9007199254740993.12345678', '0.00000001')).toBe('9007199254740993.12345679')
    expect(actualRate('8192', '1')).toBe('0.000122070312')
    expect(actualRate('8192', '3')).toBe('0.000366210938')
    expect(() => sourceTotal('1e2', '0')).toThrow('十进制')
    expect(rateLabel(actualRate('9007199254740993', '12.34'))).toContain('小于显示精度')
  })
  it('默认目标为空，显式确认后提交；失败保留草稿和UUID，修改金额重置确认', async () => {
    const submit = vi.fn().mockResolvedValue(false)
    const wrapper = mount(TransferForm, { props: { accounts: [source, target], selected: 'a', busy: false, submit } })
    expect((wrapper.get('[aria-label="划入账户"]').element as HTMLSelectElement).value).toBe('')
    await wrapper.get('[aria-label="划入账户"]').setValue('b'); await wrapper.get('[aria-label="划出金额"]').setValue('7'); await wrapper.get('[aria-label="实际到账金额"]').setValue('1')
    await wrapper.get('form').trigger('submit'); expect(submit).not.toHaveBeenCalled()
    await wrapper.get('[aria-label="确认划转"]').setValue(true)
    await wrapper.get('form').trigger('submit'); await flushPromises(); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(submit.mock.calls[0]![0]).toEqual(submit.mock.calls[1]![0]); expect((wrapper.get('[aria-label="划出金额"]').element as HTMLInputElement).value).toBe('7')
    await wrapper.get('[aria-label="划出金额"]').setValue('8'); expect((wrapper.get('[aria-label="确认划转"]').element as HTMLInputElement).checked).toBe(false)
    await wrapper.get('[aria-label="确认划转"]').setValue(true); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(submit.mock.calls[2]![0].request_id).not.toBe(submit.mock.calls[0]![0].request_id); wrapper.unmount()
  })
  it('整体作废要求原因和确认，服务拒绝后保留原因与请求编号', async () => {
    const reverse = vi.fn().mockResolvedValue(false)
    const wrapper = mount(TransferHistory, { props: { ledger: page, accounts: [source, target], filter: 'a', busy: false, reverse } })
    await wrapper.get('tbody button').trigger('click'); await wrapper.get('form').trigger('submit'); expect(reverse).not.toHaveBeenCalled()
    await wrapper.get('textarea').setValue('金额录错'); await wrapper.get('[aria-label="确认整体作废"]').setValue(true)
    await wrapper.get('form').trigger('submit'); await flushPromises(); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(reverse.mock.calls[0]).toEqual(reverse.mock.calls[1]); expect(wrapper.text()).toContain('服务端会拒绝')
    await wrapper.get('textarea').setValue('账户录错'); await wrapper.get('[aria-label="确认整体作废"]').setValue(true); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(reverse.mock.calls[2]![1].request_id).not.toBe(reverse.mock.calls[0]![1].request_id); wrapper.unmount()
  })
  it('筛选迟到读取不回填，退出后的迟到写入不触发刷新，写入不重入', async () => {
    const { store, wrapper, changed } = setup()
    let finishRead!: (value: PortfolioTransferPage) => void
    vi.mocked(api.getTransfers).mockImplementationOnce(() => new Promise(done => { finishRead = done })).mockResolvedValueOnce({ ...page, items: [] })
    const read = store.select('a'); await store.select('b'); finishRead(page); await read; expect(store.ledger.value?.items).toEqual([])
    let finishWrite!: (value: PortfolioTransfer) => void
    vi.mocked(api.createTransfer).mockImplementationOnce(() => new Promise(done => { finishWrite = done }))
    const write = store.create(transferPayload(draft(), [source, target], 'r')); expect(await store.create(transferPayload(draft(), [source, target], 'r'))).toBe(false)
    useAuthStore().logout(); finishWrite(item); expect(await write).toBe(false); expect(changed).not.toHaveBeenCalled(); expect(store.ledger.value).toBeNull(); expect(api.createTransfer).toHaveBeenCalledTimes(1); wrapper.unmount()
  })
  it('卸载后迟到响应不更新页面，错误不自动重试', async () => {
    const { store, wrapper, changed } = setup()
    vi.mocked(api.reverseTransfer).mockRejectedValueOnce(new Error('目标资金已占用'))
    expect(await store.reverse('t', { request_id: 'r', reason: '录错' })).toBe(false); expect(store.error.value).toContain('目标资金已占用'); expect(api.reverseTransfer).toHaveBeenCalledTimes(1)
    let finish!: (value: PortfolioTransfer) => void
    vi.mocked(api.createTransfer).mockImplementationOnce(() => new Promise(done => { finish = done }))
    const pending = store.create(transferPayload(draft(), [source, target], 'r')); wrapper.unmount(); finish(item); expect(await pending).toBe(false); expect(changed).not.toHaveBeenCalled()
  })
})
