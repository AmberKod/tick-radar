import type { Component } from 'vue'
import { LayoutDashboard, ChartNoAxesCombined, Star, BriefcaseBusiness, Activity, Bell, ScanSearch, Settings2 } from 'lucide-vue-next'

export interface WorkspaceModule {
  key: string; path: string; label: string; english: string; icon: Component
  enabled: boolean; description: string; scope: string[]
}

export const workspaceModules: WorkspaceModule[] = [
  { key: 'market_data', path: '/market', label: '行情看板', english: 'Market', icon: ChartNoAxesCombined, enabled: true,
    description: '查询沪深京、港股和美股公共报价，查看自选行情。', scope: ['公共报价查询', '自选行情看板', '证券登记'] },
  { key: 'market_history', path: '/market/history', label: '历史K线', english: 'History', icon: ChartNoAxesCombined, enabled: true,
    description: '查询公共历史日线与原始成交量。', scope: ['历史日线', '复权选择', '原始成交量'] },
  { key: 'overview', path: '/system', label: '系统概览', english: 'Overview', icon: LayoutDashboard, enabled: true,
    description: '基础服务状态与模块接入进度', scope: [] },
  { key: 'securities', path: '/securities', label: '证券主数据', english: 'Securities', icon: ScanSearch, enabled: true,
    description: '手工维护证券身份与基础资料。', scope: ['证券查询', '手工录入', '资料维护'] },
  { key: 'watchlist', path: '/watchlist', label: '自选股', english: 'Watchlist', icon: Star, enabled: true,
    description: '集中管理关注的证券，持续追踪市场变化。', scope: ['自选分组', '关注证券管理', '关联行情展示'] },
  { key: 'portfolio', path: '/portfolio', label: '资产组合', english: 'Portfolio', icon: BriefcaseBusiness, enabled: true,
    description: '建立组合视图，了解资产配置与表现。', scope: ['组合管理', '持仓记录', '组合表现'] },
  { key: 'indicators', path: '/indicators', label: '指标中心', english: 'Indicators', icon: Activity, enabled: false,
    description: '以统一的指标计算能力支持观察与分析。', scope: ['指标定义', '计算任务', '指标结果'] },
  { key: 'alerts', path: '/alerts', label: '智能预警', english: 'Alerts', icon: Bell, enabled: false,
    description: '在数据与任务能力就绪后，配置预警条件与通知。', scope: ['预警规则', '触发记录', '通知通道'] },
  { key: 'analytics', path: '/analytics', label: '分析研究', english: 'Analytics', icon: ScanSearch, enabled: false,
    description: '基于真实数据开展证券与组合分析。', scope: ['证券分析', '组合分析', '分析结果'] },
  { key: 'system', path: '/settings', label: '系统设置', english: 'Settings', icon: Settings2, enabled: false,
    description: '查看并管理数据接入与系统运行配置。', scope: ['数据源配置', '任务配置', '通知设置'] },
]
