import { createRouter, createWebHistory } from 'vue-router'
import { workspaceModules } from './modules'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/market' },
    { path: '/system', component: () => import('../../modules/system/views/SystemOverview.vue'), meta: { title: '系统概览' } },
    { path: '/market', component: () => import('../../modules/market').then(module => module.MarketDashboard), meta: { title: '行情看板' } },
    { path: '/market/history', component: () => import('../../modules/market/views/HistoryPage.vue'), meta: { title: '历史日线' } },
    { path: '/securities', component: () => import('../../modules/securities').then(module => module.SecuritiesPage), meta: { title: '证券主数据', private: true } },
    { path: '/watchlist', component: () => import('../../modules/watchlist').then(module => module.WatchlistPage), meta: { title: '自选股', private: true } },
    { path: '/portfolio', component: () => import('../../modules/portfolio').then(module => module.PortfolioPage), meta: { title: '资产组合', private: true } },
    { path: '/alerts', component: () => import('../../modules/alerts').then(module => module.AlertsPage), meta: { title: '预警与通知', private: true } },
    ...workspaceModules.filter(module => !['overview', 'market_data', 'market_history', 'securities', 'watchlist', 'portfolio', 'alerts'].includes(module.key)).map(module => ({
      path: module.path,
      component: () => import('../../shared/components/ModulePlaceholderPage.vue'),
      props: { module }, meta: { title: module.label },
    })),
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
router.afterEach(to => { document.title = `TickRadar · ${String(to.meta.title || '工作台')}` })
