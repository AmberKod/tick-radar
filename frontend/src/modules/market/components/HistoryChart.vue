<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { CandlestickSeries, ColorType, HistogramSeries, createChart, type IChartApi, type Time } from 'lightweight-charts'
import type { HistoryBar } from '../types'
const props = defineProps<{ bars: HistoryBar[] }>()
const container = ref<HTMLDivElement>()
const selected = ref<HistoryBar | null>(props.bars.at(-1) || null)
let chart: IChartApi | undefined
let observer: ResizeObserver | undefined
onMounted(() => {
  if (!container.value) return
  chart = createChart(container.value, {
    height: 480, width: container.value.clientWidth,
    layout: { background: { type: ColorType.Solid, color: '#ffffff' }, textColor: '#273449', attributionLogo: true },
    grid: { vertLines: { color: '#edf1f5' }, horzLines: { color: '#edf1f5' } },
    timeScale: { timeVisible: false, borderColor: '#dce3eb' },
  })
  const candles = chart.addSeries(CandlestickSeries, { upColor: '#d03050', downColor: '#16804a', wickUpColor: '#d03050', wickDownColor: '#16804a', borderVisible: false })
  const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' } }, 1)
  candles.setData(props.bars.map(bar => ({ time: bar.date as Time, open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close) })))
  volume.setData(props.bars.map(bar => ({ time: bar.date as Time, value: Number(bar.volume), color: Number(bar.close) >= Number(bar.open) ? '#d03050' : '#16804a' })))
  chart.panes()[1]?.setHeight(120)
  const byDate = new Map(props.bars.map(bar => [bar.date, bar]))
  chart.subscribeCrosshairMove(event => {
    const time = event.time
    const date = typeof time === 'string' ? time : typeof time === 'object' ? `${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}` : ''
    selected.value = byDate.get(date) || props.bars.at(-1) || null
  })
  chart.timeScale().fitContent()
  observer = new ResizeObserver(() => {
    if (container.value) chart?.resize(container.value.clientWidth, 480)
  })
  observer.observe(container.value)
})
onBeforeUnmount(() => { observer?.disconnect(); chart?.remove(); chart = undefined })
function fit() { chart?.timeScale().fitContent() }
</script>
<template>
  <div class="history-chart">
    <div v-if="selected" class="history-readout" aria-live="polite"><strong>{{ selected.date }}</strong><span>开 {{ selected.open }}</span><span>高 {{ selected.high }}</span><span>低 {{ selected.low }}</span><span>收 {{ selected.close }}</span><span>成交量 {{ selected.volume }}</span></div>
    <div ref="container" class="chart-canvas" aria-label="历史日线与原始成交量图" />
    <div class="chart-caption"><span>红涨绿跌 · 支持缩放、拖拽与悬停读数 · 成交量为源端原始数值，单位未经确认</span><button type="button" @click="fit">适应全部数据</button></div>
    <p class="chart-notice"><a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">TradingView</a> · TradingView Lightweight Charts™ Copyright (с) 2025 TradingView, Inc. https://www.tradingview.com/</p>
  </div>
</template>
<style scoped>
.history-chart { background: #fff; color: #273449; min-width: 0; }
.history-readout, .chart-caption { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; padding: 12px 0; font-variant-numeric: tabular-nums; }
.chart-canvas { width: 100%; height: 480px; }
.chart-caption, .chart-notice { font-size: 12px; color: #596579; }
.chart-notice { overflow-wrap: anywhere; }
.chart-caption button { cursor: pointer; padding: 6px 10px; background: #f4f7fb; border: 1px solid #dce3eb; border-radius: 6px; color: #273449; }
</style>
