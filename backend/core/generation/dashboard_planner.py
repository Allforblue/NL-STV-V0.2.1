import logging
import json
from typing import Dict, Any, List

from core.llm.AI_client import AIClient
from core.schemas.dashboard import DashboardSchema, DashboardComponent, ComponentType

logger = logging.getLogger(__name__)


class DashboardPlanner:
    """
    看板编排器：规划看板布局
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    def _unwrap_llm_json(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """智能解包"""
        required_keys = {"dashboard_id", "title", "components"}
        current_keys = set(data.keys())
        if not required_keys.issubset(current_keys):
            for wrapper in ['dashboard', 'plan', 'result', 'output']:
                if wrapper in data and isinstance(data[wrapper], dict):
                    return data[wrapper]
        return data

    def _build_system_prompt(self, summaries: List[Dict[str, Any]]) -> str:
        context_str = ""
        for s in summaries:
            var_name = s.get('variable_name')
            tags = s.get('semantic_analysis', {}).get('semantic_tags', {})
            context_str += f"- 变量 `{var_name}`: {json.dumps(tags)}\n"

        # [关键修改] 提供极其详细的 JSON 模板，防止 LLM 漏掉必填字段
        prompt = f"""
        你是一位可视化专家。请规划一个多维交互看板。

        === 数据上下文 ===
        {context_str}

        === 输出格式 (严格 JSON) ===
        你必须返回符合以下结构的 JSON。注意标注为 [必填] 的字段：

        {{
            "dashboard_id": "dash_001",
            "title": "看板标题",
            "components": [
                {{
                    "id": "map_1",
                    "type": "map",
                    "title": "地图标题",
                    "layout": {{"x": 0, "y": 0, "w": 6, "h": 6}},
                    "map_config": [
                        {{
                            "layer_id": "layer_1",         // [必填]
                            "layer_type": "ScatterplotLayer", // [必填]
                            "data_api": "N/A"              // [必填] 填 N/A 即可
                        }}
                    ]
                }},
                {{
                    "id": "chart_1",
                    "type": "chart",
                    "title": "图表标题",
                    "layout": {{"x": 6, "y": 0, "w": 6, "h": 6}},
                    "chart_config": {{
                        "chart_type": "bar",              // [必填] bar/line/pie
                        "series_name": "指标名称",          // [必填]
                        "x_axis": "字段名"
                    }}
                }},
                {{
                    "id": "insight_1",
                    "type": "insight",
                    "title": "智能洞察",
                    "layout": {{"x": 0, "y": 6, "w": 12, "h": 4}},
                    "insight_config": {{
                        "summary": "等待生成...",          // [必填]
                        "detail": "等待生成...",           // [必填]
                        "tags": []
                    }}
                }}
            ]
        }}
        """
        return prompt

    def plan_dashboard(self, query: str, summaries: List[Dict[str, Any]]) -> DashboardSchema:
        """核心方法：生成看板规划"""
        system_prompt = self._build_system_prompt(summaries)

        user_prompt = f"""
        用户查询: "{query}"

        请规划看板，包含至少 1 个地图(如果数据含地理信息)和 1 个统计图。
        必须包含 1 个 type="insight" 的组件。

        请严格按照 System Prompt 中的 JSON 模板输出，不要遗漏必填字段。
        """

        logger.info("Planning dashboard layout...")

        try:
            raw_plan = self.llm.query_json(
                prompt=user_prompt,
                system_prompt=system_prompt
            )

            # 解包
            clean_plan = self._unwrap_llm_json(raw_plan)

            # 转换为 Schema
            dashboard_plan = DashboardSchema(**clean_plan)
            return dashboard_plan

        except Exception as e:
            logger.error(f"Dashboard planning failed: {e}")
            # 打印详细错误方便调试
            # logger.error(f"Failed JSON: {json.dumps(raw_plan, indent=2)}")
            return self._generate_fallback_plan(query)

    def _generate_fallback_plan(self, query: str) -> DashboardSchema:
        """兜底方案"""
        # [关键] 兜底方案也要符合 Schema 的必填要求
        return DashboardSchema(
            dashboard_id="fallback",
            title="基础分析(Fallback)",
            components=[
                DashboardComponent(
                    id="insight_1",
                    title="系统提示",
                    type=ComponentType.INSIGHT,
                    layout={"x": 0, "y": 0, "w": 12, "h": 4},
                    insight_config={
                        "summary": "规划失败",
                        "detail": "AI 响应格式异常，系统已降级为基础模式。",
                        "tags": ["Error"]
                    }
                )
            ]
        )