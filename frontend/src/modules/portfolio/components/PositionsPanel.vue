<script setup lang="ts">
import type { PortfolioSummary, PortfolioValuationResponse } from '../types'
import { beijingTime, decimalLabel as number } from '../composables/format'
defineProps<{ summary: PortfolioSummary | null; valuation: PortfolioValuationResponse | null; valuationError: string }>()
const tone = (value: string | null | undefined) => !value || /^-?0(?:\.0*)?$/.test(value) ? '' : value.startsWith('-') ? 'portfolio-loss' : 'portfolio-profit'
</script>
<template>
  <section class="panel portfolio-panel">
    <h2>账户摘要与持仓</h2>
    <template v-if="summary">
      <p>{{ summary.account.name }} · {{ summary.account.currency }} · 移动加权平均成本</p>
      <p class="muted">核对时间 {{ beijingTime(summary.checked_at) }} · 数值保留原精度，去除无意义小数零</p>
      <div class="portfolio-metrics">
        <div>现金余额<strong :title="summary.cash_balance">{{ number(summary.cash_balance) }}</strong></div>
        <div>持仓成本<strong :title="summary.total_cost">{{ number(summary.total_cost) }}</strong></div>
        <div>已实现盈亏<strong :class="tone(summary.realized_pnl)" :title="summary.realized_pnl">{{ number(summary.realized_pnl) }}</strong></div>
        <div>累计分红<strong>{{ number(summary.dividend_income) }}</strong></div>
        <div>独立费用<strong>{{ number(summary.standalone_fees) }}</strong></div>
        <div>外部净入金<strong>{{ number(summary.external_net_flow) }}</strong></div>
        <div>内部净划入（原币）<strong>{{ number(summary.internal_net_flow) }}</strong></div>
      </div>
      <p v-for="warning in summary.warnings" :key="warning" role="status">{{ warning }}</p>
      <h3>观察估值</h3>
      <p class="muted">缓存报价用于数据观察，非实时成交价；缺价显示未覆盖，不视为0。不跨币种相加，不表示当日盈亏。</p>
      <p v-if="valuationError" role="status">估值暂不可读，账本仍可使用：{{ valuationError }}</p>
      <div v-if="valuation" class="portfolio-metrics">
        <div>覆盖持仓<strong>{{ valuation.valued_positions }} / {{ valuation.total_positions }}</strong></div>
        <div>总市值<strong>{{ number(valuation.market_value) }}</strong></div>
        <div>浮动盈亏<strong :class="tone(valuation.unrealized_pnl)">{{ number(valuation.unrealized_pnl) }}</strong></div>
        <div>净资产<strong>{{ number(valuation.net_asset_value) }}</strong></div>
      </div>
      <p v-if="valuation" class="muted">估值核对时间 {{ beijingTime(valuation.checked_at) }} · {{ valuation.complete ? '覆盖完整' : '覆盖不完整' }}</p>
      <details v-if="valuation?.warnings?.length" class="portfolio-valuation-notes"><summary>估值来源与质量说明</summary><p v-for="warning in valuation?.warnings || []" :key="warning">{{ warning }}</p></details>
      <div class="portfolio-scroll">
        <table>
          <thead><tr><th>证券</th><th>数量</th><th>成本 / 均价</th><th>已实现 / 分红</th><th>观察价格 / 市值 / 浮盈亏</th><th>报价来源与时间</th></tr></thead>
          <tbody>
            <tr v-for="position in summary.positions" :key="position.security_id">
              <td>{{ position.symbol }}<small>{{ position.name }} · {{ position.currency }}</small></td>
              <td>{{ number(position.quantity) }}</td>
              <td>{{ number(position.total_cost) }}<small>{{ number(position.average_cost) }}</small></td>
              <td><span :class="tone(position.realized_pnl)">{{ number(position.realized_pnl) }}</span><small>分红 {{ number(position.dividend_income) }}</small></td>
              <td>
                <span v-if="/^0(?:\.0*)?$/.test(position.quantity)">已清仓</span>
                <template v-for="item in /^0(?:\.0*)?$/.test(position.quantity) ? [] : [valuation?.positions.find(item => item.security_id === position.security_id)]" :key="item?.security_id || 'missing'">
                  <span>{{ number(item?.price) }}</span><small>市值 {{ number(item?.market_value) }}</small><small :class="tone(item?.unrealized_pnl)">浮盈亏 {{ number(item?.unrealized_pnl) }}</small>
                </template>
              </td>
              <td>
                <template v-for="quote in [valuation?.positions.find(item => item.security_id === position.security_id)?.quote]" :key="quote?.symbol || 'missing'">
                  <template v-if="quote"><small>{{ quote.source }} · {{ quote.quality_status }}</small><small>源时间（原始）{{ quote.source_time_raw || '未知' }}</small><small>接收时间 {{ beijingTime(quote.received_at) }}</small><small>延迟状态 {{ quote.delay_status }} · 时间语义未经验证</small></template>
                  <span v-else>{{ /^0(?:\.0*)?$/.test(position.quantity) ? '已清仓，不估值' : '当前数据源未覆盖' }}</span>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!summary.positions.length" class="small-empty">尚无持仓。先入金，再搜索证券录入买入；清仓后保留已实现收益。</p>
    </template>
    <p v-else class="small-empty">选择账户后读取真实账本摘要。</p>
  </section>
</template>
