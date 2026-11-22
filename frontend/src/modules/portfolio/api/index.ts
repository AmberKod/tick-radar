import { apiGet, apiPost, apiPut, type RequestOptions } from '../../../shared/api/client'
import type { PortfolioAccount, PortfolioAccountCreate, PortfolioAccountUpdate, PortfolioEntry, PortfolioEntryCreate, PortfolioEntryPage, PortfolioReversalCreate, PortfolioSummary, PortfolioValuationResponse } from '../types'
const root = '/portfolio/accounts'
const accountPath = (id: string) => `${root}/${encodeURIComponent(id)}`
export const getAccounts = (options?: RequestOptions) => apiGet<{ items: PortfolioAccount[] }>(root, options)
export const createAccount = (body: PortfolioAccountCreate, options?: RequestOptions) => apiPost<PortfolioAccount>(root, body, options)
export const updateAccount = (id: string, body: PortfolioAccountUpdate, options?: RequestOptions) => apiPut<PortfolioAccount>(accountPath(id), body, options)
export const getSummary = (id: string, options?: RequestOptions) => apiGet<PortfolioSummary>(`${accountPath(id)}/summary`, options)
export const getLedger = (id: string, page: number, options?: RequestOptions) => apiGet<PortfolioEntryPage>(`${accountPath(id)}/ledger?page=${page}&page_size=20`, options)
export const getValuation = (id: string, options?: RequestOptions) => apiGet<PortfolioValuationResponse>(`${accountPath(id)}/valuation`, options)
export const createEntry = (id: string, body: PortfolioEntryCreate, options?: RequestOptions) => apiPost<PortfolioEntry>(`${accountPath(id)}/entries`, body, options)
export const reverseEntry = (id: string, entry: string, body: PortfolioReversalCreate, options?: RequestOptions) => apiPost<PortfolioEntry>(`${accountPath(id)}/entries/${encodeURIComponent(entry)}/reverse`, body, options)
