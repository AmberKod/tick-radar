import { apiGet, apiPost, apiPut, type RequestOptions } from '../../../shared/api/client'
import type { CreateSecurity, Market, SecurityDTO, SecurityPage, UpdateSecurity } from '../types'
export function searchSecurities(q = '', market: Market | '' = '', page = 1, options?: RequestOptions) {
  const params = new URLSearchParams({ q, page: String(page), page_size: '20' })
  if (market) params.set('market', market)
  return apiGet<SecurityPage>(`/securities?${params}`, options)
}
export const createSecurity = (body: CreateSecurity) => apiPost<SecurityDTO>('/securities', body)
export const updateSecurity = (id: string, body: UpdateSecurity) => apiPut<SecurityDTO>(`/securities/${id}`, body)
