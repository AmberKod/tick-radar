import type { components } from '../../../generated/api-schema'

export type Market = 'CN' | 'HK' | 'US'
export type SecurityDTO = components['schemas']['SecurityDTO']
export type SecurityPage = components['schemas']['SecurityPage']
export type CreateSecurity = components['schemas']['SecurityCreate']
export type UpdateSecurity = components['schemas']['SecurityUpdate']
export const exchanges: Record<Market, CreateSecurity['exchange'][]> = { CN: ['SSE', 'SZSE', 'BSE'], HK: ['HKEX'], US: ['NASDAQ', 'NYSE', 'AMEX'] }
export const currencies: Record<Market, string> = { CN: 'CNY', HK: 'HKD', US: 'USD' }
export function validSymbol(symbol: string, market: Market) {
  return symbol.length <= 40 && { CN: /^CN:[0-9]{6}$/, HK: /^HK:[0-9]{5}$/, US: /^US:[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*$/ }[market].test(symbol.trim().toUpperCase())
}
