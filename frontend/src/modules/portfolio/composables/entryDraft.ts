import type { SecurityDTO } from '../../securities'
import type { PortfolioAccount, PortfolioEntryCreate } from '../types'
export const kinds = { DEPOSIT: '入金', WITHDRAWAL: '出金', BUY: '买入', SELL: '卖出', DIVIDEND: '分红', FEE: '费用' } as const
export type EntryKind = keyof typeof kinds
export const beijingNow = () => new Date(Date.now() + 8 * 3600_000).toISOString().slice(0, 16)
export const newDraft = () => ({ kind: 'DEPOSIT' as EntryKind, occurred_at: beijingNow(), quantity: '', price: '', amount: '', fee: '0', tax: '0', note: '' })
export type EntryDraft = ReturnType<typeof newDraft>
const decimal = /^(?:0|[1-9]\d{0,15})(?:\.\d{1,8})?$/
const units = (value: string) => { const [whole = '0', fraction = ''] = value.split('.'); return BigInt(whole) * 100000000n + BigInt(fraction.padEnd(8, '0')) }
export function entryPayload(draft: EntryDraft, security: SecurityDTO | null, account: PortfolioAccount, requestId: string): PortfolioEntryCreate {
  if (!account.is_active) throw new Error('账户已停用，请先启用账户。')
  const trade = draft.kind === 'BUY' || draft.kind === 'SELL'
  const needsSecurity = trade || draft.kind === 'DIVIDEND'
  if (needsSecurity && !security) throw new Error('请搜索并选择证券。')
  if (needsSecurity && security?.currency !== account.currency) throw new Error('证券币种与账户币种不一致，请切换账户或证券。')
  if (needsSecurity && security?.status !== 'ACTIVE') throw new Error('请选择有效证券。')
  const quantity = trade ? draft.quantity.trim() : '0', price = trade ? draft.price.trim() : '0'
  const amount = trade ? '0' : draft.amount.trim()
  const fee = needsSecurity ? draft.fee.trim() : '0', tax = needsSecurity ? draft.tax.trim() : '0'
  for (const value of [quantity, price, amount, fee, tax]) if (!decimal.test(value)) throw new Error('金额与数量须为非负十进制数，整数最多16位、小数最多8位。')
  if (trade ? units(quantity) <= 0n || units(price) <= 0n : units(amount) <= 0n) throw new Error(trade ? '数量和成交价必须大于0。' : '金额必须大于0。')
  if (trade && security?.market !== 'US' && units(quantity) % 100000000n !== 0n) throw new Error('沪深京和港股数量须为整数股/份，不是手数。')
  if (draft.kind === 'DIVIDEND' && units(fee) + units(tax) > units(amount)) throw new Error('分红费用与税费合计不能超过分红金额。')
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(draft.occurred_at)) throw new Error('请输入北京时间。')
  const date = new Date(`${draft.occurred_at}:00+08:00`)
  if (!Number.isFinite(date.getTime()) || date.getTime() > Date.now() || draft.occurred_at.slice(0, 4) < '1900' || new Date(date.getTime() + 8 * 3600_000).toISOString().slice(0, 16) !== draft.occurred_at) throw new Error('发生时间须为1900年起的有效北京时间，且不能晚于现在。')
  if (draft.note.trim().length > 500) throw new Error('备注最多500字。')
  return { request_id: requestId, kind: draft.kind, occurred_at: date.toISOString(), security_id: needsSecurity ? security!.id : null, quantity, price, amount, fee, tax, note: draft.note.trim() }
}
