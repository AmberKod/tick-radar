<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import TransferPanel from '../components/TransferPanel.vue'
import { useAuthStore } from '../../auth'
import { usePortfolio } from '../composables/usePortfolio'
import AccountPanel from '../components/AccountPanel.vue'
import EntryForm from '../components/EntryForm.vue'
import PositionsPanel from '../components/PositionsPanel.vue'
import LedgerPanel from '../components/LedgerPanel.vue'
const tab = ref('ledger'), transferBusy = ref(false)
const auth = useAuthStore()
const portfolio = usePortfolio()
const { accounts, selected, summary, ledger, valuation, loading, saving, error, valuationError } = portfolio
const account = computed(() => accounts.value.find(item => item.id === selected.value))
onMounted(() => { void portfolio.load() })
</script>
<template>
  <div class="business-page portfolio-page">
    <section class="page-heading"><div><div class="eyebrow">PORTFOLIO</div><h1>资产组合</h1><p>按原币记录入出金、交易与分红，查询持仓成本和累计盈亏。</p></div><button :disabled="loading || saving || transferBusy" @click="selected ? portfolio.refresh() : portfolio.load()">{{ loading ? '正在读取…' : '刷新账本' }}</button></section>
    <p v-if="error" role="alert" class="portfolio-error">{{ error }}</p>
    <div class="toolbar" role="tablist" aria-label="资产组合功能"><button role="tab" :aria-selected="tab === 'ledger'" :disabled="saving || transferBusy" @click="tab = 'ledger'">账户账本</button><button role="tab" :aria-selected="tab === 'transfers'" :disabled="saving || transferBusy" @click="tab = 'transfers'">内部划转与换汇</button></div>
    <TransferPanel v-if="tab === 'transfers'" :key="auth.epoch" :accounts="accounts" :selected="selected" @changed="portfolio.refresh" @busy="transferBusy = $event" />
    <div v-else class="portfolio-layout"><AccountPanel :key="`${auth.epoch}:${selected}`" :accounts="accounts" :selected="selected" :busy="loading || saving" @select="portfolio.select" @create="portfolio.create" @update="portfolio.update" /><div class="portfolio-main"><p v-if="!accounts.length && !loading" class="panel portfolio-panel">尚未创建账户。请在左侧填写账户名称和币种，创建后从入金开始记账。</p><template v-if="account"><EntryForm :key="selected" :account="account" :busy="saving" :submit="portfolio.enter" /><PositionsPanel :summary="summary" :valuation="valuation" :valuation-error="valuationError" /><LedgerPanel :key="selected" :ledger="ledger" :busy="saving || loading" :reverse="portfolio.reverse" @page="portfolio.changePage" /></template></div></div>
  </div>
</template>
<style scoped>
.portfolio-layout{display:grid;grid-template-columns:minmax(220px,280px) minmax(0,1fr);gap:20px;align-items:start}.portfolio-main{display:grid;gap:20px;min-width:0}.portfolio-page :deep(.portfolio-panel){padding:20px;min-width:0}.portfolio-page :deep(.portfolio-form){display:grid;gap:12px;margin-top:18px}.portfolio-page :deep(label){display:grid;gap:6px;min-width:0}.portfolio-page :deep(input),.portfolio-page :deep(select),.portfolio-page :deep(textarea){max-width:100%;width:100%;box-sizing:border-box;border:1px solid #dce2eb;border-radius:6px;padding:9px;background:white;color:#27364c;font:inherit}.portfolio-page :deep(button){border:1px solid #cbd5e1;background:#f8fafc;color:#23354d;border-radius:6px;padding:8px 12px;cursor:pointer;white-space:normal}.portfolio-page :deep(button:disabled){opacity:.5;cursor:default}.portfolio-page :deep(fieldset){border:0;padding:0;margin:0;min-width:0;display:grid;gap:12px}.portfolio-page :deep(.portfolio-fields){display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.portfolio-page :deep(.portfolio-checkbox){display:flex;align-items:center;gap:8px}.portfolio-page :deep(input[type=checkbox]){width:auto}.portfolio-page :deep(.portfolio-scroll){overflow-x:auto;max-width:100%}.portfolio-page :deep(table){width:100%;border-collapse:collapse;min-width:720px}.portfolio-page :deep(th),.portfolio-page :deep(td){text-align:left;padding:12px 8px;border-bottom:1px solid #e6ebf1;vertical-align:top}.portfolio-page :deep(small){display:block;margin-top:5px;overflow-wrap:anywhere}.portfolio-page :deep(.portfolio-metrics){display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.portfolio-page :deep(.portfolio-metrics strong){display:block;margin-top:6px;font-size:20px;overflow-wrap:anywhere}.portfolio-page :deep(.portfolio-error){color:#a32432;overflow-wrap:anywhere}.portfolio-page :deep(.portfolio-profit){color:#c53742}.portfolio-page :deep(.portfolio-loss){color:#16824a}.portfolio-page :deep(.portfolio-confirm){padding:16px;margin-top:16px;border:1px solid #e5ba7b;background:#fffaf1;display:grid;gap:12px}.portfolio-page :deep(p){overflow-wrap:anywhere}@media(max-width:850px){.portfolio-layout{grid-template-columns:1fr}.portfolio-page :deep(.portfolio-metrics){grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:420px){.portfolio-page :deep(.portfolio-fields){grid-template-columns:1fr}.portfolio-page :deep(.portfolio-panel){padding:14px}}
</style>
