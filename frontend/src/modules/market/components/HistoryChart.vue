<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CandlestickSeries, ColorType, HistogramSeries, LineSeries, createChart, type IChartApi, type ISeriesApi, type Time } from 'lightweight-charts'
import type { HistoryBar, IndicatorParameters, IndicatorPoint, MinuteBar, MinuteIndicatorPoint } from '../types'
type Bar = HistoryBar | MinuteBar
type Point = IndicatorPoint | MinuteIndicatorPoint
const props = withDefaults(defineProps<{ bars: Bar[]; points?: Point[]; parameters?: IndicatorParameters; period?: 'day' | 'm15' }>(), { period: 'day', points: undefined, parameters: undefined })
function chartKey(value: Bar | Point): Time { return 'timestamp' in value ? Math.floor(Date.parse(value.timestamp) / 1000) as Time : value.date as Time }
function shanghaiTime(value: number) {
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(value * 1000))
  const get = (key: string) => parts.find(part => part.type === key)?.value
  return `${get('year')}/${get('month')}/${get('day')} ${get('hour')}:${get('minute')} GMT+8`
}
function displayTime(value: Bar) { return 'timestamp' in value ? shanghaiTime(Number(chartKey(value))) : value.date }
const container = ref<HTMLDivElement>()
const selected = ref<Bar | null>(props.bars.at(-1) || null)
const selectedPoint = computed(() => props.points?.find(point => selected.value && chartKey(point) === chartKey(selected.value)))
const showMa = ref(true), showRawVolume = ref(false), active = ref<'macd' | 'kdj' | 'atr'>('macd')
const indicatorKeys = computed(() => active.value === 'macd' ? ['dif', 'dea', 'macd'] as const : active.value === 'kdj' ? ['k', 'd', 'j'] as const : ['atr'] as const)
let chart: IChartApi | undefined
let observer: ResizeObserver | undefined
let ma: ISeriesApi<'Line'> | undefined
let indicatorSeries: ISeriesApi<'Line' | 'Histogram'>[] = []
const height = props.points ? 560 : 480
function groupDigits(value: string) { return value.replace(/\B(?=(\d{3})+(?!\d))/g, ',') }
function volumeParts(value: string | number) {
  const text = typeof value === 'number' ? value.toLocaleString('en-US', { useGrouping: false, maximumFractionDigits: 20 }) : value
  const match = text.match(/^(-?)(\d+)(?:\.(\d+))?$/)
  if (!match) return null
  return { sign: match[1]!, whole: match[2]!.replace(/^0+(?=\d)/, ''), fraction: (match[3] || '').replace(/0+$/, '') }
}
function fullVolume(value: string) {
  const parts = volumeParts(value)
  return parts ? `${parts.sign}${groupDigits(parts.whole)}${parts.fraction ? `.${parts.fraction}` : ''}` : '—'
}
function compactVolume(value: string | number) {
  const parts = volumeParts(value)
  if (!parts) return '—'
  let shift = parts.whole.length >= 9 ? 8 : parts.whole.length >= 5 ? 4 : 0
  if (!shift) return `${parts.sign}${groupDigits(parts.whole)}${parts.fraction ? `.${parts.fraction}` : ''}`
  // 从源端十进制字符串精确缩放，显示舍入不影响原始成交量。
  const digits = BigInt(parts.whole + parts.fraction)
  const rounded = (power: number) => { const denominator = 10n ** BigInt(parts.fraction.length + power); return (digits * 100n + denominator / 2n) / denominator }
  let result = rounded(shift)
  if (shift === 4 && result >= 1_000_000n) { shift = 8; result = rounded(shift) }
  const decimal = String(result % 100n).padStart(2, '0').replace(/0+$/, '')
  return `${parts.sign}${groupDigits(String(result / 100n))}${decimal ? `.${decimal}` : ''} ${shift === 8 ? '亿' : '万'}`
}
function sizePanes() {
  const factors = props.points ? [6, 2, 3] : [4, 1]
  chart?.panes().forEach((pane, index) => pane.setStretchFactor(factors[index] || 1))
}
function renderIndicator() {
  if (!chart || !props.points) return
  for (const series of indicatorSeries) chart.removeSeries(series)
  indicatorSeries = []
  const add = (key: keyof Omit<IndicatorPoint, 'date'>, color: string, histogram = false) => {
    const series = histogram ? chart!.addSeries(HistogramSeries, {}, 2) : chart!.addSeries(LineSeries, { color, lineWidth: 2 }, 2)
    series.setData(props.points!.map(point => point[key] === null ? { time: chartKey(point) } : { time: chartKey(point), value: Number(point[key]), ...(histogram ? { color: Number(point[key]) >= 0 ? '#d03050' : '#16804a' } : {}) }))
    indicatorSeries.push(series)
  }
  if (active.value === 'macd') { add('macd', '#d03050', true); add('dif', '#2563eb'); add('dea', '#d97706') }
  else if (active.value === 'kdj') { add('k', '#2563eb'); add('d', '#d97706'); add('j', '#9333ea') }
  else add('atr', '#9333ea')
  sizePanes()
}
watch(active, renderIndicator)
watch(showMa, value => ma?.applyOptions({ visible: value }))
onMounted(() => {
  if (!container.value) return
  chart = createChart(container.value, {
    height, width: container.value.clientWidth,
    layout: { background: { type: ColorType.Solid, color: '#ffffff' }, textColor: '#273449', attributionLogo: true },
    grid: { vertLines: { color: '#edf1f5' }, horzLines: { color: '#edf1f5' } },
    timeScale: { timeVisible: props.period === 'm15', borderColor: '#dce3eb', ...(props.period === 'm15' ? { tickMarkFormatter: (time: Time) => typeof time === 'number' ? shanghaiTime(time).replace(' GMT+8', '') : String(time) } : {}) },
    ...(props.period === 'm15' ? { localization: { timeFormatter: (time: Time) => typeof time === 'number' ? shanghaiTime(time) : String(time) } } : {}),
  })
  const candles = chart.addSeries(CandlestickSeries, { upColor: '#d03050', downColor: '#16804a', wickUpColor: '#d03050', wickDownColor: '#16804a', borderVisible: false })
  const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'custom', minMove: 1, formatter: compactVolume } }, 1)
  candles.setData(props.bars.map(bar => ({ time: chartKey(bar), open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close) })))
  volume.setData(props.bars.map(bar => ({ time: chartKey(bar), value: Number(bar.volume), color: Number(bar.close) >= Number(bar.open) ? '#d03050' : '#16804a' })))
  chart.panes()[1]?.setHeight(100)
  if (props.points) {
    ma = chart.addSeries(LineSeries, { color: '#d97706', lineWidth: 2 }, 0)
    ma.setData(props.points.map(point => point.ma === null ? { time: chartKey(point) } : { time: chartKey(point), value: Number(point.ma) }))
    renderIndicator()
  }
  const byDate = new Map(props.bars.map(bar => [chartKey(bar), bar]))
  chart.subscribeCrosshairMove(event => {
    const time = event.time
    const date = typeof time === 'string' || typeof time === 'number' ? time : typeof time === 'object' ? `${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}` : ''
    selected.value = byDate.get(date) || props.bars.at(-1) || null
  })
  sizePanes()
  chart.timeScale().fitContent()
  observer = new ResizeObserver(() => { if (container.value) chart?.resize(container.value.clientWidth, height) })
  observer.observe(container.value)
})
onBeforeUnmount(() => { observer?.disconnect(); chart?.remove(); chart = undefined })
function fit() { chart?.timeScale().fitContent() }
</script>
<template>
  <div class="history-chart">
    <p v-if="points" class="indicator-legend">主图：MA {{ parameters?.ma_period }} · 成交量 · 副图：{{ active.toUpperCase() }}</p>
    <div v-if="points" class="indicator-layers"><label><input v-model="showMa" type="checkbox" /> MA {{ parameters?.ma_period }}</label><div role="tablist" :aria-label="period === 'm15' ? '15分钟指标图层' : '日线指标图层'"><button v-for="tab in (['macd', 'kdj', 'atr'] as const)" :key="tab" type="button" role="tab" :aria-selected="active === tab" @click="active = tab">{{ tab.toUpperCase() }}</button></div></div>
    <div v-if="selected" class="history-readout" aria-live="polite"><strong>{{ displayTime(selected) }}</strong><span>开 {{ selected.open }}</span><span>高 {{ selected.high }}</span><span>低 {{ selected.low }}</span><span>收 {{ selected.close }}</span><span class="volume-readout" :title="`完整数值：${fullVolume(selected.volume)}；源端原值：${selected.volume}`">成交量 {{ showRawVolume ? fullVolume(selected.volume) : compactVolume(selected.volume) }}</span><button type="button" class="volume-format" :aria-pressed="showRawVolume" @click="showRawVolume = !showRawVolume">{{ showRawVolume ? '简写显示' : '完整数值' }}</button></div>
    <div v-if="selectedPoint" class="indicator-readout" aria-live="polite"><span v-if="showMa">MA {{ selectedPoint.ma ?? '预热不足' }}</span><span v-for="key in indicatorKeys" :key="key">{{ key.toUpperCase() }} {{ selectedPoint[key] ?? '预热不足' }}</span></div>
    <div ref="container" class="chart-canvas" :style="{ height: `${height}px` }" :aria-label="period === 'm15' ? '历史15分钟与原始成交量图' : '历史日线与原始成交量图'" />
    <div class="chart-caption"><span>红涨绿跌 · 支持缩放、拖拽与悬停读数 · 成交量以万/亿简写，可切完整数值；源端单位保持不变，未经确认</span><button type="button" @click="fit">适应全部数据</button></div>
    <p class="chart-notice"><a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">TradingView</a> · TradingView Lightweight Charts™ Copyright (с) 2025 TradingView, Inc. https://www.tradingview.com/</p>
  </div>
</template>
<style scoped>
.history-chart { background: #fff; color: #273449; min-width: 0; }
.history-readout, .indicator-readout, .indicator-layers, .chart-caption { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; padding: 8px 0; font-variant-numeric: tabular-nums; }
.indicator-layers [role='tablist'] { display: flex; gap: 6px; }
.chart-canvas { width: 100%; }
.chart-caption, .chart-notice, .indicator-legend { font-size: 12px; color: #596579; }
.indicator-legend { margin: 14px 0 0; }
.chart-notice { overflow-wrap: anywhere; }
button { cursor: pointer; padding: 6px 10px; background: #f4f7fb; border: 1px solid #dce3eb; border-radius: 6px; color: #273449; }
button[aria-selected='true'] { background: #dbeafe; border-color: #2563eb; }
</style>
