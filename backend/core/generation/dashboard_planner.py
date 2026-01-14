import logging
import json
from typing import Dict, Any, List

# 确保路径一致，都从 core 开始
from core.llm.AI_client import AIClient  # 确保文件夹已改为小写 llm
from core.schemas.dashboard import DashboardSchema, DashboardComponent, ComponentType

logger = logging.getLogger(__name__)


class DashboardPlanner:
    """
    看板编排器：
    根据数据的语义特征（Semantic Tags）和用户需求，自动设计看板布局、选择图表类型并规划交互联动。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    def _build_system_prompt(self, summaries: List[Dict[str, Any]]) -> str:
        """
        构建编排器的系统提示词，注入数据背景
        """
        context_str = ""
        for s in summaries:
            var_name = s.get('variable_name')
            desc = s.get('semantic_analysis', {}).get('description', '')
            tags = s.get('semantic_analysis', {}).get('semantic_tags', {})
            context_str += f"- 数据变量 `{var_name}`: {desc}\n  语义标签: {json.dumps(tags)}\n"

        prompt = f"""
        你是一位高级时空数据可视化专家和 UX 设计师。
        你的任务是根据用户提供的【数据上下文】和【分析目标】，规划一个多维交互看板。

        === 数据上下文 ===
        {context_str}

        === 编排原则 ===
        1. 布局合理性：使用 12 列网格系统。大地图通常占据 8x8 或 12x6 的空间。
        2. 维度匹配：
           - 含有 ST_GEO, ST_LAT/LON 的数据必须配置 MAP 组件。
           - 含有 ST_TIME 的数据应配置趋势图 (LINE chart)。
           - 含有 BIZ_CAT 的数据应配置分布图 (BAR/PIE chart)。
           - 含有 BIZ_METRIC 的重要指标应配置 KPI 卡片。
        3. 联动规划：为支持下钻的组件添加 'bbox_filter' 或 'id_select' 到 interactions 列表。
        4. 洞察预测：预留一个 INSIGHT 组件用于展示 AI 执行后的深度结论。

        === 输出格式 ===
        你必须返回一个符合 DashboardSchema 结构的 JSON 对象。
        """
        return prompt

    def plan_dashboard(self, query: str, summaries: List[Dict[str, Any]]) -> DashboardSchema:
        """
        核心方法：生成看板初步规划
        """
        system_prompt = self._build_system_prompt(summaries)

        user_prompt = f"""
        用户查询需求: "{query}"

        请基于上述需求和数据特征，规划一个多维看板。
        要求：
        1. 包含至少一个地图组件。
        2. 包含至少两个统计图表（折线图、柱状图等）。
        3. 包含一个 AI 洞察组件。
        4. 设定初始视口位置（如果有经纬度信息）。

        请直接输出符合 DashboardSchema 的 JSON 结果，不要包含任何解释文字。
        """

        logger.info("Planning dashboard layout...")

        # 调用 llm 获取结构化规划
        try:
            # 假设 AIClient 已经支持 query_json 方法
            raw_plan = self.llm.query_json(
                prompt=user_prompt,
                system_prompt=system_prompt
            )

            # 将 JSON 解析为 Pydantic 模型
            dashboard_plan = DashboardSchema(**raw_plan)
            return dashboard_plan

        except Exception as e:
            logger.error(f"Dashboard planning failed: {e}")
            # 返回一个基础的保底方案
            return self._generate_fallback_plan(query, summaries)

    def _generate_fallback_plan(self, query: str, summaries: List[Dict[str, Any]]) -> DashboardSchema:
        """
        当 llm 失败时的兜底方案
        """
        return DashboardSchema(
            dashboard_id="fallback",
            title="基础数据预览",
            components=[
                DashboardComponent(
                    id="map_1",
                    title="空间分布",
                    type=ComponentType.MAP,
                    layout={"x": 0, "y": 0, "w": 8, "h": 6},
                    map_config=[]
                ),
                DashboardComponent(
                    id="insight_1",
                    title="分析结论",
                    type=ComponentType.INSIGHT,
                    layout={"x": 8, "y": 0, "w": 4, "h": 6},
                    insight_config={"summary": "规划失败", "detail": "系统无法自动规划看板，请尝试简化指令。",
                                    "tags": ["Error"]}
                )
            ]
        )


# --- 逻辑演示 ---
if __name__ == "__main__":
    # 模拟分析结果
    mock_summaries = [{
        "variable_name": "df_traffic",
        "semantic_analysis": {
            "description": "城市交通流量数据",
            "semantic_tags": {
                "pickup_time": "ST_TIME",
                "lat": "ST_LAT",
                "lon": "ST_LON",
                "volume": "BIZ_METRIC",
                "district": "BIZ_CAT"
            }
        }
    }]

    # client = AIClient(...)
    # planner = DashboardPlanner(client)
    # plan = planner.plan_dashboard("分析静安区交通高峰趋势", mock_summaries)
    # print(plan.json(indent=2))