<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Schedule, ScheduleCreate } from '../types/schedules'
import { newScheduleDraft, scheduleDraft, schedulePayload, scheduleTimes } from '../composables/scheduleDraft'
const props = defineProps<{ schedule: Schedule | null; busy: boolean; submit: (body: ScheduleCreate) => Promise<boolean> }>()
const draft = ref(newScheduleDraft()), error = ref('')
watch(() => props.schedule, value => { draft.value = value ? scheduleDraft(value) : newScheduleDraft(); error.value = '' }, { immediate: true })
const canonical = computed(() => { try { return scheduleTimes(draft.value.times).join('、') } catch { return '请修正时间输入后核对' } })
async function save() { error.value = ''; try { await props.submit(schedulePayload(draft.value)) } catch (cause) { error.value = cause instanceof Error ? cause.message : '请检查输入' } }
</script>
<template>
  <section class="panel alert-business-panel" data-testid="schedule-editor">
    <h2>{{ schedule ? '编辑尾盘提醒' : '新建尾盘提醒' }}</h2>
    <p v-if="schedule">当前保存版本 v{{ schedule.version }} · {{ schedule.enabled ? '已启用' : '已停用' }}</p>
    <form class="alert-form" @submit.prevent="save">
      <fieldset :disabled="busy">
        <label>提醒名称<input v-model="draft.name" aria-label="尾盘提醒名称" maxlength="80" required></label>
        <label>交易所<select v-model="draft.exchange" aria-label="尾盘提醒交易所"><option value="SSE">上海证券交易所（SSE）</option><option value="SZSE">深圳证券交易所（SZSE）</option><option value="BSE">北京证券交易所（BSE）</option></select></label>
        <p>固定时区：北京时间 Asia/Shanghai</p>
        <label>提醒时间<input v-model="draft.times" aria-label="尾盘提醒时间" required placeholder="14:30,14:40,14:50"></label>
        <small>14:00 至 14:59，分钟精度，最多 8 个且不可重复；支持逗号、中文逗号或空格分隔。</small>
        <p data-testid="schedule-canonical-times">规范时间（升序）：{{ canonical }}</p>
        <label>提醒内容<textarea v-model="draft.message" aria-label="尾盘提醒内容" maxlength="1000" rows="4" required /></label>
        <label>宽限秒数<input v-model.number="draft.grace_seconds" aria-label="尾盘提醒宽限秒数" type="number" min="30" max="600" step="1" required></label>
        <label class="alert-check"><input v-model="draft.enabled" type="checkbox" aria-label="启用尾盘提醒">启用尾盘提醒（须明确勾选，默认停用）</label>
        <p>新启用或编辑后，当天已经过去的时间点不追补。保存后请核对版本和启用状态。</p>
        <p v-if="error" role="alert">{{ error }}</p>
        <button type="submit" data-testid="schedule-save">{{ busy ? '正在提交…' : '保存尾盘提醒' }}</button>
      </fieldset>
    </form>
  </section>
</template>
<style scoped>
textarea{box-sizing:border-box;width:100%;max-width:100%;resize:vertical;border:1px solid #dce2eb;border-radius:6px;padding:9px;background:#fff;color:#27364c;font:inherit}
</style>
