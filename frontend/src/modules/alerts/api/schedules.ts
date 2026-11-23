import { apiGet, apiPost, apiPut, apiDelete, type RequestOptions } from '../../../shared/api/client'
import type { Schedule, ScheduleCreate, ScheduleUpdate, ScheduleList, SchedulePreview, ScheduleRunPage } from '../types/schedules'
const path = (id: string) => `/alerts/schedules/${encodeURIComponent(id)}`
export const listSchedules = (options?: RequestOptions) => apiGet<ScheduleList>('/alerts/schedules', options)
export const getSchedule = (id: string, options?: RequestOptions) => apiGet<Schedule>(path(id), options)
export const createSchedule = (body: ScheduleCreate, options?: RequestOptions) => apiPost<Schedule>('/alerts/schedules', body, options)
export const updateSchedule = (id: string, body: ScheduleUpdate, options?: RequestOptions) => apiPut<Schedule>(path(id), body, options)
export const deleteSchedule = (id: string, version: number, options?: RequestOptions) => apiDelete(`${path(id)}?version=${version}`, options)
export const previewSchedule = (id: string, options?: RequestOptions) => apiPost<SchedulePreview>(`${path(id)}/preview`, undefined, options)
export const getScheduleRuns = (page = 1, scheduleId = '', options?: RequestOptions) => apiGet<ScheduleRunPage>(`/alerts/schedule-runs?page=${page}&page_size=20${scheduleId ? `&schedule_id=${encodeURIComponent(scheduleId)}` : ''}`, options)
