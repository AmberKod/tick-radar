import { apiGet, apiPost, apiPut, type RequestOptions } from '../../../shared/api/client'
import type { NotificationInboxPage, NotificationMessage, NotificationOutbox, NotificationOutboxPage, NotificationDeliveryList, NotificationTestRequest } from '../types'
const outbox = (id: string) => `/notifications/outbox/${encodeURIComponent(id)}`
export const getInbox = (page: number, unreadOnly: boolean, options?: RequestOptions) => apiGet<NotificationInboxPage>(`/notifications/inbox?page=${page}&page_size=20&unread_only=${unreadOnly}`, options)
export const markRead = (id: string, options?: RequestOptions) => apiPut<NotificationMessage>(`/notifications/inbox/${encodeURIComponent(id)}/read`, undefined, options)
export const markAllRead = (options?: RequestOptions) => apiPost<{ updated: number }>('/notifications/inbox/read-all', undefined, options)
export const getOutbox = (page: number, status: string, options?: RequestOptions) => apiGet<NotificationOutboxPage>(`/notifications/outbox?page=${page}&page_size=20${status ? `&status=${encodeURIComponent(status)}` : ''}`, options)
export const getDeliveries = (id: string, options?: RequestOptions) => apiGet<NotificationDeliveryList>(`${outbox(id)}/deliveries`, options)
export const retryOutbox = (id: string, options?: RequestOptions) => apiPost<NotificationOutbox>(`${outbox(id)}/retry`, undefined, options)
export const testNotification = (body: NotificationTestRequest, options?: RequestOptions) => apiPost<NotificationOutbox>('/notifications/test', body, options)
