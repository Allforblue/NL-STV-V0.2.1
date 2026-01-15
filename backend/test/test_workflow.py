import pytest
from unittest.mock import MagicMock
from typing import Dict, Any

from core.services.workflow import AnalysisWorkflow
from core.schemas.dashboard import DashboardSchema, DashboardComponent, ComponentType
from core.schemas.interaction import InteractionPayload
from core.execution.executor import DashboardExecutionResult, ComponentResult


# ==========================================
# Helpers
# ==========================================

def create_mock_plan():
    return DashboardSchema(
        dashboard_id="test_dash",
        title="Test Dashboard",
        components=[
            DashboardComponent(
                id="chart_1", title="Chart", type=ComponentType.CHART, layout={"x": 0, "y": 0, "w": 6, "h": 6},
                chart_config={"chart_type": "bar", "series_name": "s"}
            ),
            DashboardComponent(
                id="insight_1", title="Insight", type=ComponentType.INSIGHT, layout={"x": 6, "y": 0, "w": 6, "h": 6},
                insight_config={"summary": "S", "detail": "D", "tags": []}
            )
        ]
    )


def create_mock_exec_result(success=True, error=None):
    return DashboardExecutionResult(
        success=success,
        results={} if not success else {"chart_1": ComponentResult(component_id="chart_1", data={})},
        global_insight_data={},
        error=error,
        code="print('ok')"
    )


# ==========================================
# Test Class
# ==========================================

@pytest.mark.asyncio
class TestAnalysisWorkflow:

    @pytest.fixture
    def mock_ai_client(self):
        return MagicMock()

    @pytest.fixture
    def workflow(self, mock_ai_client):
        wf = AnalysisWorkflow(llm_client=mock_ai_client)
        # Mock 所有子模块
        wf.analyzer = MagicMock()
        wf.relation_mapper = MagicMock()  # [新增]
        wf.planner = MagicMock()
        wf.generator = MagicMock()
        wf.editor = MagicMock()
        wf.executor = MagicMock()
        wf.insight_extractor = MagicMock()
        return wf

    @pytest.fixture
    def basic_payload(self):
        return InteractionPayload(session_id="sess_1", query="Analyze relation")

    async def test_workflow_integrates_relation_mapper(self, workflow, basic_payload):
        """测试：Workflow 是否正确调用了 RelationMapper 并将结果传给了 Generator"""

        # 1. 设定 Mock
        workflow.planner.plan_dashboard.return_value = create_mock_plan()
        workflow.executor.execute_dashboard_logic.return_value = create_mock_exec_result(success=True)
        workflow.insight_extractor.generate_insights.return_value = {"summary": "Done"}

        # 模拟 RelationMapper 发现了关联
        workflow.relation_mapper.map_relations.return_value = [
            {"source": "TblA", "target": "TblB", "type": "ID_LINK", "join_on": ["ID"]}
        ]

        # 2. 执行 (模拟传入两个数据摘要，触发关联分析)
        summaries = [{"var": "TblA"}, {"var": "TblB"}]
        await workflow.execute_step(basic_payload, summaries, {}, None)

        # 3. 验证
        # 确认调用了 map_relations
        workflow.relation_mapper.map_relations.assert_called_once()

        # 确认生成的 Hint 传给了 Generator
        # 检查 generator.generate_dashboard_code 的 interaction_hint 参数
        call_args = workflow.generator.generate_dashboard_code.call_args
        hint_passed = call_args.kwargs['interaction_hint']

        assert "ID_LINK" in hint_passed
        assert "TblA" in hint_passed

    async def test_workflow_self_healing(self, workflow, basic_payload):
        """测试：自动修复机制 (Self-Healing)"""

        # 1. 设定 Mocks
        workflow.planner.plan_dashboard.return_value = create_mock_plan()

        # 第一次生成代码：坏代码
        workflow.generator.generate_dashboard_code.return_value = "bad_code"

        # 第一次执行：失败
        fail_result = create_mock_exec_result(success=False, error="SyntaxError")
        # 第二次执行：成功 (修复后)
        success_result = create_mock_exec_result(success=True)

        # 设置 executor 的副作用：第一次调用返回失败，第二次返回成功
        workflow.executor.execute_dashboard_logic.side_effect = [fail_result, success_result]

        # 设置 fix_code 返回好代码
        workflow.generator.fix_code.return_value = "fixed_code"

        # 2. 执行
        await workflow.execute_step(basic_payload, [{"var": "A"}], {}, None)

        # 3. 验证
        # Executor 应该被调用两次
        assert workflow.executor.execute_dashboard_logic.call_count == 2
        # Generator.fix_code 应该被调用一次
        workflow.generator.fix_code.assert_called_once()
        # 最终的 metadata 应该保存的是 fixed_code
        call_args = workflow.generator.fix_code.call_args
        assert call_args.kwargs['original_code'] == "bad_code"