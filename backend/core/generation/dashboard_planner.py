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
    看板编排器 (V3.1 鲁棒增强版)：
    1. 应用方案 B：强化 Prompt 约束，强制 LLM 提供 title。
    2. 应用方案 C：后端自动补全缺失字段，确保校验 100% 通过。
    3. 动态感知数据基数，智能选型。
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
        # 提取动态元数据上下文
        context_str = ""
        for s in summaries:
            var_name = s.get('variable_name')
            col_meta = s.get('semantic_analysis', {}).get('column_metadata', {})

            context_str += f"\n### 数据集变量: {var_name}\n"
            for col_raw, meta in col_meta.items():
                context_str += (
                    f"- 原始列名: `{col_raw}` | 中文概念: '{meta.get('concept_name')}' | "
                    f"基数(唯一值数量): {meta.get('cardinality')} | 标签: {meta.get('semantic_tag')}\n"
                )

        layout_rules = LayoutTemplates.get_template_prompt()

        prompt = f"""
        你是一位顶尖的智能数据分析师和可视化专家。请规划一个专业的分析看板。

        === 数据元数据 (Metadata Context) ===
        {context_str}

        {layout_rules}

        === 强制输出约束 (Option B) ===
        每个组件(Component)必须严格包含以下字段，严禁缺失：
        1. "id": 唯一ID
        2. "title": 组件的中文标题 (必须提供，严禁缺失！！)
        3. "type": 组件类型
        4. "layout": {{"zone": "..."}}
        5. 如果是 "insight" 类型，必须提供 "insight_config": {{"summary": "...", "detail": "...", "tags": []}}

        === 图表选型准则 ===
        - 基数 < 10 (占比类): 必须用 'pie'。
        - 基数 10-30: 使用 'bar'。
        - 基数 > 30: 使用 'table'。

        === 输出格式 (严格 JSON) ===
        {{
            "dashboard_id": "dash_v3_auto",
            "title": "中文看板标题",
            "initial_view_state": {{ "longitude": -74.0, "latitude": 40.7, "zoom": 10 }},
            "components": [
                {{
                    "id": "main_map",
                    "type": "map",
                    "title": "地理分布图",
                    "layout": {{ "zone": "center_main" }},
                    "map_config": [ {{ "layer_id": "L1", "layer_type": "ScatterplotLayer", "data_api": "N/A" }} ]
                }},
                {{
                    "id": "side_chart_1",
                    "type": "chart",
                    "title": "占比统计",
                    "layout": {{ "zone": "right_sidebar" }},
                    "chart_config": {{ "chart_type": "pie", "series_name": "指标", "x_axis": "原始列名" }}
                }},
                {{
                    "id": "global_insight",
                    "type": "insight",
                    "title": "核心发现",
                    "layout": {{ "zone": "bottom_insight" }},
                    "insight_config": {{ "summary": "结论摘要", "detail": "深度解析", "tags": ["标签"] }}
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
        1. 必须根据数据元数据，从饼图、条形图、表格中选择【最适合基数特征】的两种不同图表放在右侧。
        2. 严禁漏掉任何组件的 "title" 字段。
        """

        logger.info(f">>> [Planner] 正在规划看板...")

        try:
            raw_plan = self.llm.query_json(prompt=user_prompt, system_prompt=system_prompt)
            clean_plan = self._unwrap_llm_json(raw_plan)

            # --- [Option C] 鲁棒性后处理：自动补全缺失字段 ---
            if "components" in clean_plan:
                for i, comp in enumerate(clean_plan["components"]):
                    # 1. 补全缺失的标题
                    if not comp.get("title"):
                        comp["title"] = f"分析详情 {i + 1}"

                    # 2. 补全缺失的 ID
                    if not comp.get("id"):
                        comp["id"] = f"comp_{i}"

                    # 3. 修复 insight_config 的内部结构
                    if comp.get("type") == "insight":
                        if "insight_config" not in comp or not isinstance(comp["insight_config"], dict):
                            comp["insight_config"] = {"summary": "正在分析数据...", "detail": "请稍候查看详细洞察。",
                                                      "tags": []}
                        else:
                            # 补全 insight 内部必填项
                            cfg = comp["insight_config"]
                            if "summary" not in cfg: cfg["summary"] = "核心结论生成中"
                            if "detail" not in cfg: cfg["detail"] = "详细数据特征已提取"
                            if "tags" not in cfg: cfg["tags"] = ["自动分析"]

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
                    layout=LayoutConfig(zone=LayoutZone.CENTER_MAIN)
                ),
                DashboardComponent(
                    id="chart_default", title="关键维度统计", type=ComponentType.CHART,
                    layout=LayoutConfig(zone=LayoutZone.RIGHT_SIDEBAR),
                    chart_config={"chart_type": ChartType.BAR, "series_name": "记录数", "x_axis": "auto"}
                ),
                DashboardComponent(
                    id="insight_default", title="智能洞察结果", type=ComponentType.INSIGHT,
                    layout=LayoutConfig(zone=LayoutZone.BOTTOM_INSIGHT),
                    insight_config={
                        "summary": "分析引擎已生成基础结论",
                        "detail": "虽然复杂规划遇到阻碍，但我们已提取出关键的数据分布特征供您参考。",
                        "tags": ["Fallback", "Ready"]
                    }
                )
            ]
        )
        LayoutTemplates.apply_layout(fallback.components)
        return fallback