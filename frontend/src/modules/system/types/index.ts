import type { components } from '../../../generated/api-schema'

// DTO 统一从后端契约派生，模块内只补充 UI 专用类型。
export type ComponentStatus = components['schemas']['ComponentStatus']['status']
export type SystemComponent = components['schemas']['ComponentStatus']
export type SystemStatus = components['schemas']['SystemStatus']
export type SystemModule = components['schemas']['ModuleInfo']
export type ModulesResponse = components['schemas']['ModulesResponse']
