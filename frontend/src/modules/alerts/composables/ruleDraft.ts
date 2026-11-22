import type { AlertRule, AlertRuleCreate } from '../types'
export const ruleLabels = { PRICE_CROSS_UP: '价格上穿', PRICE_CROSS_DOWN: '价格下穿', DAY_CHANGE_ABOVE: '日涨跌幅高于', DAY_CHANGE_BELOW: '日涨跌幅低于' }
export function fixed8(value: string): bigint {
  if (!/^-?\d{1,16}(?:\.\d{1,8})?$/.test(value)) throw new Error('阈值必须为最多 8 位小数的十进制数字，不能使用科学计数法')
  const negative = value.startsWith('-'), [integer = '', fraction = ''] = value.replace(/^-/, '').split('.')
  return (negative ? -1n : 1n) * BigInt(integer + fraction.padEnd(8, '0'))
}
export function newRuleDraft(): AlertRuleCreate { return { name: '', security_id: '', rule_type: 'PRICE_CROSS_UP', mode: 'OBSERVATION', threshold: '', reset_threshold: '', cooldown_seconds: 300, enabled: false } }
export function ruleDraft(rule: AlertRule): AlertRuleCreate { return { name: rule.name, security_id: rule.security_id, rule_type: rule.rule_type, mode: rule.mode, threshold: rule.threshold, reset_threshold: rule.reset_threshold, cooldown_seconds: rule.cooldown_seconds, enabled: rule.enabled } }
export function rulePayload(draft: AlertRuleCreate): AlertRuleCreate {
  const body = { ...draft, name: draft.name.trim(), threshold: draft.threshold.trim(), reset_threshold: draft.reset_threshold.trim() }
  if (!body.name || body.name.length > 80) throw new Error('规则名称须为 1–80 个字符')
  if (!body.security_id) throw new Error('请先选择证券')
  const threshold = fixed8(body.threshold), reset = fixed8(body.reset_threshold)
  if (body.rule_type.startsWith('PRICE_') && (threshold <= 0n || reset <= 0n)) throw new Error('价格阈值和重置阈值必须大于 0')
  const up = body.rule_type === 'PRICE_CROSS_UP' || body.rule_type === 'DAY_CHANGE_ABOVE'
  if (up ? reset >= threshold : reset <= threshold) throw new Error(up ? '重置阈值必须小于触发阈值' : '重置阈值必须大于触发阈值')
  if (!Number.isInteger(body.cooldown_seconds) || body.cooldown_seconds! < 0 || body.cooldown_seconds! > 86400) throw new Error('冷却时间须为 0–86400 的整数秒')
  if (body.mode === 'REALTIME' && body.enabled) throw new Error('源延迟未知，实时风控尚未验收；实时规则只能保存为停用')
  return body
}
export function decimalLabel(value: string | null | undefined): string {
  if (value == null) return '未覆盖'
  const [integer = '', fraction = ''] = value.split('.')
  const tail = fraction.replace(/0+$/, '')
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (tail ? `.${tail}` : '')
}
export function beijingTime(value: string | null | undefined): string { return value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—' }
