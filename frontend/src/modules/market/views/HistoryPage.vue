<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NInput, NSelect } from 'naive-ui'
import { getHistory, getIndicators } from '../api'
import { ApiError } from '../../../shared/api/client'
import type { DailyIndicatorsResponse, IndicatorParameters, HistoryAdjustment, HistoryResponse } from '../types'
import HistoryChart from '../components/HistoryChart.vue'
const route = useRoute(), router = useRouter()
const symbol = ref(''), limit = ref(120), adjustment = ref<HistoryAdjustment>('raw')
const result = ref<HistoryResponse | null>(null), error = ref(''), loading = ref(false)
const indicatorsEnabled = ref(false), indicators = ref<DailyIndicatorsResponse | null>(null)
const importantWarnings = computed(() => indicators.value?.warnings.filter(warning => /预热不足|未达到|缺失/.test(warning)) || [])
const shortParameters: IndicatorParameters = { ma_period: 10, macd_fast: 6, macd_slow: 13, macd_signal: 5, kdj_lookback: 13, kdj_k: 5, kdj_d: 5, atr_period: 14 }
const standardParameters: IndicatorParameters = { ma_period: 20, macd_fast: 12, macd_slow: 26, macd_signal: 9, kdj_lookback: 9, kdj_k: 3, kdj_d: 3, atr_period: 14 }
const parameters = ref<IndicatorParameters>({ ...shortParameters })
const parameterFields: { key: keyof IndicatorParameters; label: string; min: number; max: number }[] = [
  { key: 'ma_period', label: 'MA 周期', min: 2, max: 120 },
  { key: 'macd_fast', label: 'MACD 快线', min: 2, max: 60 }, { key: 'macd_slow', label: 'MACD 慢线', min: 3, max: 120 }, { key: 'macd_signal', label: 'MACD 信号周期', min: 2, max: 60 },
  { key: 'kdj_lookback', label: 'KDJ 回看周期', min: 2, max: 120 }, { key: 'kdj_k', label: 'K 平滑周期', min: 2, max: 60 }, { key: 'kdj_d', label: 'D 平滑周期', min: 2, max: 60 },
  { key: 'atr_period', label: 'ATR 周期', min: 2, max: 120 },
]
const parameterError = computed(() => {
  if (!indicatorsEnabled.value) return ''
  if (limit.value > 500) return '计算日线指标最多支持 500 根，以保留预热数据；请明确改选 500 根或关闭指标。'
  if (parameterFields.some(field => !Number.isInteger(parameters.value[field.key]) || parameters.value[field.key] < field.min || parameters.value[field.key] > field.max)) return '指标参数必须为指定范围内的整数。'
  return parameters.value.macd_fast >= parameters.value.macd_slow ? 'MACD 快线周期必须小于慢线周期。' : ''
})
let revision = 0, controller: AbortController | undefined
const limits = [60, 120, 250, 500, 640].map(value => ({ label: `${value} 根`, value }))
const adjustments = [{ label: '不复权', value: 'raw' }, { label: '前复权', value: 'qfq' }, { label: '后复权', value: 'hfq' }]
const adjustmentLabels = { raw: '不复权', qfq: '前复权', hfq: '后复权' }
async function load(value: string) {
  const current = ++revision
  controller?.abort(); controller = new AbortController()
  result.value = null; indicators.value = null; error.value = ''; loading.value = false
  symbol.value = value.trim().toUpperCase()
  if (!symbol.value) return
  if (!/^(CN:\d{6}|HK:\d{5}|US:[A-Z][A-Z0-9.-]*)$/.test(symbol.value)) { error.value = '请输入标准证券代码，例如 CN:600519、HK:00700 或 US:AAPL。'; return }
  if (parameterError.value) { error.value = parameterError.value; return }
  const requestedSymbol = symbol.value, requestedAdjustment = adjustment.value
  loading.value = true
  try {
    const calculated = indicatorsEnabled.value ? await getIndicators(requestedSymbol, limit.value, requestedAdjustment, { ...parameters.value }, { signal: controller.signal }) : null
    const data = calculated ? calculated.history : await getHistory(requestedSymbol, limit.value, requestedAdjustment, { signal: controller.signal })
    if (current !== revision) return
    if (calculated && (data.symbol !== requestedSymbol || data.adjustment !== requestedAdjustment)) throw new Error('指标响应证券或复权方式不匹配，请重新查询。')
    const valid = data.bars.every(bar => /^\d{4}-\d{2}-\d{2}$/.test(bar.date) && [bar.open, bar.high, bar.low, bar.close].every(value => value.trim() !== '' && Number.isFinite(Number(value)) && Number(value) > 0) && bar.volume.trim() !== '' && Number.isFinite(Number(bar.volume)) && Number(bar.volume) >= 0)
    const ordered = data.bars.every((bar, index) => index === 0 || bar.date > data.bars[index - 1]!.date)
    if (!valid || !ordered) throw new Error('历史数据格式异常，无法绘制日线，请稍后重试。')
    if (calculated) {
      const values = ['ma', 'dif', 'dea', 'macd', 'k', 'd', 'j', 'atr'] as const
      if (calculated.points.length !== data.bars.length || !calculated.points.every((point, index) => point.date === data.bars[index]!.date && values.every(key => point[key] === null || (typeof point[key] === 'string' && point[key].trim() !== '' && Number.isFinite(Number(point[key])))))) throw new Error('指标数据格式异常或日期未对齐，无法绘图。')
      indicators.value = calculated
    }
    result.value = data
  } catch (cause) {
    if (current !== revision) return
    error.value = cause instanceof ApiError ? `${cause.message}（${cause.code}；请求 ID：${cause.requestId}）` : cause instanceof Error ? cause.message : '历史日线读取失败，请稍后重试。'
  } finally { if (current === revision) loading.value = false }
}
async function lookup(value = symbol.value) {
  const next = value.trim().toUpperCase()
  if (route.query.symbol !== next) await router.push({ path: '/market/history', query: next ? { symbol: next } : {} })
  else await load(next)
}
watch(() => route.query.symbol, value => { void load(typeof value === 'string' ? value : '') }, { immediate: true })
onBeforeUnmount(() => { ++revision; controller?.abort() })
function time(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : `${parsed.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })} GMT+8`
}
</script>
<template>
  <div class="business-page history-page">
    <section class="page-heading"><div><div class="eyebrow">MARKET HISTORY</div><h1>历史日线</h1><p>公共历史数据，只读观察；历史数据不是实时行情。休市期间仍可查询。</p></div></section>
    <section class="panel business-panel">
      <form class="toolbar history-form" @submit.prevent="lookup()">
        <NInput v-model:value="symbol" placeholder="CN:600519、HK:00700、US:AAPL" aria-label="历史证券代码" />
        <NSelect v-model:value="limit" :options="limits" aria-label="历史根数" />
        <NSelect v-model:value="adjustment" :options="adjustments" aria-label="复权方式" />
        <NButton type="primary" attr-type="submit" :loading="loading" :disabled="!symbol.trim() || !!parameterError">查询历史日线</NButton>
      </form>
      <label class="indicator-toggle"><input v-model="indicatorsEnabled" type="checkbox" /> 计算日线指标</label>
      <details v-if="indicatorsEnabled" class="indicator-settings" open>
        <summary>指标参数（仅本次提交生效）</summary>
        <div class="sample-actions"><NButton @click="parameters = { ...shortParameters }">短周期观察</NButton><NButton @click="parameters = { ...standardParameters }">标准参数</NButton></div>
        <div class="parameter-grid"><label v-for="field in parameterFields" :key="field.key">{{ field.label }}<input v-model.number="parameters[field.key]" type="number" :min="field.min" :max="field.max" step="1" :aria-label="field.label" /></label></div>
      </details>
      <p v-if="parameterError" role="alert" class="parameter-error">{{ parameterError }}</p>
      <div class="sample-actions"><span>示例代码</span><NButton v-for="sample in ['CN:600519', 'HK:00700', 'US:AAPL']" :key="sample" text @click="lookup(sample)">{{ sample }}</NButton></div>
      <p class="muted">周期：日线 · 排除交易所当地日期为今天的 Bar · 成交量保留原始口径 · 美股暂不支持后复权</p>
    </section>
    <NAlert v-if="error" type="error" title="历史日线读取失败" role="alert">{{ error }}</NAlert>
    <p v-if="loading" class="small-empty" role="status">正在读取历史日线…</p>
    <section v-if="result" class="panel business-panel">
      <h2>{{ result.symbol }} · 历史日线</h2>
      <div class="history-meta"><span>历史截至 {{ result.latest_date || '暂无日期' }}</span><span>实际 {{ result.actual_count }} 根 / 请求 {{ result.requested_limit }} 根</span><span>来源 {{ result.source }}</span><span>{{ adjustmentLabels[result.adjustment] }} · {{ result.market }} · {{ result.currency }}</span><span>采集时间 {{ time(result.checked_at) }}</span><span>数据截至 {{ result.data_as_of || '暂无日期' }}</span></div>
      <NAlert v-if="!result.history_complete || result.actual_count < result.requested_limit" type="warning">历史覆盖不足：{{ result.coverage_reason || '数据源返回的历史根数少于请求根数。' }}</NAlert>
      <details class="history-source-details"><summary>数据来源与口径说明</summary><p v-for="warning in result.warnings || []" :key="warning">{{ warning }}</p></details>
      <section v-if="indicators" class="indicator-metadata">
        <h3>已计算指标 · {{ indicators.algorithm_version }}</h3>
        <p>数据截至 {{ indicators.as_of || '暂无日期' }} · 计算时间 {{ time(indicators.calculated_at) }}</p>
        <p>来源 {{ indicators.source_bars }} 根 · 实际预热 {{ indicators.warmup_bars }} 根 / 请求预热 {{ indicators.warmup_requested }} 根 · 展示 {{ indicators.visible_bars }} 根</p>
        <p>实际参数：MA {{ indicators.parameters.ma_period }}；MACD {{ indicators.parameters.macd_fast }}/{{ indicators.parameters.macd_slow }}/{{ indicators.parameters.macd_signal }}；KDJ {{ indicators.parameters.kdj_lookback }}/{{ indicators.parameters.kdj_k }}/{{ indicators.parameters.kdj_d }}；ATR {{ indicators.parameters.atr_period }}</p>
        <NAlert v-for="warning in importantWarnings" :key="warning" type="warning">{{ warning }}</NAlert>
        <details class="indicator-notes"><summary>指标公式与计算口径</summary><p class="parameter-hash">参数摘要 {{ indicators.parameter_hash }}</p><p v-for="note in indicators.formula_notes" :key="note">{{ note }}</p><p v-for="warning in indicators.warnings" :key="warning">{{ warning }}</p></details>
        <p>仅用于观察，不提供买卖信号。</p>
      </section>
      <HistoryChart v-if="result.bars.length" :key="`${result.symbol}-${result.adjustment}-${result.requested_limit}-${result.checked_at}-${indicators?.parameter_hash || ''}-${indicators?.calculated_at || ''}`" :bars="result.bars" :points="indicators?.points" :parameters="indicators?.parameters" />
      <p v-else class="small-empty">暂无可用历史日线，请更换标的或稍后重试。</p>
      <p class="muted">仅用于观察。历史数据不是实时行情，不拼接当前报价。</p>
    </section>
    <p v-else-if="!loading && !error" class="small-empty">输入标准证券代码或点击示例，查询历史日线。</p>
  </div>
</template>
<style scoped>
.indicator-toggle { display: inline-flex; align-items: center; gap: 6px; margin: 16px 0; }
.indicator-settings summary { cursor: pointer; }
.parameter-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 12px; margin: 12px 0; }
.parameter-grid label { display: grid; gap: 6px; }
.parameter-grid input { width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; }
.parameter-error { color: #d03050; }
.indicator-metadata { font-size: 13px; line-height: 1.8; }
.parameter-hash { overflow-wrap: anywhere; }
.history-form { display: grid; grid-template-columns: minmax(220px, 1fr) 120px 140px auto; }
.history-meta { display: flex; flex-wrap: wrap; gap: 10px 24px; margin: 16px 0; color: #596579; font-size: 13px; }
.history-source-details { margin: 12px 0 18px; color: #596579; font-size: 12px; line-height: 1.8; }
.history-source-details summary { cursor: pointer; }
.history-source-details p { margin: 6px 0; }
@media (max-width: 760px) { .history-form { grid-template-columns: 1fr 1fr; } .history-form > :first-child { grid-column: 1 / -1; } }
</style>
