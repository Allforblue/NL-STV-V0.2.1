from typing import Dict, List, Any
from core.schemas.dashboard import LayoutZone, LayoutConfig


class LayoutTemplates:
    """
    布局模板库：
    预设符合原型图（左中右+下结构）的栅格坐标系统。
    采用 12 列栅格系统 (React-Grid-Layout 标准)。
    """

    # --- 核心模板：标准时空分析看板（即你的原型图） ---
    # 结构：中间占据 8 列宽的大地图，右侧 4 列宽摆放 2 个图表，下方全宽摆放洞察。
    GOLDEN_SPATIO_TEMPORAL = {
        "template_id": "st_standard_v1",
        "description": "标准时空分析布局：中心地图 + 右侧双表 + 下方洞察",
        "slots": {
            # 主地图区域：占据左侧和中间大部分空间
            LayoutZone.CENTER_MAIN: [
                LayoutConfig(zone=LayoutZone.CENTER_MAIN, x=0, y=0, w=8, h=9)
            ],
            # 右侧边栏：垂直摆放两个槽位
            LayoutZone.RIGHT_SIDEBAR: [
                LayoutConfig(zone=LayoutZone.RIGHT_SIDEBAR, x=8, y=0, w=4, h=4.5),  # 右上槽位
                LayoutConfig(zone=LayoutZone.RIGHT_SIDEBAR, x=8, y=4.5, w=4, h=4.5)  # 右下槽位
            ],
            # 下方洞察区域：全宽展示
            LayoutZone.BOTTOM_INSIGHT: [
                LayoutConfig(zone=LayoutZone.BOTTOM_INSIGHT, x=0, y=9, w=12, h=3)
            ]
        }
    }

    # --- 备选模板：纯图表对比看板 ---
    # 结构：如果不含地理信息，则切换为左右平分图表的布局
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
        1. CENTER_MAIN: 只能放置 1 个 'map' 类型组件。
        2. RIGHT_SIDEBAR: 最多放置 2 个 'chart' 类型组件。
        3. BOTTOM_INSIGHT: 必须放置 1 个 'insight' 类型组件。

        请为每个组件分配对应的 'zone' 属性，系统会自动将其对齐到 UI 预设位置。
        """

    @classmethod
    def apply_layout(cls, components: List[Any], template_id: str = "st_standard_v1") -> None:
        """
        [工具方法] 后端逻辑层调用：
        根据 LLM 指定的 zone，将组件强制对齐到物理坐标。
        """
        template = cls.GOLDEN_SPATIO_TEMPORAL if template_id == "st_standard_v1" else cls.CHART_ONLY_GRID
        slots = template["slots"]

        # 记录每个区域已经使用了多少个槽位
        counters = {zone: 0 for zone in LayoutZone}

        for comp in components:
            zone = comp.layout.zone
            if zone in slots and counters[zone] < len(slots[zone]):
                # 赋予物理坐标
                target_config = slots[zone][counters[zone]]
                comp.layout.x = target_config.x
                comp.layout.y = target_config.y
                comp.layout.w = target_config.w
                comp.layout.h = target_config.h
                counters[zone] += 1