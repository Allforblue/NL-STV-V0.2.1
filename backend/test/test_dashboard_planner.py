import pytest
from unittest.mock import MagicMock
from typing import Dict, Any

# 适配引用路径
from core.generation.dashboard_planner import DashboardPlanner
# 引入真实的 Schema 类
from core.schemas.dashboard import (
    DashboardSchema,
    ComponentType,
    ChartType,
    DashboardComponent
)


class TestDashboardPlanner:

    @pytest.fixture
    def mock_ai_client(self):
        """Mock AIClient，避免真实调用"""
        client = MagicMock()
        return client

    @pytest.fixture
    def planner(self, mock_ai_client):
        return DashboardPlanner(llm_client=mock_ai_client)

    @pytest.fixture
    def mock_summaries(self) -> list[Dict[str, Any]]:
        """模拟 Profiler 生成的数据摘要"""
        return [{
            "variable_name": "df_traffic",
            "semantic_analysis": {
                "description": "2025年纽约出租车数据",
                "semantic_tags": {
                    "pickup_datetime": "ST_TIME",
                    "dropoff_lat": "ST_LAT",
                    "passenger_count": "BIZ_METRIC"
                }
            }
        }]

    def test_build_system_prompt(self, planner, mock_summaries):
        """测试 Prompt 构建逻辑"""
        prompt = planner._build_system_prompt(mock_summaries)
        assert "df_traffic" in prompt
        assert "ST_TIME" in prompt
        assert "DashboardSchema" in prompt

    def test_plan_dashboard_success(self, planner, mock_ai_client, mock_summaries):
        """
        核心测试：测试 LLM 返回 JSON 后，能否正确解析为 DashboardSchema 对象。
        这里的 JSON 结构必须严格符合 core/schemas/dashboard.py 的定义。
        """

        # 1. 构造一个符合 Pydantic 定义的字典
        valid_response = {
            "dashboard_id": "dash_001",
            "title": "交通分析看板",
            "initial_view_state": {"longitude": -74.0, "latitude": 40.7, "zoom": 10},
            "components": [
                {
                    # 这是一个统计图组件
                    "id": "chart_1",
                    "title": "客流趋势",
                    "type": "chart",  # 对应 ComponentType.CHART (枚举值)
                    "layout": {"x": 0, "y": 0, "w": 6, "h": 4},
                    # ChartConfig 必须包含 series_name 和 chart_type
                    "chart_config": {
                        "chart_type": "line",  # 对应 ChartType.LINE
                        "x_axis": "pickup_datetime",
                        "y_axis": ["passenger_count"],
                        "series_name": "客流量"
                    }
                },
                {
                    # 这是一个地图组件
                    "id": "map_1",
                    "title": "上车点分布",
                    "type": "map",  # 对应 ComponentType.MAP
                    "layout": {"x": 6, "y": 0, "w": 6, "h": 4},
                    # MapLayerConfig 列表
                    "map_config": [
                        {
                            "layer_id": "layer_scatter",
                            "layer_type": "ScatterplotLayer",
                            "data_api": "api/data/geo_points"
                        }
                    ]
                }
            ]
        }

        # 2. 设定 Mock 返回
        mock_ai_client.query_json.return_value = valid_response

        # 3. 执行
        query = "帮我分析一下客流趋势"
        plan = planner.plan_dashboard(query, mock_summaries)

        # 4. 验证
        assert isinstance(plan, DashboardSchema)
        assert plan.title == "交通分析看板"
        assert len(plan.components) == 2

        # 验证组件类型解析正确 (Enum 比较)
        assert plan.components[0].type == ComponentType.CHART
        assert plan.components[0].chart_config.chart_type == ChartType.LINE

        # 验证地图配置
        assert plan.components[1].type == ComponentType.MAP
        assert plan.components[1].map_config[0].layer_type == "ScatterplotLayer"

    def test_plan_dashboard_failure_fallback(self, planner, mock_ai_client, mock_summaries):
        """测试 LLM 失败时的兜底方案"""

        # 模拟异常
        mock_ai_client.query_json.side_effect = ValueError("LLM returned garbage")

        # 执行
        plan = planner.plan_dashboard("随便问问", mock_summaries)

        # 验证
        assert plan.dashboard_id == "fallback"
        # 验证兜底方案中包含 Map 和 Insight
        types = [c.type for c in plan.components]
        assert ComponentType.MAP in types
        assert ComponentType.INSIGHT in types

        # 验证 Insight 组件的配置结构
        insight_comp = next(c for c in plan.components if c.type == ComponentType.INSIGHT)
        assert insight_comp.insight_config.summary == "规划失败"