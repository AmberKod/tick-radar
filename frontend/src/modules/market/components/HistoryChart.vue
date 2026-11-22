<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CandlestickSeries, ColorType, HistogramSeries, LineSeries, createChart, type IChartApi, type ISeriesApi, type Time } from 'lightweight-charts'
import type { HistoryBar, IndicatorParameters, IndicatorPoint } from '../types'
const props = defineProps<{ bars: HistoryBar[]; points?: IndicatorPoint[]; parameters?: IndicatorParameters }>()
const container = ref<HTMLDivElement>()
const selected = ref<HistoryBar | null>(props.bars.at(-1) || null)
const selectedPoint = computed(() => props.points?.find(point => point.date === selected.value?.date))
const showMa = ref(true), active = ref<'macd' | 'kdj' | 'atr'>('macd')
const indicatorKeys = computed(() => active.value === 'macd' ? ['dif', 'dea', 'macd'] as const : active.value === 'kdj' ? ['k', 'd', 'j'] as const : ['atr'] as const)
let chart: IChartApi | undefined
let observer: ResizeObserver | undefined
let ma: ISeriesApi<'Line'> | undefined
let indicatorSeries: ISeriesApi<'Line' | 'Histogram'>[] = []
const height = props.points ? 560 : 480
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
    series.setData(props.points!.map(point => point[key] === null ? { time: point.date as Time } : { time: point.date as Time, value: Number(point[key]), ...(histogram ? { color: Number(point[key]) >= 0 ? '#d03050' : '#16804a' } : {}) }))
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
    timeScale: { timeVisible: false, borderColor: '#dce3eb' },
  })
  const candles = chart.addSeries(CandlestickSeries, { upColor: '#d03050', downColor: '#16804a', wickUpColor: '#d03050', wickDownColor: '#16804a', borderVisible: false })
  const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' } }, 1)
  candles.setData(props.bars.map(bar => ({ time: bar.date as Time, open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close) })))
  volume.setData(props.bars.map(bar => ({ time: bar.date as Time, value: Number(bar.volume), color: Number(bar.close) >= Number(bar.open) ? '#d03050' : '#16804a' })))
  chart.panes()[1]?.setHeight(100)
  if (props.points) {
    ma = chart.addSeries(LineSeries, { color: '#d97706', lineWidth: 2 }, 0)
    ma.setData(props.points.map(point => point.ma === null ? { time: point.date as Time } : { time: point.date as Time, value: Number(point.ma) }))
    renderIndicator()
  }
  const byDate = new Map(props.bars.map(bar => [bar.date, bar]))
  chart.subscribeCrosshairMove(event => {
    const time = event.time
    const date = typeof time === 'string' ? time : typeof time === 'object' ? `${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}` : ''
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
    <div v-if="points" class="indicator-layers"><label><input v-model="showMa" type="checkbox" /> MA {{ parameters?.ma_period }}</label><div role="tablist" aria-label="日线指标图层"><button v-for="tab in (['macd', 'kdj', 'atr'] as const)" :key="tab" type="button" role="tab" :aria-selected="active === tab" @click="active = tab">{{ tab.toUpperCase() }}</button></div></div>
    <div v-if="selected" class="history-readout" aria-live="polite"><strong>{{ selected.date }}</strong><span>开 {{ selected.open }}</span><span>高 {{ selected.high }}</span><span>低 {{ selected.low }}</span><span>收 {{ selected.close }}</span><span>成交量 {{ selected.volume }}</span></div>
    <div v-if="selectedPoint" class="indicator-readout" aria-live="polite"><span v-if="showMa">MA {{ selectedPoint.ma ?? '预热不足' }}</span><span v-for="key in indicatorKeys" :key="key">{{ key.toUpperCase() }} {{ selectedPoint[key] ?? '预热不足' }}</span></div>
    <div ref="container" class="chart-canvas" :style="{ height: `${height}px` }" aria-label="历史日线与原始成交量图" />
    <div class="chart-caption"><span>红涨绿跌 · 支持缩放、拖拽与悬停读数 · 成交量为源端原始数值，单位未经确认</span><button type="button" @click="fit">适应全部数据</button></div>
    <p class="chart-notice"><a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">TradingView</a> · TradingView Lightweight Charts™ Copyright (с) 2025 TradingView, Inc. https://www.tradingview.com/</p>
  </div>
</template>
<style scoped>
.history-chart { background: #fff; color: #273449; min-width: 0; }
.history-readout, .indicator-readout, .indicator-layers, .chart-caption { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; padding: 8px 0; font-variant-numeric: tabular-nums; }
.indicator-layers [role='tablist'] { display: flex; gap: 6px; }
.chart-canvas { width: 100%; }
.chart-caption, .chart-notice { font-size: 12px; color: #596579; }
.chart-notice { overflow-wrap: anywhere; }
button { cursor: pointer; padding: 6px 10px; background: #f4f7fb; border: 1px solid #dce3eb; border-radius: 6px; color: #273449; }
button[aria-selected='true'] { background: #dbeafe; border-color: #2563eb; }
</style>
