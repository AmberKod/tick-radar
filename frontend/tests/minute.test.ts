import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import HistoryPage from '../src/modules/market/views/HistoryPage.vue'
import HistoryChart from '../src/modules/market/components/HistoryChart.vue'
import type { MinuteHistoryResponse, MinuteIndicatorsResponse } from '../src/modules/market/types'
const chart = vi.hoisted(() => ({ series: [] as { kind: string; pane: number; setData: ReturnType<typeof vi.fn>; applyOptions: ReturnType<typeof vi.fn> }[], options: vi.fn(), hover: vi.fn(), remove: vi.fn() }))
const route = reactive<{ query: Record<string, string> }>({ query: {} })
const push = vi.fn(async (value: { query: Record<string, string> }) => { route.query = value.query })
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push }) }))
vi.mock('lightweight-charts', () => ({
  CandlestickSeries: 'candlestick', HistogramSeries: 'histogram', LineSeries: 'line', ColorType: { Solid: 'solid' },
  createChart: (_element: unknown, options: unknown) => { chart.options(options); return { addSeries: (kind: string, _options: unknown, pane = 0) => { const series = { kind, pane, setData: vi.fn(), applyOptions: vi.fn() }; chart.series.push(series); return series }, removeSeries: vi.fn(), panes: () => [0, 1, 2].map(() => ({ setStretchFactor: vi.fn(), setHeight: vi.fn() })), subscribeCrosshairMove: chart.hover, timeScale: () => ({ fitContent: vi.fn() }), remove: chart.remove, resize: vi.fn() } },
}))
vi.mock('naive-ui', () => ({
  NButton: { props: ['disabled', 'attrType'], template: '<button :disabled="disabled" :type="attrType || \'button\'"><slot /></button>' },
  NInput: { props: ['value'], emits: ['update:value'], template: '<input :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  NSelect: { props: ['value', 'options', 'disabled'], emits: ['update:value'], template: '<select :value="value" :disabled="disabled" @change="$emit(\'update:value\', typeof value === \'number\' ? Number($event.target.value) : $event.target.value)"><option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option></select>' },
  NAlert: { template: '<div><slot /></div>' },
}))
const timestamps = ['2026-11-20T01:45:00Z', '2026-11-20T02:00:00Z']
function history(): MinuteHistoryResponse {
  return { symbol: 'CN:600519', market: 'CN', currency: 'CNY', source: 'tencent_minute_public', period: 'm15', adjustment: 'vendor_unverified', timezone: 'Asia/Shanghai', timestamp_semantics: 'VENDOR_BAR_LABEL_UNVERIFIED', bars: timestamps.map((timestamp, index) => ({ timestamp, source_time_raw: index ? '202611201000' : '202611200945', open: '100', high: '103', low: '99', close: index ? '102.000' : '101.000', volume: '123456.000' })), requested_limit: 120, actual_count: 2, earliest_timestamp: timestamps[0]!, latest_timestamp: timestamps[1]!, checked_at: '2026-11-22T08:00:00Z', data_as_of: timestamps[1]!, observation_only: true, history_complete: false, coverage_reason: '分钟覆盖不足', warnings: ['时间标签含义未经确认'] }
}
function result(): MinuteIndicatorsResponse {
  return { history: history(), parameters: { ma_period: 10, macd_fast: 6, macd_slow: 13, macd_signal: 5, kdj_lookback: 13, kdj_k: 5, kdj_d: 5, atr_period: 14 }, algorithm_version: 'm15-v1', parameter_hash: 'minute-hash', source_bars: 20, warmup_bars: 18, warmup_requested: 100, visible_bars: 2, points: timestamps.map((timestamp, index) => ({ timestamp, ma: index ? '101.000' : null, dif: index ? '-0.1' : null, dea: index ? '0.2' : null, macd: index ? '-0.6' : null, k: index ? '51' : null, d: index ? '50' : null, j: index ? '53' : null, atr: index ? '3' : null })), as_of: timestamps[1]!, calculated_at: '2026-11-22T08:00:00Z', warnings: ['预热不足'], observation_only: true, formula_notes: ['同周期计算'] }
}
const response = (data: unknown) => new Response(JSON.stringify(data), { status: 200 })
beforeEach(() => { vi.clearAllMocks(); chart.series.length = 0; route.query = { symbol: 'CN:600519', period: 'm15' }; vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(result()))); vi.stubGlobal('ResizeObserver', class { observe = vi.fn(); disconnect = vi.fn() }) })
afterEach(() => vi.unstubAllGlobals())
describe('15分钟历史和指标', () => {
  it('默认一次POST，不发送日线复权，元数据和预热提示可见；关闭只GET一次', async () => {
    const wrapper = mount(HistoryPage); await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith('/api/v1/indicators/minute', expect.objectContaining({ method: 'POST', body: JSON.stringify({ symbol: 'CN:600519', limit: 120, parameters: result().parameters }) }))
    expect(wrapper.text()).toContain('15分钟指标')
    expect(wrapper.text()).toContain('预热不足')
    expect(wrapper.text()).toContain('GMT+8')
    expect(wrapper.find('select[aria-label="复权方式"]').attributes('disabled')).toBeDefined()
    vi.mocked(fetch).mockResolvedValueOnce(response(history()))
    await wrapper.find('.indicator-toggle input').setValue(false); await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(vi.mocked(fetch).mock.calls[1]![0]).toBe('/api/v1/market/history/minute?symbol=CN%3A600519&limit=120')
    await wrapper.findAll('button').find(button => button.text() === 'CN:000001')!.trigger('click'); await flushPromises()
    expect(push).toHaveBeenLastCalledWith({ path: '/market/history', query: { symbol: 'CN:000001', period: 'm15', indicators: 'off' } })
    wrapper.unmount()
  })
  it('所有序列使用UTC秒且同日多bar不合并，上海时间tooltip与精确指标对应', async () => {
    const data = result(), wrapper = mount(HistoryChart, { props: { bars: data.history.bars, points: data.points, period: 'm15', parameters: data.parameters } })
    const keys = timestamps.map(value => Math.floor(Date.parse(value) / 1000))
    for (const series of chart.series) expect(series.setData.mock.calls[0]![0].map((point: { time: number }) => point.time)).toEqual(keys)
    const ma = chart.series.find(series => series.kind === 'line' && series.pane === 0)!
    expect(ma.setData).toHaveBeenCalledWith([{ time: keys[0] }, { time: keys[1], value: 101 }])
    expect(chart.series.find(series => series.kind === 'histogram' && series.pane === 2)!.setData).toHaveBeenCalledWith([{ time: keys[0] }, { time: keys[1], value: -0.6, color: '#16804a' }])
    const options = chart.options.mock.calls[0]![0]
    expect(options.timeScale.timeVisible).toBe(true)
    expect(options.localization.timeFormatter(keys[0])).toBe('2026/11/20 09:45 GMT+8')
    expect(options.timeScale.tickMarkFormatter(keys[1])).toContain('10:00')
    chart.hover.mock.calls[0]![0]({ time: keys[0] }); await flushPromises()
    expect(wrapper.text()).toContain('2026/11/20 09:45 GMT+8'); expect(wrapper.text()).toContain('收 101.000'); expect(wrapper.text()).toContain('预热不足')
    chart.hover.mock.calls[0]![0]({ time: keys[1] }); await flushPromises()
    expect(wrapper.text()).toContain('2026/11/20 10:00 GMT+8'); expect(wrapper.text()).toContain('收 102.000'); expect(wrapper.text()).toContain('DIF -0.1')
    await wrapper.findAll('[role="tab"]')[1]!.trigger('click'); expect(wrapper.text()).toContain('J 53')
    await wrapper.findAll('[role="tab"]')[2]!.trigger('click'); expect(wrapper.text()).toContain('ATR 3')
    wrapper.unmount(); expect(chart.remove).toHaveBeenCalledOnce()
  })
  it('320根指标和切周期超限显式报错，不静默改根数', async () => {
    const wrapper = mount(HistoryPage); await flushPromises()
    await wrapper.find('select[aria-label="历史根数"]').setValue('320'); await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('最多支持 250 根'); expect(fetch).toHaveBeenCalledTimes(1)
    vi.mocked(fetch).mockResolvedValueOnce(response(history()))
    await wrapper.find('.indicator-toggle input').setValue(false); await flushPromises()
    expect(vi.mocked(fetch).mock.calls[1]![0]).toContain('limit=320')
    await wrapper.find('select[aria-label="周期"]').setValue('day'); await flushPromises()
    await wrapper.find('select[aria-label="历史根数"]').setValue('640')
    const count = vi.mocked(fetch).mock.calls.length
    await wrapper.find('select[aria-label="周期"]').setValue('m15'); await flushPromises()
    expect(wrapper.text()).toContain('最多支持 320 根'); expect(fetch).toHaveBeenCalledTimes(count)
    wrapper.unmount()
  })
  it.each(['HK:00700', 'US:AAPL', 'CN:920001'])('不支持%s时清旧图，显示中文范围且无降级请求', async symbol => {
    const wrapper = mount(HistoryPage); await flushPromises(); expect(wrapper.findComponent(HistoryChart).exists()).toBe(true)
    route.query = { symbol, period: 'm15' }; await flushPromises()
    expect(wrapper.text()).toContain('仅支持沪深证券'); expect(wrapper.text()).toContain('MINUTE_MARKET_UNSUPPORTED')
    expect(wrapper.findComponent(HistoryChart).exists()).toBe(false); expect(fetch).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('切回日线中止分钟请求，迟到分钟响应不覆盖日线状态', async () => {
    let finish!: (value: Response) => void
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = mount(HistoryPage); await flushPromises()
    const signal = vi.mocked(fetch).mock.calls[0]![1]!.signal!
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ code: 'DAILY_TEST', message: '日线响应' }), { status: 422 }))
    await wrapper.find('select[aria-label="周期"]').setValue('day'); await flushPromises()
    expect(signal.aborted).toBe(true); expect(fetch).toHaveBeenCalledTimes(2)
    expect(vi.mocked(fetch).mock.calls[1]![0]).toBe('/api/v1/indicators/daily')
    finish(response(result())); await flushPromises()
    expect(wrapper.text()).toContain('日线响应'); expect(wrapper.text()).not.toContain('m15-v1'); expect(wrapper.findComponent(HistoryChart).exists()).toBe(false)
    wrapper.unmount()
  })
  it.each(['timestamp', 'alignment', 'numeric'])('拒绝异常分钟响应：%s', async kind => {
    const data = result()
    if (kind === 'timestamp') data.history.bars[0]!.timestamp = '2026-11-20T01:45:00'
    if (kind === 'alignment') data.points[0]!.timestamp = '2026-11-20T01:30:00Z'
    if (kind === 'numeric') data.points[0]!.ma = 'Infinity'
    vi.mocked(fetch).mockResolvedValueOnce(response(data))
    const wrapper = mount(HistoryPage); await flushPromises()
    expect(wrapper.text()).toContain('格式异常'); expect(wrapper.findComponent(HistoryChart).exists()).toBe(false)
    wrapper.unmount()
  })
  it('15秒超时中止分钟请求，显示可重试错误', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(fetch).mockImplementationOnce((_url, options) => new Promise((_resolve, reject) => options!.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))))
      const wrapper = mount(HistoryPage); await flushPromises()
      const signal = vi.mocked(fetch).mock.calls[0]![1]!.signal!
      await vi.advanceTimersByTimeAsync(15_000); await flushPromises()
      expect(signal.aborted).toBe(true); expect(wrapper.text()).toContain('请求超时'); expect(wrapper.text()).toContain('TIMEOUT')
      wrapper.unmount()
    } finally { vi.useRealTimers() }
  })
  it('服务端分钟错误保持中文与代码，清除旧图且不降级', async () => {
    const wrapper = mount(HistoryPage); await flushPromises()
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ code: 'MINUTE_SOURCE_UNAVAILABLE', message: '分钟数据暂不可用' }), { status: 503 }))
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('分钟数据暂不可用'); expect(wrapper.text()).toContain('MINUTE_SOURCE_UNAVAILABLE')
    expect(wrapper.findComponent(HistoryChart).exists()).toBe(false); expect(fetch).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})
