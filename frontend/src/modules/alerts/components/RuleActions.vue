<script setup lang="ts">
import { ref, watch } from 'vue'
import type { AlertRule, AlertPreview } from '../types'
import { beijingTime, decimalLabel } from '../composables/ruleDraft'
const props = defineProps<{ rule: AlertRule; preview: AlertPreview | null; busy: boolean; remove: () => Promise<boolean>; reset: () => Promise<boolean> }>()
defineEmits<{ preview: [] }>()
const confirmation = ref('')
watch(() => props.rule.id, () => { confirmation.value = '' })
async function confirm() { const success = await (confirmation.value === 'delete' ? props.remove() : props.reset()); if (success) confirmation.value = '' }
</script>
<template>
  <section class="panel alert-business-panel">
    <h2>规则操作与试算</h2><div class="toolbar"><button :disabled="busy" @click="$emit('preview')">只读试算</button><button :disabled="busy" @click="confirmation = 'reset'">重置基线</button><button :disabled="busy" @click="confirmation = 'delete'">删除规则</button></div>
    <div v-if="confirmation" class="alert-confirm"><p v-if="confirmation === 'delete'">确认删除「{{ rule.name }}」（{{ rule.symbol }} · v{{ rule.version }}）？历史事件会保留。</p><p v-else>确认重置「{{ rule.name }}」（{{ rule.symbol }} · v{{ rule.version }}）？清除穿越基线，保留冷却时间。</p><button :disabled="busy" @click="confirm">确认{{ confirmation === 'delete' ? '删除' : '重置' }}</button> <button :disabled="busy" @click="confirmation = ''">取消</button></div>
    <p>只读试算使用已保存规则和真实缓存，不触发事件、不投递通知、不修改基线或冷却。编辑中的草稿须先保存。</p>
    <div v-if="preview" data-testid="alert-preview"><p>{{ preview.status }} · {{ preview.reason }}</p><p>可评估：{{ preview.eligible ? '是' : '否' }} · 条件将触发：{{ preview.would_trigger ? '是' : '否' }} · 值 {{ decimalLabel(preview.value) }}</p><p>状态 {{ preview.state_before.phase }} → {{ preview.state_after.phase }}（仅模拟）</p><p v-if="preview.quote">来源 {{ preview.quote.source }} · 源时间原文 {{ preview.quote.source_time_raw || '—' }}<br>接收 {{ beijingTime(preview.quote.received_at) }} · 质量 {{ preview.quote.quality_status }} · 延迟 {{ preview.quote.delay_status }}</p></div>
  </section>
</template>
