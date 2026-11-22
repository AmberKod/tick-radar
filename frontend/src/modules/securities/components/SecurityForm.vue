<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { NButton, NInput, NSelect } from 'naive-ui'
import { currencies, exchanges, validSymbol, type CreateSecurity, type Market, type SecurityDTO, type UpdateSecurity } from '../types'
const props = defineProps<{ security?: SecurityDTO; saving: boolean }>()
const emit = defineEmits<{ save: [body: CreateSecurity | UpdateSecurity] }>()
const market = ref<Market>('CN')
const form = reactive({ symbol: '', name: '', exchange: 'SSE' as CreateSecurity['exchange'], security_type: 'STOCK' as CreateSecurity['security_type'], status: 'ACTIVE' as NonNullable<UpdateSecurity['status']> })
watch(() => props.security, value => { if (value) Object.assign(form, value) }, { immediate: true })
watch(market, value => { form.exchange = exchanges[value][0]!; form.symbol = '' })
const exchangeOptions = computed(() => exchanges[market.value].map(value => ({ label: value, value })))
const valid = computed(() => form.name.trim() && (props.security || validSymbol(form.symbol, market.value)))
function submit() {
  if (!valid.value) return
  emit('save', props.security ? { name: form.name.trim(), status: form.status } : { symbol: form.symbol, name: form.name.trim(), exchange: form.exchange, security_type: form.security_type })
}
</script>
<template>
  <form class="entry-form" @submit.prevent="submit">
    <template v-if="!security">
      <label>市场<NSelect v-model:value="market" :options="['CN','HK','US'].map(value => ({label:value,value}))" :disabled="saving" /></label>
      <label>标准代码<NInput v-model:value="form.symbol" :placeholder="`${market}:` + (market === 'CN' ? '六位数字' : market === 'HK' ? '五位数字' : '大写代码')" :disabled="saving" /></label>
      <p v-if="form.symbol && !validSymbol(form.symbol, market)" class="field-error">代码格式不正确，请保留市场前缀。</p>
      <label>交易所<NSelect v-model:value="form.exchange" :options="exchangeOptions" :disabled="saving" /></label>
      <label>证券类型<NSelect v-model:value="form.security_type" :options="['STOCK','ETF','ADR'].map(value => ({label:value,value}))" :disabled="saving" /></label>
      <p class="muted">币种：{{ currencies[market] }}（由市场固定）</p>
    </template>
    <p v-else>{{ security.symbol }} · {{ security.exchange }}</p>
    <label>证券名称<NInput v-model:value="form.name" :maxlength="120" :disabled="saving" /></label>
    <label v-if="security">状态<NSelect v-model:value="form.status" :options="[{label:'启用',value:'ACTIVE'},{label:'停用',value:'INACTIVE'}]" :disabled="saving" /></label>
    <NButton type="primary" attr-type="submit" :loading="saving" :disabled="saving || !valid">保存资料</NButton>
  </form>
</template>
