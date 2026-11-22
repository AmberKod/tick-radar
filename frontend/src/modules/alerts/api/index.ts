import { apiGet, apiPost, apiPut, apiDelete, type RequestOptions } from '../../../shared/api/client'
import type { AlertRule, AlertRuleCreate, AlertRuleUpdate, AlertRuleList, AlertEventPage, AlertPreview } from '../types'
const path = (id: string) => `/alerts/rules/${encodeURIComponent(id)}`
export const listRules = (options?: RequestOptions) => apiGet<AlertRuleList>('/alerts/rules', options)
export const getRule = (id: string, options?: RequestOptions) => apiGet<AlertRule>(path(id), options)
export const createRule = (body: AlertRuleCreate, options?: RequestOptions) => apiPost<AlertRule>('/alerts/rules', body, options)
export const updateRule = (id: string, body: AlertRuleUpdate, options?: RequestOptions) => apiPut<AlertRule>(path(id), body, options)
export const deleteRule = (id: string, version: number, options?: RequestOptions) => apiDelete(`${path(id)}?version=${version}`, options)
export const resetRule = (id: string, version: number, options?: RequestOptions) => apiPost<AlertRule>(`${path(id)}/reset`, { version }, options)
export const previewRule = (id: string, options?: RequestOptions) => apiPost<AlertPreview>(`${path(id)}/preview`, undefined, options)
export const getEvents = (page: number, ruleId = '', options?: RequestOptions) => apiGet<AlertEventPage>(`/alerts/events?page=${page}&page_size=20${ruleId ? `&rule_id=${encodeURIComponent(ruleId)}` : ''}`, options)
