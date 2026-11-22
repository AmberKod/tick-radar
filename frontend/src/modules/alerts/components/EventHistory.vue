<script setup lang="ts">
import type { AlertEventPage } from '../types'
import { beijingTime, decimalLabel, ruleLabels } from '../composables/ruleDraft'
defineProps<{ events: AlertEventPage | null; busy: boolean }>()
defineEmits<{ page: [page: number] }>()
</script>
<template>
  <section class="panel alert-business-panel">
    <h2>触发记录</h2><p>事件保留触发时的规则版本和报价快照。所有时间为北京时间；观察记录不构成交易建议。</p>
    <p v-if="!events?.items.length">暂无触发记录。</p>
    <div v-else class="alert-scroll"><table><thead><tr><th>时间 / 规则</th><th>触发值 / 阈值</th><th>快照与依据</th></tr></thead><tbody><tr v-for="event in events.items" :key="event.id"><td>{{ beijingTime(event.created_at) }}<small>{{ event.rule_name }} · {{ event.symbol }} · v{{ event.rule_version }}</small><small>{{ ruleLabels[event.rule_type] }} · {{ event.mode }}</small></td><td>{{ decimalLabel(event.value) }} / {{ decimalLabel(event.threshold) }}<small>{{ event.reason }}</small></td><td>来源 {{ event.quote.source }}<small>源时间（原文）{{ event.quote.source_time_raw || '—' }}</small><small>接收 {{ beijingTime(event.quote.received_at) }}</small><small>质量 {{ event.quote.quality_status }} · 延迟 {{ event.quote.delay_status }}</small><small>投递编号 {{ event.outbox_id || '—' }}</small></td></tr></tbody></table></div>
    <div v-if="events" class="toolbar"><button :disabled="busy || events.page <= 1" @click="$emit('page', events.page - 1)">上一页</button><span>第 {{ events.page }} 页，共 {{ events.total }} 条</span><button :disabled="busy || events.page * events.page_size >= events.total" @click="$emit('page', events.page + 1)">下一页</button></div>
  </section>
</template>
