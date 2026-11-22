import { apiGet } from '../../../shared/api/client'
import type { components } from '../../../generated/api-schema'
export const verifySession = (signal: AbortSignal) => apiGet<components['schemas']['SessionStatus']>('/auth/session', { signal })
