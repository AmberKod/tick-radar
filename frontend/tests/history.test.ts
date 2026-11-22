import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import HistoryPage from '../src/modules/market/views/HistoryPage.vue'
import HistoryChart from '../src/modules/market/components/HistoryChart.vue'
import { setAccessToken } from '../src/shared/api/client'
import type { HistoryResponse } from '../src/modules/market/types'
const chart = vi.hoisted(() => ({ remove: vi.fn(), resize: vi.fn(), fitContent: vi.fn(), setData: vi.fn(), hover: vi.fn(), disconnect: vi.fn(), observe: vi.fn() }))
const routing = vi.hoisted(() => ({ push: vi.fn() }))
const route = reactive<{ query: { symbol?: string } }>({ query: {} })
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => routing }))
vi.mock('lightweight-charts', () => ({
  CandlestickSeries: 'candlestick', HistogramSeries: 'histogram', ColorType: { Solid: 'solid' },
  createChart: () => ({ addSeries: () => ({ setData: chart.setData }), panes: () => [{ setStretchFactor: vi.fn() }, { setHeight: vi.fn(), setStretchFactor: vi.fn() }], subscribeCrosshairMove: chart.hover, timeScale: () => ({ fitContent: chart.fitContent }), remove: chart.remove, resize: chart.resize }),
}))
vi.mock('naive-ui', () => ({
  NButton: { props: ['disabled', 'attrType'], template: '<button :disabled="disabled" :type="attrType || \'button\'"><slot /></button>' },
  NInput: { props: ['value'], emits: ['update:value'], template: '<input :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  NSelect: { props: ['value', 'options'], emits: ['update:value'], template: '<select :value="value" @change="$emit(\'update:value\', typeof value === \'number\' ? Number($event.target.value) : $event.target.value)"><option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option></select>' },
  NAlert: { template: '<div><slot /></div>' },
}))
const bars = [{ date: '2026-11-20', open: '100.00100', high: '102.10000', low: '99.00000', close: '101.01000', volume: '123456.0000' }]
function history(overrides: Partial<HistoryResponse> = {}): HistoryResponse {
  return { symbol: 'US:AAPL', market: 'US', currency: 'USD', source: 'tencent_history_public', adjustment: 'raw', period: 'day', bars, requested_limit: 120, actual_count: 1, latest_date: '2026-11-20', earliest_date: '2026-11-20', checked_at: '2026-11-22T08:00:00Z', data_as_of: '2026-11-20', observation_only: true, warnings: [], history_complete: false, coverage_reason: '供应商仅返回一根历史数据', ...overrides }
}
const response = (data: HistoryResponse) => new Response(JSON.stringify(data), { status: 200 })
let resizeCallback: ResizeObserverCallback
beforeEach(() => {
  vi.clearAllMocks(); route.query = {}; setAccessToken('')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(history())))
  vi.stubGlobal('ResizeObserver', class { constructor(callback: ResizeObserverCallback) { resizeCallback = callback } observe = chart.observe; disconnect = chart.disconnect })
  routing.push.mockImplementation(async (value: { query: { symbol?: string } }) => { route.query = value.query })
})
afterEach(() => { vi.unstubAllGlobals() })
describe('公共历史日线', () => {
  it('路由代码自动请求默认参数，显示覆盖与精确读数，图表与观察器卸载清理', async () => {
    route.query = { symbol: 'US:AAPL' }
    const wrapper = mount(HistoryPage); await flushPromises()
    expect(fetch).toHaveBeenCalledWith('/api/v1/market/history?symbol=US%3AAAPL&limit=120&adjustment=raw', expect.objectContaining({ method: 'GET' }))
    const init = vi.mocked(fetch).mock.calls[0]![1]!
    expect(init.headers).not.toHaveProperty('Authorization')
    expect(wrapper.text()).toContain('供应商仅返回一根历史数据')
    expect(wrapper.text()).toContain('历史截至 2026-11-20')
    expect(wrapper.text()).toContain('100.00100')
    expect(wrapper.text()).toContain('123456.0000')
    chart.hover.mock.calls[0]![0]({ time: { year: 2026, month: 11, day: 20 } })
    await flushPromises()
    expect(wrapper.text()).toContain('101.01000')
    expect(wrapper.text()).toContain('历史数据不是实时行情')
    expect(chart.setData).toHaveBeenCalledWith([{ time: '2026-11-20', open: 100.001, high: 102.1, low: 99, close: 101.01 }])
    resizeCallback([], {} as ResizeObserver); expect(chart.resize).toHaveBeenCalled()
    wrapper.unmount(); expect(chart.remove).toHaveBeenCalledOnce(); expect(chart.disconnect).toHaveBeenCalledOnce()
  })
  it('查询提交根数和复权，示例只携带symbol路由参数', async () => {
    const wrapper = mount(HistoryPage)
    await wrapper.find('input').setValue('hk:00700')
    await wrapper.findAll('select')[0]!.setValue('250')
    await wrapper.findAll('select')[1]!.setValue('qfq')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(routing.push).toHaveBeenCalledWith({ path: '/market/history', query: { symbol: 'HK:00700' } })
    expect(fetch).toHaveBeenCalledWith('/api/v1/market/history?symbol=HK%3A00700&limit=250&adjustment=qfq', expect.anything())
    const sample = wrapper.findAll('button').find(button => button.text() === 'CN:600519')!
    await sample.trigger('click'); await flushPromises()
    expect(routing.push).toHaveBeenLastCalledWith({ path: '/market/history', query: { symbol: 'CN:600519' } })
    wrapper.unmount()
  })
  it('切换代码取消旧请求且迟到旧响应不能覆盖新图', async () => {
    let finish!: (value: Response) => void
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    route.query = { symbol: 'US:AAPL' }
    const wrapper = mount(HistoryPage); await flushPromises()
    const oldSignal = vi.mocked(fetch).mock.calls[0]![1]!.signal!
    route.query = { symbol: 'HK:00700' }; await flushPromises()
    expect(oldSignal.aborted).toBe(true)
    finish(response(history({ symbol: 'US:OLD' }))); await flushPromises()
    expect(wrapper.text()).not.toContain('US:OLD')
    expect(fetch).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
  it('新请求加载时清理旧图，明确显示复权错误且不降级', async () => {
    route.query = { symbol: 'US:AAPL' }
    const wrapper = mount(HistoryPage); await flushPromises()
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ message: '供应商不支持美股后复权', code: 'ADJUSTMENT_UNSUPPORTED' }), { status: 422 }))
    await wrapper.findAll('select')[1]!.setValue('hfq')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(chart.remove).toHaveBeenCalledOnce()
    expect(wrapper.findComponent(HistoryChart).exists()).toBe(false)
    expect(wrapper.text()).toContain('供应商不支持美股后复权')
    expect(fetch).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
  it('空数据和无效数值不绘制图表，显示原因', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response(history({ bars: [], actual_count: 0, latest_date: null, earliest_date: null })))
    route.query = { symbol: 'US:AAPL' }
    const wrapper = mount(HistoryPage); await flushPromises()
    expect(wrapper.text()).toContain('暂无可用历史日线')
    expect(wrapper.findComponent(HistoryChart).exists()).toBe(false)
    vi.mocked(fetch).mockResolvedValueOnce(response(history({ bars: [{ ...bars[0]!, close: 'Infinity' }] })))
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('历史数据格式异常')
    expect(chart.setData).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('请求切换到加载状态立即移除旧图，卸载取消正在读取的请求', async () => {
    route.query = { symbol: 'US:AAPL' }
    const wrapper = mount(HistoryPage); await flushPromises()
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(() => {}))
    route.query = { symbol: 'CN:600519' }; await flushPromises()
    expect(wrapper.text()).toContain('正在读取历史日线')
    expect(wrapper.findComponent(HistoryChart).exists()).toBe(false)
    const signal = vi.mocked(fetch).mock.calls[1]![1]!.signal!
    wrapper.unmount(); expect(signal.aborted).toBe(true)
  })
})
