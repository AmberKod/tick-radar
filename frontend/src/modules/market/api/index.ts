import { apiGet, apiPost, type RequestOptions } from '../../../shared/api/client'
import type { Group, HistoryAdjustment, HistoryResponse, Item, MarketCalendarStatuses, QuoteDTO, QuoteList, SecurityFromQuote, SecurityFromQuoteInput } from '../types'
export const getHistory = (symbol: string, limit: number, adjustment: HistoryAdjustment, options?: RequestOptions) => apiGet<HistoryResponse>(`/market/history?${new URLSearchParams({ symbol, limit: String(limit), adjustment })}`, { timeoutMs: 15_000, ...options })
export const getCalendarStatuses = (options?: RequestOptions) => apiGet<MarketCalendarStatuses>('/market-calendar/statuses', options)
export const getQuote = (symbol: string, options?: RequestOptions) => apiGet<QuoteDTO>(`/market/quote?${new URLSearchParams({ symbol })}`, options)
export const getQuotes = (symbols: string[], options?: RequestOptions) => apiGet<QuoteList>(`/market/quotes?${new URLSearchParams({ symbols: symbols.join(',') })}`, options)
export const refreshQuotes = (symbols: string[]) => apiPost<QuoteList>('/market/refresh', { symbols })
export const getGroups = (options?: RequestOptions) => apiGet<{ groups: Group[] }>('/watchlist-groups', options)
export const getItems = (groupId: string, options?: RequestOptions) => apiGet<{ items: Item[] }>(`/watchlists?${new URLSearchParams({ group_id: groupId })}`, options)
export const createGroup = (name: string) => apiPost<Group>('/watchlist-groups', { name })
export const createSecurityFromQuote = (body: SecurityFromQuoteInput) => apiPost<SecurityFromQuote>('/securities/from-quote', body)
export const addItem = (group_id: string, security_id: string) => apiPost<Item>('/watchlists', { group_id, security_id })
