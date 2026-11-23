import type { PortfolioAccount } from '../types'
import type { PortfolioTransferCreate } from '../types/transfers'
import { beijingDate, beijingNow } from './entryDraft'
const decimal = /^(?:0|[1-9]\d{0,15})(?:\.\d{1,8})?$/
export const cashUnits = (value: string) => {
  if (!decimal.test(value)) throw new Error('金额须为非负十进制数，整数最多16位、小数最多8位。')
  const [whole = '0', fraction = ''] = value.split('.')
  return BigInt(whole) * 100000000n + BigInt(fraction.padEnd(8, '0'))
}
const fixed = (value: bigint, places: number) => { const text = value.toString().padStart(places + 1, '0'); return `${text.slice(0, -places)}.${text.slice(-places)}` }
export const sourceTotal = (amount: string, fee: string) => fixed(cashUnits(amount.trim()) + cashUnits(fee.trim()), 8)
export function actualRate(source: string, target: string) {
  const denominator = cashUnits(source.trim()), numerator = cashUnits(target.trim()) * 1000000000000n
  if (denominator <= 0n) throw new Error('划出金额必须大于0。')
  let quotient = numerator / denominator
  const remainder = numerator % denominator
  if (remainder * 2n > denominator || (remainder * 2n === denominator && quotient % 2n !== 0n)) quotient++
  return fixed(quotient, 12)
}
export const rateLabel = (value: string) => /^0\.0+$/.test(value) ? '< 0.000000000001（小于显示精度）' : value
export const newTransferDraft = (source = '') => ({ source_account_id: source, target_account_id: '', occurred_at: beijingNow(), source_amount: '', target_amount: '', source_fee: '0', note: '' })
export type TransferDraft = ReturnType<typeof newTransferDraft>
export function transferPayload(draft: TransferDraft, accounts: PortfolioAccount[], requestId: string): PortfolioTransferCreate {
  const source = accounts.find(item => item.id === draft.source_account_id), target = accounts.find(item => item.id === draft.target_account_id)
  if (!source || !target) throw new Error('请明确选择划出和划入账户。')
  if (source.id === target.id) throw new Error('划出与划入账户不能相同。')
  if (!source.is_active || !target.is_active) throw new Error('两端账户必须均为启用状态。')
  const sourceAmount = draft.source_amount.trim(), targetAmount = source.currency === target.currency ? sourceAmount : draft.target_amount.trim(), sourceFee = draft.source_fee.trim()
  if (cashUnits(sourceAmount) <= 0n || cashUnits(targetAmount) <= 0n) throw new Error('划出和实际到账金额必须大于0。')
  cashUnits(sourceFee)
  if (draft.note.trim().length > 500) throw new Error('备注最多500字。')
  return { request_id: requestId, source_account_id: source.id, target_account_id: target.id, occurred_at: beijingDate(draft.occurred_at), source_amount: sourceAmount, target_amount: targetAmount, source_fee: sourceFee, note: draft.note.trim() }
}
