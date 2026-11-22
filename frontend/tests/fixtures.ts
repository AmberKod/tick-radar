import type { ModulesResponse, SystemStatus } from '../src/modules/system/types'
export const statusFixture: SystemStatus = {
  status: 'degraded', checked_at: '2026-11-22T08:00:00Z', version: '0.1.0',
  components: {
    api: { status: 'healthy', detail: '服务正常' },
    mysql: { status: 'unhealthy', detail: '数据库连接失败' },
    redis: { status: 'healthy', detail: null },
    worker: { status: 'unknown', detail: '尚无心跳' },
  },
  tasks: [{ name: 'market_ingestion', status: 'disabled', detail: '阶段0禁用采集' }],
  market_data_enabled: false,
}
export const modulesFixture: ModulesResponse = { modules: [
  { name: 'system', label: '系统管理', tier: 'A', status: 'foundation', description: '系统状态检查' },
  { name: 'market_data', label: '行情数据', tier: 'A', status: 'planned', description: '数据采集' },
] }
