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
        (
            "market_calendar",
            "交易日历",
            "B",
            "foundation",
            "2026常规时段、午休、提前收市及临时闭市覆盖",
        ),
        ("watchlist", "自选管理", "C", "foundation", "自选分组、证券关注及排序管理"),
        (
            "portfolio", "资产持仓", "A", "foundation",
            "单币种账户、审计账本、冲正与移动平均成本核算",
        ),
        (
            "indicators",
            "技术指标",
            "A",
            "foundation",
            "日线及沪深15分钟指标观察、版本化参数配置；预警未启用",
        ),
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
