import pytest
from unittest.mock import MagicMock
from typing import Dict, Any

# 适配引用路径
from core.execution.insight_extractor import InsightExtractor
# 引入真实的 Schema，确保返回值符合定义
from core.schemas.dashboard import InsightCard


class TestInsightExtractor:

    @pytest.fixture
    def mock_ai_client(self):
        return MagicMock()

    @pytest.fixture
    def extractor(self, mock_ai_client):
        return InsightExtractor(llm_client=mock_ai_client)

    @pytest.fixture
    def sample_inputs(self):
        """准备测试用的输入数据"""
        query = "Analyze fare distribution"

        # 模拟 Executor 算出来的统计值
        stats = {
            "chart_1": {"mean": 15.5, "max": 100.0, "count": 500}
        }

        # 模拟 Profiler 分析出的语义背景
        summaries = [
            {
                "variable_name": "df_taxi",
                "semantic_analysis": {
                    "semantic_tags": {"fare": "BIZ_METRIC"}
                }
            }
        ]
        return query, stats, summaries

    def test_generate_insights_success(self, extractor, mock_ai_client, sample_inputs):
        """测试：正常生成 Insight 的流程"""
        query, stats, summaries = sample_inputs

        # 1. 模拟 LLM 返回符合 InsightCard 结构的 JSON
        mock_response = {
            "summary": "Fare is high.",
            "detail": "The average fare is 15.5, with a max of 100.",
            "tags": ["High Cost", "Outlier"]
        }
        mock_ai_client.query_json.return_value = mock_response

        # 2. 执行
        result = extractor.generate_insights(query, stats, summaries)

        # 3. 验证
        assert isinstance(result, InsightCard)
        assert result.summary == "Fare is high."
        assert "High Cost" in result.tags

    def test_prompt_context_injection(self, extractor, mock_ai_client, sample_inputs):
        """测试：验证语义标签和统计数据是否真的进入了 Prompt"""
        query, stats, summaries = sample_inputs

        # Mock 返回值以免报错
        mock_ai_client.query_json.return_value = {
            "summary": "s", "detail": "d", "tags": []
        }

        extractor.generate_insights(query, stats, summaries)

        # 捕获调用参数
        call_args = mock_ai_client.query_json.call_args
        kwargs = call_args.kwargs

        system_prompt = kwargs['system_prompt']
        user_prompt = kwargs['prompt']

        # 验证 System Prompt 包含语义背景
        assert "df_taxi" in system_prompt
        assert "BIZ_METRIC" in system_prompt

        # 验证 User Prompt 包含统计数据
        assert "15.5" in user_prompt  # mean value
        assert "Analyze fare distribution" in user_prompt  # query

    def test_error_handling_fallback(self, extractor, mock_ai_client, sample_inputs):
        """测试：当 LLM 挂掉时，应返回兜底的 InsightCard"""
        query, stats, summaries = sample_inputs

        # 模拟 LLM 抛出异常
        mock_ai_client.query_json.side_effect = Exception("LLM Down")

        # 执行
        result = extractor.generate_insights(query, stats, summaries)

        # 验证
        assert isinstance(result, InsightCard)
        # 兜底逻辑中的 summary 应该是固定的
        assert result.summary == "数据特征提取完成"
        # 兜底逻辑的 tags 包含 "系统提示"
        assert "系统提示" in result.tags
        # 错误详情里应该包含原始数据的 keys
        assert "chart_1" in result.detail