import { apiGet } from '../../../shared/api/client'
import type { ModulesResponse, SystemStatus } from '../types'

export const systemApi = {
  status: (signal?: AbortSignal) => apiGet<SystemStatus>('/system/status', { signal }),
  modules: (signal?: AbortSignal) => apiGet<ModulesResponse>('/system/modules', { signal }),
}
