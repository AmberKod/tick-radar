import { apiDelete, apiGet, apiPost, apiPut, type RequestOptions } from '../../../shared/api/client'
import type { Group, Item, Groups, Items } from '../types'
export const getGroups = (options?: RequestOptions) => apiGet<Groups>('/watchlist-groups', options)
export const createGroup = (name: string) => apiPost<Group>('/watchlist-groups', { name })
export const renameGroup = (id: string, name: string) => apiPut<Group>(`/watchlist-groups/${id}`, { name })
export const deleteGroup = (id: string) => apiDelete(`/watchlist-groups/${id}`)
export const orderGroups = (ids: string[]) => apiPut<Groups>('/watchlist-groups/order', { ids })
export const getItems = (groupId: string, options?: RequestOptions) => apiGet<Items>(`/watchlists?${new URLSearchParams({ group_id: groupId })}`, options)
export const addItem = (group_id: string, security_id: string) => apiPost<Item>('/watchlists', { group_id, security_id })
export const updateNote = (id: string, note: string) => apiPut<Item>(`/watchlists/${id}`, { note })
export const deleteItem = (id: string) => apiDelete(`/watchlists/${id}`)
export const moveItem = (id: string, group_id: string) => apiPost<Item>(`/watchlists/${id}/move`, { group_id })
export const orderItems = (group_id: string, ids: string[]) => apiPut<Items>('/watchlists/order', { group_id, ids })
