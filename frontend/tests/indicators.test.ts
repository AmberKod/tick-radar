import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import HistoryPage from '../src/modules/market/views/HistoryPage.vue'
import HistoryChart from '../src/modules/market/components/HistoryChart.vue'
import type { DailyIndicatorsResponse, HistoryResponse } from '../src/modules/market/types'
const chart = vi.hoisted(() => ({ series: [] as { kind: string; pane: number; setData: ReturnType<typeof vi.fn>; applyOptions: ReturnType<typeof vi.fn> }[], removeSeries: vi.fn(), remove: vi.fn(), hover: vi.fn() }))
const route = reactive<{ query: { symbol?: string } }>({ query: {} })
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push: async (value: { query: { symbol?: string } }) => { route.query = value.query } }) }))
vi.mock('lightweight-charts', () => ({
  CandlestickSeries: 'candlestick', HistogramSeries: 'histogram', LineSeries: 'line', ColorType: { Solid: 'solid' },
  createChart: () => ({ addSeries: (kind: string, _options: unknown, pane = 0) => { const series = { kind, pane, setData: vi.fn(), applyOptions: vi.fn() }; chart.series.push(series); return series }, removeSeries: chart.removeSeries, panes: () => [{ setStretchFactor: vi.fn() }, { setHeight: vi.fn(), setStretchFactor: vi.fn() }, { setHeight: vi.fn(), setStretchFactor: vi.fn() }], subscribeCrosshairMove: chart.hover, timeScale: () => ({ fitContent: vi.fn() }), remove: chart.remove, resize: vi.fn() }),
}))
vi.mock('naive-ui', () => ({
  NButton: { props: ['disabled', 'attrType'], template: '<button :disabled="disabled" :type="attrType || \'button\'"><slot /></button>' },
  NInput: { props: ['value'], emits: ['update:value'], template: '<input :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  NSelect: { props: ['value', 'options'], emits: ['update:value'], template: '<select :value="value" @change="$emit(\'update:value\', typeof value === \'number\' ? Number($event.target.value) : $event.target.value)"><option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option></select>' },
  NAlert: { template: '<div><slot /></div>' },
}))
const bars = [{ date: '2026-11-19', open: '100', high: '102', low: '99', close: '101', volume: '10' }, { date: '2026-11-20', open: '101', high: '103', low: '100', close: '102', volume: '20' }]
const history: HistoryResponse = { symbol: 'US:AAPL', market: 'US', currency: 'USD', source: 'tencent_history_public', adjustment: 'raw', period: 'day', bars, requested_limit: 120, actual_count: 2, latest_date: '2026-11-20', earliest_date: '2026-11-19', checked_at: '2026-11-22T08:00:00Z', data_as_of: '2026-11-20', observation_only: true, warnings: [], history_complete: false, coverage_reason: '覆盖不足' }
function result(): DailyIndicatorsResponse {
  return { history, parameters: { ma_period: 10, macd_fast: 6, macd_slow: 13, macd_signal: 5, kdj_lookback: 13, kdj_k: 5, kdj_d: 5, atr_period: 14 }, algorithm_version: 'daily-v1', parameter_hash: 'hash-short', source_bars: 20, warmup_bars: 18, warmup_requested: 100, visible_bars: 2, points: [{ date: bars[0]!.date, ma: null, dif: null, dea: null, macd: null, k: null, d: null, j: null, atr: null }, { date: bars[1]!.date, ma: '101.00000', dif: '-0.012345', dea: '0.02000', macd: '-0.064690', k: '51.00000', d: '50.00000', j: '53.00000', atr: '3.00000' }], as_of: '2026-11-20', calculated_at: '2026-11-22T08:00:00Z', warnings: ['预热数据不足'], observation_only: true, formula_notes: ['MACD 柱为两倍差值'] }
}
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 200 })
beforeEach(() => {
  vi.clearAllMocks(); chart.series.length = 0; route.query = {}
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(result())))
  vi.stubGlobal('ResizeObserver', class { observe = vi.fn(); disconnect = vi.fn() })
})
afterEach(() => vi.unstubAllGlobals())
async function enable() {
  const wrapper = mount(HistoryPage)
  await wrapper.find('input[type="checkbox"]').setValue(true)
  await wrapper.find('input[aria-label="历史证券代码"]').setValue('US:AAPL')
  return wrapper
}
describe('日线指标', () => {
  it('打开K线默认计算并展示MA和MACD，关闭开关立即恢复纯历史', async () => {
    route.query = { symbol: 'US:AAPL' }
    const wrapper = mount(HistoryPage); await flushPromises()
    expect((wrapper.find('.indicator-toggle input').element as HTMLInputElement).checked).toBe(true)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(vi.mocked(fetch).mock.calls[0]![0]).toBe('/api/v1/indicators/daily')
    expect(wrapper.find('[role="tab"][aria-selected="true"]').text()).toBe('MACD')
    expect(wrapper.text()).toContain('主图：MA 10')
    expect(wrapper.find('.indicator-settings').attributes('open')).toBeUndefined()
    vi.mocked(fetch).mockResolvedValueOnce(response(history))
    await wrapper.find('.indicator-toggle input').setValue(false); await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(vi.mocked(fetch).mock.calls[1]![0]).toContain('/market/history?')
    expect(wrapper.find('.indicator-layers').exists()).toBe(false)
    wrapper.unmount()
  })
  it('开启后一次POST含参数快照，展示服务端元数据；编辑参数不自动读取', async () => {
    const wrapper = await enable()
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith('/api/v1/indicators/daily', expect.objectContaining({ method: 'POST', body: JSON.stringify({ symbol: 'US:AAPL', limit: 120, adjustment: 'raw', parameters: result().parameters }) }))
    for (const value of ['daily-v1', '实际预热 18 根 / 请求预热 100 根', '来源 20 根', 'hash-short', '预热数据不足', '不提供买卖信号', '-0.012345']) expect(wrapper.text()).toContain(value)
    await wrapper.find('input[aria-label="MA 周期"]').setValue('20')
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('实际参数：MA 10')
    wrapper.unmount()
  })
  it('640根、非整数与快慢线倒置阻止请求；标准按钮可恢复', async () => {
    const wrapper = await enable()
    await wrapper.findAll('select')[0]!.setValue('640')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('最多支持 500 根'); expect(fetch).not.toHaveBeenCalled()
    await wrapper.findAll('select')[0]!.setValue('500')
    await wrapper.find('input[aria-label="MACD 快线"]').setValue('13')
    expect(wrapper.text()).toContain('快线周期必须小于慢线周期')
    await wrapper.find('form').trigger('submit'); await flushPromises(); expect(fetch).not.toHaveBeenCalled()
    await wrapper.find('input[aria-label="MACD 快线"]').setValue('6.5')
    expect(wrapper.text()).toContain('必须为指定范围内的整数')
    await wrapper.findAll('button').find(button => button.text() === '标准参数')!.trigger('click')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0]![1]!.body as string)).toMatchObject({ limit: 500, parameters: { ma_period: 20, macd_fast: 12, macd_slow: 26, macd_signal: 9, kdj_lookback: 9, kdj_k: 3, kdj_d: 3 } })
    wrapper.unmount()
  })
  it('关闭回到历史GET并取消旧指标请求，迟到响应不覆盖', async () => {
    let finish!: (value: Response) => void
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await enable(); await wrapper.find('form').trigger('submit'); await flushPromises()
    const signal = vi.mocked(fetch).mock.calls[0]![1]!.signal!
    vi.mocked(fetch).mockResolvedValueOnce(response(history))
    await wrapper.find('input[type="checkbox"]').setValue(false)
    await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(vi.mocked(fetch).mock.calls[1]![0]).toContain('/market/history?')
    finish(response(result())); await flushPromises()
    expect(wrapper.text()).not.toContain('daily-v1')
    wrapper.unmount()
  })
  it.each(['date', 'identity', 'infinity'])('拒绝错误指标响应：%s', async kind => {
    const data = result()
    if (kind === 'date') data.points[0]!.date = '2026-11-18'
    if (kind === 'identity') data.history = { ...history, adjustment: 'qfq' }
    if (kind === 'infinity') data.points[0]!.ma = 'Infinity'
    vi.mocked(fetch).mockResolvedValueOnce(response(data))
    const wrapper = await enable(); await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(wrapper.findComponent(HistoryChart).exists()).toBe(false)
    expect(wrapper.text()).toMatch(/不匹配|格式异常/)
    wrapper.unmount()
  })
  it('主图MA、成交量和副图独立；空值保留whitespace，三指标可切换并读取精确字符串', async () => {
    const data = result(), wrapper = mount(HistoryChart, { props: { bars, points: data.points, parameters: data.parameters } })
    const ma = chart.series.find(series => series.kind === 'line' && series.pane === 0)!
    expect(ma.setData).toHaveBeenCalledWith([{ time: '2026-11-19' }, { time: '2026-11-20', value: 101 }])
    expect(chart.series.filter(series => series.pane === 1)).toHaveLength(1)
    expect(chart.series.filter(series => series.pane === 2)).toHaveLength(3)
    expect(chart.series.find(series => series.pane === 2 && series.kind === 'histogram')!.setData).toHaveBeenCalledWith([{ time: '2026-11-19' }, { time: '2026-11-20', value: -0.06469, color: '#16804a' }])
    chart.hover.mock.calls[0]![0]({ time: '2026-11-19' }); await flushPromises()
    expect(wrapper.text()).toContain('预热不足')
    chart.hover.mock.calls[0]![0]({ time: '2026-11-20' }); await flushPromises()
    expect(wrapper.text()).toContain('-0.012345')
    await wrapper.findAll('[role="tab"]')[1]!.trigger('click'); expect(wrapper.text()).toContain('J 53.00000')
    await wrapper.findAll('[role="tab"]')[2]!.trigger('click'); expect(wrapper.text()).toContain('ATR 3.00000')
    expect(chart.removeSeries).toHaveBeenCalledTimes(6)
    await wrapper.find('input[type="checkbox"]').setValue(false); expect(ma.applyOptions).toHaveBeenCalledWith({ visible: false })
    wrapper.unmount(); expect(chart.remove).toHaveBeenCalledOnce()
  })
})
