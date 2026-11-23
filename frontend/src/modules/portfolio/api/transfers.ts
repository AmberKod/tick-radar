import { apiGet, apiPost, type RequestOptions } from '../../../shared/api/client'
import type { PortfolioReversalCreate } from '../types'
import type { PortfolioTransfer, PortfolioTransferCreate, PortfolioTransferPage } from '../types/transfers'
const root = '/portfolio/transfers'
export const getTransfers = (page: number, accountId: string, options?: RequestOptions) => apiGet<PortfolioTransferPage>(`${root}?page=${page}&page_size=20${accountId ? `&account_id=${encodeURIComponent(accountId)}` : ''}`, options)
export const getTransfer = (id: string, options?: RequestOptions) => apiGet<PortfolioTransfer>(`${root}/${encodeURIComponent(id)}`, options)
export const createTransfer = (body: PortfolioTransferCreate, options?: RequestOptions) => apiPost<PortfolioTransfer>(root, body, options)
export const reverseTransfer = (id: string, body: PortfolioReversalCreate, options?: RequestOptions) => apiPost<PortfolioTransfer>(`${root}/${encodeURIComponent(id)}/reverse`, body, options)
