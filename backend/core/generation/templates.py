from typing import Dict, List, Any
from core.schemas.dashboard import LayoutZone, LayoutConfig


class LayoutTemplates:
    """
    布局模板库：
    预设符合原型图（左中右+下结构）的栅格坐标系统。
    采用 12 列栅格系统 (React-Grid-Layout 标准)。
    """

    # --- 核心模板：标准时空分析看板 ---
    # 结构：顶部时间控制 + 中间 8 列地图 + 右侧 4 列双表 + 下方全宽洞察
    GOLDEN_SPATIO_TEMPORAL = {
        "template_id": "st_standard_v1",
        "description": "标准时空分析布局：顶部时间轴 + 中心地图 + 右侧双表 + 下方洞察",
        "slots": {
            # [新增] 顶部导航/时间控制器：全宽，高度较小
            LayoutZone.TOP_NAV: [
                LayoutConfig(zone=LayoutZone.TOP_NAV, x=0, y=0, w=12, h=1.5)
            ],
            # 主地图区域：y 坐标下移，避开顶部导航
            LayoutZone.CENTER_MAIN: [
                LayoutConfig(zone=LayoutZone.CENTER_MAIN, x=0, y=1.5, w=8, h=9)
            ],
            # 右侧边栏：y 坐标下移
            LayoutZone.RIGHT_SIDEBAR: [
                LayoutConfig(zone=LayoutZone.RIGHT_SIDEBAR, x=8, y=1.5, w=4, h=4.5),  # 右上槽位
                LayoutConfig(zone=LayoutZone.RIGHT_SIDEBAR, x=8, y=6.0, w=4, h=4.5)  # 右下槽位
            ],
            # 下方洞察区域：紧跟地图下方
            LayoutZone.BOTTOM_INSIGHT: [
                LayoutConfig(zone=LayoutZone.BOTTOM_INSIGHT, x=0, y=10.5, w=12, h=3)
            ]
        }
    }

    # --- 备选模板：纯图表对比看板 ---
    CHART_ONLY_GRID = {
        "template_id": "chart_grid_v1",
        "description": "纯统计图表布局：左右平分",
        "slots": {
            LayoutZone.RIGHT_SIDEBAR: [
                LayoutConfig(zone=LayoutZone.RIGHT_SIDEBAR, x=0, y=0, w=6, h=6),
                LayoutConfig(zone=LayoutZone.RIGHT_SIDEBAR, x=6, y=0, w=6, h=6)
            ],
            LayoutZone.BOTTOM_INSIGHT: [
                LayoutConfig(zone=LayoutZone.BOTTOM_INSIGHT, x=0, y=6, w=12, h=4)
            ]
        }
    }

    @classmethod
    def get_template_prompt(cls) -> str:
        """
        生成给 LLM 看的布局说明，作为 Prompt 的一部分。
        """
        return """
        === 布局区域守则 (Layout Rules) ===
        1. TOP_NAV: 只能放置 1 个 'timeline_controller' 组件 (如果数据含时间维度)。
        2. CENTER_MAIN: 只能放置 1 个 'map' 类型组件。
        3. RIGHT_SIDEBAR: 最多放置 2 个 'chart' 类型组件。
        4. BOTTOM_INSIGHT: 放置 'insight' 或 'table' 类型组件。

        请为每个组件分配对应的 'zone' 属性，系统会自动将其对齐到 UI 预设位置。
        """

    @classmethod
    def apply_layout(cls, components: List[Any], template_id: str = "st_standard_v1") -> None:
        template = cls.GOLDEN_SPATIO_TEMPORAL if template_id == "st_standard_v1" else cls.CHART_ONLY_GRID
        slots = template["slots"]
        counters = {zone: 0 for zone in LayoutZone}

        for comp in components:
            zone = comp.layout.zone
            if zone in slots:
                idx = counters[zone]
                if idx < len(slots[zone]):
                    config = slots[zone][idx]
                    comp.layout.x, comp.layout.y = config.x, config.y
                    comp.layout.w, comp.layout.h = config.w, config.h
                else:
                    # 溢出处理：自动向下堆叠，防止重叠
                    last = slots[zone][-1]
                    comp.layout.x = last.x
                    comp.layout.y = last.y + (last.h * (idx - len(slots[zone]) + 1))
                    comp.layout.w, comp.layout.h = last.w, last.h
                counters[zone] += 1