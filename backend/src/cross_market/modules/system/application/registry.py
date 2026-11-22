from cross_market.modules.system.application.schemas import ModuleInfo, TaskStatus

MODULES = tuple(
    ModuleInfo(name=name, label=label, tier=tier, status=status, description=description)
    for name, label, tier, status, description in [
        ("securities", "证券主数据", "B", "foundation", "手工证券主数据及统一代码管理"),
        (
            "market_data",
            "行情数据",
            "A",
            "foundation",
            "真实报价观察、共享缓存与自选采集；实时预警未启用",
        ),
        ("market_calendar", "交易日历", "B", "planned", "交易时段及节假日管理尚未实施"),
        ("watchlist", "自选管理", "C", "foundation", "自选分组、证券关注及排序管理"),
        ("portfolio", "资产持仓", "A", "planned", "持仓及交易事实管理尚未实施"),
        ("indicators", "技术指标", "A", "planned", "指标计算尚未实施"),
        ("alerts", "监控告警", "A", "planned", "告警规则及触发判断尚未实施"),
        ("notifications", "通知渠道", "C", "planned", "通知投递尚未实施"),
        ("analytics", "分析统计", "B", "planned", "资产分析及统计尚未实施"),
        ("system", "系统管理", "C", "foundation", "状态诊断、模块注册和配置存储基础"),
    ]
)


def disabled_tasks() -> list[TaskStatus]:
    return [
        TaskStatus(name="quote_collector", detail="行情采集尚未实施，任务未注册"),
        TaskStatus(name="alert_engine", detail="告警引擎尚未实施，任务未注册"),
    ]
