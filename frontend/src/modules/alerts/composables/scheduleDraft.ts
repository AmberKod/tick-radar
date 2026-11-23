import type { Schedule, ScheduleCreate } from '../types/schedules'
export interface ScheduleDraft { name: string; exchange: 'SSE' | 'SZSE' | 'BSE'; times: string; message: string; grace_seconds: number; enabled: boolean }
export const newScheduleDraft = (): ScheduleDraft => ({ name: '', exchange: 'SSE', times: '14:30,14:40,14:50', message: '请核对尾盘检查清单与风险约束，条件不满足时保持观望。', grace_seconds: 120, enabled: false })
export const scheduleDraft = (value: Schedule): ScheduleDraft => ({ name: value.name, exchange: value.exchange, times: value.times.join(','), message: value.message, grace_seconds: value.grace_seconds, enabled: value.enabled })
export function scheduleTimes(value: string): string[] {
  const times = value.trim().split(/[,，\s]+/u)
  if (!value.trim() || times.some(time => !/^14:[0-5][0-9]$/.test(time))) throw new Error('时间必须是 14:00 至 14:59 的 HH:mm，可用逗号、中文逗号或空格分隔。')
  if (times.length > 8) throw new Error('最多填写 8 个时间。')
  if (new Set(times).size !== times.length) throw new Error('时间不能重复，请明确删除重复项。')
  return [...times].sort()
}
export function schedulePayload(draft: ScheduleDraft): ScheduleCreate {
  if ([...draft.name].some(char => char.charCodeAt(0) < 32 || (char.charCodeAt(0) >= 127 && char.charCodeAt(0) <= 159)) || !draft.name.trim() || [...draft.name].length > 80) throw new Error('名称须为 1 至 80 字，且不能包含控制字符。')
  if ([...draft.message].some(char => (char.charCodeAt(0) < 32 && char !== '\n') || (char.charCodeAt(0) >= 127 && char.charCodeAt(0) <= 159)) || !draft.message.trim() || [...draft.message].length > 1000) throw new Error('提醒内容须为 1 至 1000 字，仅允许换行，不允许其他控制字符。')
  if (!['SSE', 'SZSE', 'BSE'].includes(draft.exchange)) throw new Error('请选择沪、深或北交易所。')
  if (!Number.isInteger(draft.grace_seconds) || draft.grace_seconds < 30 || draft.grace_seconds > 600) throw new Error('宽限秒数须为 30 至 600 的整数。')
  if (typeof draft.enabled !== 'boolean') throw new Error('请明确选择启用状态。')
  return { name: draft.name.trim(), exchange: draft.exchange, times: scheduleTimes(draft.times), message: draft.message, grace_seconds: draft.grace_seconds, enabled: draft.enabled }
}
export function beijingTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(date)
}
const statusLabels: Record<string, string> = { ENQUEUED: '已入投递队列', MISSED: '已错过', DISABLED: '已停用', WAITING: '未到计划时间', SKIPPED: '暂停判断', NON_TRADING: '非交易日', ENQUEUE: '窗口内可入队（仅预览）' }
export const scheduleStatus = (status: string) => statusLabels[status] || status
