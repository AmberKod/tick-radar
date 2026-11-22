import { apiDelete, apiGet, apiPost, apiPut, type RequestOptions } from '../../../shared/api/client'
import type { IndicatorProfile, IndicatorProfileCreate, IndicatorProfileUpdate, IndicatorProfileList } from '../types'

const path = '/indicators/profiles'
export const listProfiles = (options?: RequestOptions) => apiGet<IndicatorProfileList>(path, options)
export const getProfile = (id: string, options?: RequestOptions) => apiGet<IndicatorProfile>(`${path}/${encodeURIComponent(id)}`, options)
export const createProfile = (data: IndicatorProfileCreate, options?: RequestOptions) => apiPost<IndicatorProfile>(path, data, options)
export const updateProfile = (id: string, data: IndicatorProfileUpdate, options?: RequestOptions) => apiPut<IndicatorProfile>(`${path}/${encodeURIComponent(id)}`, data, options)
export const deleteProfile = (id: string, version: number, options?: RequestOptions) => apiDelete(`${path}/${encodeURIComponent(id)}?version=${version}`, options)
