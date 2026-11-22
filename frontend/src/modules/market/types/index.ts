import type { components } from '../../../generated/api-schema'
export type IndicatorParameters = components['schemas']['IndicatorParameters']
export type IndicatorPoint = components['schemas']['IndicatorPoint']
export type DailyIndicatorsResponse = components['schemas']['DailyIndicatorsResponse']
export type HistoryResponse = components['schemas']['HistoryResponse']
export type HistoryBar = components['schemas']['HistoryBar']
export type HistoryAdjustment = HistoryResponse['adjustment']
export type QuoteDTO = components['schemas']['QuoteDTO']
export type Market = QuoteDTO['market']
export type MarketCalendarStatus = components['schemas']['MarketCalendarStatus']
export type MarketState = NonNullable<QuoteDTO['market_state']>
export type MarketCalendarStatuses = { statuses: MarketCalendarStatus[]; checked_at: string }
export const marketStateLabels: Record<MarketState, string> = {
  REGULAR_SESSION: '常规交易', LUNCH_BREAK: '午间休市', OUTSIDE_REGULAR_SESSION: '常规时段外', CLOSED: '休市', UNKNOWN: '日历未知',
}
export type Currency = QuoteDTO['currency']
export type QuoteList = components['schemas']['QuotesResponse']
export type SecurityFromQuoteInput = components['schemas']['SecurityFromQuote']
export type SecurityFromQuote = components['schemas']['SecurityDTO']
export interface Group { id: string; name: string; position: number }
export interface Item { id: string; group_id: string; note: string | null; security: { id: string; symbol: string; name: string; exchange: string; security_type: string; currency: Currency } }
export const marketLabels: Record<Market, string> = { CN: '沪深京', HK: '港股', US: '美股' }
