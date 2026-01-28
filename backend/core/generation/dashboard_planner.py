import logging
import json
from typing import Dict, Any, List, Optional

from core.llm.AI_client import AIClient
from core.schemas.dashboard import (
    DashboardSchema, DashboardComponent, ComponentType,
    LayoutZone, LayoutConfig, ComponentLink, InteractionType, ChartType, InsightCard
)
from core.generation.templates import LayoutTemplates

logger = logging.getLogger(__name__)


class DashboardPlanner:
    """
    看板编排器 (V4.0 时空增强版)：
    1. 动态感知数据基数与【时间跨度/粒度】，自动匹配最优图表选型（折线图、趋势图）。
    2. 强制规划全局时间轴与组件重采样粒度 (time_bucket)。
    3. 保持 V3.1 的鲁棒补全方案。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    def _unwrap_llm_json(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """从 LLM 返回的各类包裹层中提取标准的 Dashboard JSON"""
        required_keys = {"dashboard_id", "title", "components"}
        if not required_keys.issubset(set(data.keys())):
            for wrapper in ['dashboard', 'plan', 'result', 'output']:
                if wrapper in data and isinstance(data[wrapper], dict):
                    return data[wrapper]
        return data

    def _build_system_prompt(self, summaries: List[Dict[str, Any]]) -> str:
        # 提取动态元数据上下文 (包含时间维度)
        context_str = ""
        for s in summaries:
            var_name = s.get('variable_name')
            sem_analysis = s.get('semantic_analysis', {})
            col_meta = sem_analysis.get('column_metadata', {})
            temp_context = sem_analysis.get('temporal_context', {})

            context_str += f"\n### 数据集变量: {var_name}\n"
            # 注入时间上下文
            if temp_context:
                context_str += (
                    f"- 时间维度: 主轴 `{temp_context.get('primary_time_col')}` | "
                    f"跨度: {temp_context.get('time_span')} | "
                    f"建议聚合频率: `{temp_context.get('suggested_resampling')}`\n"
                )

            for col_raw, meta in col_meta.items():
                context_str += (
                    f"- 原始列名: `{col_raw}` | 中文概念: '{meta.get('concept_name')}' | "
                    f"基数: {meta.get('cardinality')} | 标签: {meta.get('semantic_tag')}\n"
                )

        layout_rules = LayoutTemplates.get_template_prompt()

        prompt = f"""
        你是一位顶尖的智能数据分析师和时空可视化专家。请规划一个专业的分析看板。

        === 数据元数据 (Metadata Context) ===
        {context_str}

        {layout_rules}

        === 🚨 严格布局约束 (CRITICAL) 🚨 ===
        1. 严禁使用 'left_sidebar' 或 'header'！只允许以下 Zone:
           - "center_main": 只能放地图 (map)
           - "right_sidebar": 放统计图表 (chart)
           - "bottom_insight": 放洞察卡片 (insight)
        2. 如果需要侧边栏分析，全部放入 "right_sidebar"。

        === 强制输出约束 ===
        每个组件(Component)必须严格包含以下字段，严禁缺失：
        1. "id", "title", "type", "layout"
        2. 如果是 "insight" 类型，必须提供完整的 "insight_config"。

        === 图表选型与时间分析准则 ===
        1. 趋势分析优先：若用户询问“趋势”、“变化”、“什么时候”或涉及时间，必须优先使用 'line' (折线图)。
        2. 聚合粒度：在 line/bar 的 chart_config 中必须指定 'time_bucket' (如 '1H', '1D')。
        3. 选型逻辑：
           - 时间趋势 -> 'line'
           - 低基数占比 -> 'pie'
           - 高基数排名 -> 'bar'
           - 周期性规律 -> 'timeline_heatmap'

        === 输出格式 (严格 JSON) ===
        {{
            "dashboard_id": "dash_v4_st",
            "title": "中文看板标题",
            "initial_view_state": {{ "longitude": -74.0, "latitude": 40.7, "zoom": 10 }},
            "global_time_range": ["YYYY-MM-DD HH:mm:ss", "YYYY-MM-DD HH:mm:ss"],
            "components": [
                {{
                    "id": "main_map",
                    "type": "map",
                    "layout": {{ "zone": "center_main" }},
                    "map_config": [ {{ "layer_id": "L1", "layer_type": "ScatterplotLayer", "data_api": "N/A" }} ]
                }},
                {{
                    "id": "trend_chart",
                    "type": "chart",
                    "title": "时间趋势分析",
                    "layout": {{ "zone": "right_sidebar" }},
                    "chart_config": {{ 
                        "chart_type": "line", 
                        "series_name": "指标", 
                        "x_axis": "时间列名",
                        "time_bucket": "1H" 
                    }}
                }},
                {{
                    "id": "global_insight",
                    "type": "insight",
                    "layout": {{ "zone": "bottom_insight" }},
                    "insight_config": {{ "summary": "...", "detail": "...", "tags": [] }}
                }}
            ]
        }}
        """
        return prompt

    def plan_dashboard(self, query: str, summaries: List[Dict[str, Any]]) -> DashboardSchema:
        """核心方法：生成最优规划并应用后处理补全"""
        system_prompt = self._build_system_prompt(summaries)

        user_prompt = f"""
        用户查询指令: "{query}"

        任务要求：
        1. 识别时间意图：如果涉及趋势变化，必须在右侧 RIGHT_SIDEBAR 规划一个折线图。
        2. 指定全局时间：根据元数据中的 time_span，在根级别设定合理的 global_time_range。
        3. 必须在所有组件中提供完整的 "title" 字段。
        """

        logger.info(f">>> [Planner] 正在规划时空看板...")

        try:
            raw_plan = self.llm.query_json(prompt=user_prompt, system_prompt=system_prompt)
            clean_plan = self._unwrap_llm_json(raw_plan)

            # --- [Option C] 鲁棒性后处理：自动补全缺失字段 ---
            if "components" in clean_plan:
                for i, comp in enumerate(clean_plan["components"]):
                    if not comp.get("title"):
                        comp["title"] = f"分析详情 {i + 1}"
                    if not comp.get("id"):
                        comp["id"] = f"comp_{i}"
                    if comp.get("type") == "insight":
                        if "insight_config" not in comp or not isinstance(comp["insight_config"], dict):
                            comp["insight_config"] = {"summary": "正在生成结论...", "detail": "请稍候。", "tags": []}

            # 实例化校验
            dashboard_plan = DashboardSchema(**clean_plan)

            # 强制布局对齐
            LayoutTemplates.apply_layout(dashboard_plan.components)

            return dashboard_plan

        except Exception as e:
            logger.error(f"Dashboard planning failed, reverting to fallback. Error: {e}")
            return self._generate_fallback_plan(query)

    def _generate_fallback_plan(self, query: str) -> DashboardSchema:
        """兜底方案：提供结构完整的基础布局"""
        fallback = DashboardSchema(
            dashboard_id="fallback",
            title="基础看板 (自动适配视图)",
            components=[
                DashboardComponent(
                    id="map_default", title="基础地理分布", type=ComponentType.MAP,
                    layout=LayoutConfig(zone=LayoutZone.CENTER_MAIN),
                    # [修复] 必须添加 map_config，否则前端 Deck.gl 不会渲染
                    map_config=[
                        {
                            "layer_id": "scatter_layer_fallback",
                            "layer_type": "ScatterplotLayer",
                            "data_api": "N/A",
                            "opacity": 0.8
                        }
                    ]
                ),
                DashboardComponent(
                    id="chart_default", title="核心维度统计", type=ComponentType.CHART,
                    layout=LayoutConfig(zone=LayoutZone.RIGHT_SIDEBAR),
                    chart_config={"chart_type": ChartType.BAR, "series_name": "记录数", "x_axis": "auto"}
                ),
                DashboardComponent(
                    id="insight_default", title="智能洞察结果", type=ComponentType.INSIGHT,
                    layout=LayoutConfig(zone=LayoutZone.BOTTOM_INSIGHT),
                    insight_config={
                        "summary": "分析引擎已生成基础结论",
                        "detail": "已提取出关键的数据分布特征供您参考。",
                        "tags": ["Fallback", "Ready"]
                    }
                )
            ]
        )
        LayoutTemplates.apply_layout(fallback.components)
        return fallback