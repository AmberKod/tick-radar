<script setup lang="ts">
import type { ScheduleRunPage } from '../types/schedules'
import { beijingTime, scheduleStatus } from '../composables/scheduleDraft'
import ScheduleCalendar from './ScheduleCalendar.vue'
defineProps<{ runs: ScheduleRunPage | null; busy: boolean }>()
defineEmits<{ page: [page: number] }>()
</script>
<template>
  <div data-testid="schedule-runs">
    <p v-if="!runs">请选择筛选范围并手动读取执行记录。</p>
    <template v-else>
      <p>共 {{ runs.total }} 条 · 第 {{ runs.page }} 页。已入投递队列不代表已投递，请到“站内通知与投递”确认。</p>
      <p v-if="!runs.items.length">暂无执行记录。已删除提醒的历史记录仍保留在“全部提醒”中。</p>
      <div v-else class="alert-scroll" tabindex="0" aria-label="尾盘提醒执行记录表格">
        <table>
          <thead><tr><th>提醒与版本</th><th>交易日 / 时间</th><th>结果</th><th>详情</th></tr></thead><tbody>
            <tr v-for="run in runs.items" :key="run.id"><td>{{ run.schedule_name }}<small>{{ run.exchange }} · v{{ run.schedule_version }}</small><small>{{ run.schedule_id }}</small></td><td>{{ run.session_date }} · {{ run.local_time }}<small>计划：{{ beijingTime(run.scheduled_at) }}</small><small>记录：{{ beijingTime(run.created_at) }}</small></td><td>{{ scheduleStatus(run.status) }}<small>{{ run.reason }}</small><small>投递 ID：{{ run.outbox_id || '无' }}</small></td><td><details><summary>日历依据与配置快照</summary><ScheduleCalendar :calendar="run.calendar" /><pre>{{ JSON.stringify(run.rule_snapshot, null, 2) }}</pre><small>执行 ID：{{ run.id }}</small></details></td></tr>
          </tbody>
        </table>
      </div>
      <div class="toolbar"><button :disabled="busy || runs.page <= 1" @click="$emit('page', runs.page - 1)">上一页</button><button :disabled="busy || runs.page * runs.page_size >= runs.total" @click="$emit('page', runs.page + 1)">下一页</button></div>
    </template>
  </div>
</template>
<style scoped>
pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:400px}td{min-width:130px}td:last-child{min-width:260px}
</style>
