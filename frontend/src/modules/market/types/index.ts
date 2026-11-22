import type { components } from '../../../generated/api-schema'
export type QuoteDTO = components['schemas']['QuoteDTO']
export type Market = QuoteDTO['market']
export type Currency = QuoteDTO['currency']
export type QuoteList = components['schemas']['QuotesResponse']
export type SecurityFromQuoteInput = components['schemas']['SecurityFromQuote']
export type SecurityFromQuote = components['schemas']['SecurityDTO']
export interface Group { id: string; name: string; position: number }
export interface Item { id: string; group_id: string; note: string | null; security: { id: string; symbol: string; name: string; exchange: string; security_type: string; currency: Currency } }
export const marketLabels: Record<Market, string> = { CN: '沪深京', HK: '港股', US: '美股' }
