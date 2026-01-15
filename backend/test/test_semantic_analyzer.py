import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from typing import Dict, Any

# 适配引用路径
from core.profiler.semantic_analyzer import SemanticAnalyzer


class TestSemanticAnalyzer:

    @pytest.fixture
    def mock_ai_client(self):
        return MagicMock()

    @pytest.fixture
    def analyzer(self, mock_ai_client):
        return SemanticAnalyzer(llm_client=mock_ai_client)

    @pytest.fixture
    def mock_loader_factory(self):
        """
        Mock LoaderFactory 以及它返回的 Loader 实例。
        这是为了防止测试去读取真实的文件系统。
        """
        # Patch 的路径必须是 semantic_analyzer.py 中导入 LoaderFactory 的位置
        with patch("core.profiler.semantic_analyzer.LoaderFactory") as mock_factory:
            # 构造一个 Mock Loader 实例
            mock_loader = MagicMock()

            # 设置 factory.get_loader() 返回这个 mock_loader
            mock_factory.get_loader.return_value = mock_loader

            yield mock_factory

    def test_get_basic_fingerprint(self, analyzer, mock_loader_factory):
        """测试：物理特征提取 (行数、列统计)"""

        # 1. 准备 Mock 数据
        # 模拟文件有 100 行
        mock_loader = mock_loader_factory.get_loader.return_value
        mock_loader.count_rows.return_value = 100

        # 模拟 peek 返回前 5 行数据
        df_preview = pd.DataFrame({
            "age": [20, 30, 25],
            "name": ["Alice", "Bob", "Charlie"]
        })
        mock_loader.peek.return_value = df_preview

        # 2. 执行
        file_path = "data/users.csv"
        fingerprint = analyzer._get_basic_fingerprint(file_path)

        # 3. 验证
        assert fingerprint["rows"] == 100
        assert fingerprint["filename"] == "users.csv"

        # 验证列统计信息
        cols = fingerprint["columns"]
        assert "age" in cols
        assert "name" in cols
        # 验证样本提取是否正确
        assert "20" in cols["age"]["samples"]

        # 验证是否调用了 loader.peek(..., n=5)
        mock_loader.peek.assert_called_with(file_path, n=5)

    def test_analyze_success(self, analyzer, mock_loader_factory, mock_ai_client):
        """测试：完整的语义分析流程"""

        # 1. 准备 Mock Loader (模拟出租车数据)
        mock_loader = mock_loader_factory.get_loader.return_value
        df_sample = pd.DataFrame({
            "pickup_latitude": [40.712, 40.713],
            "pickup_longitude": [-74.006, -74.007],
            "fare_amount": [12.5, 15.0]
        })
        mock_loader.peek.return_value = df_sample
        mock_loader.count_rows.return_value = 1000

        # 2. 准备 Mock LLM 响应
        mock_ai_response = {
            "dataset_type": "TRAJECTORY",
            "description": "NYC Taxi Data",
            "semantic_tags": {
                "pickup_latitude": "ST_LAT",
                "pickup_longitude": "ST_LON",
                "fare_amount": "BIZ_METRIC"
            },
            "recommended_charts": ["Scatter Map"],
            "potential_join_keys": []
        }
        mock_ai_client.query_json.return_value = mock_ai_response

        # 3. 执行
        file_path = "data/trips_2025.csv"
        result = analyzer.analyze(file_path)

        # 4. 验证结果结构
        assert result["variable_name"] == "df_trips_2025"
        assert result["semantic_analysis"]["dataset_type"] == "TRAJECTORY"

        # 验证 tags 是否正确
        tags = result["semantic_analysis"]["semantic_tags"]
        assert tags["pickup_latitude"] == "ST_LAT"
        assert tags["fare_amount"] == "BIZ_METRIC"

        # 5. 验证发送给 LLM 的 Prompt 是否包含样本数据
        call_args = mock_ai_client.query_json.call_args
        prompt_content = call_args.kwargs['prompt']

        # Prompt 中必须包含列名和样本值，这样 LLM 才能判断
        assert "pickup_latitude" in prompt_content
        assert "40.712" in prompt_content  # 样本值

    def test_analyze_failure_handling(self, analyzer, mock_loader_factory, mock_ai_client):
        """测试：当 LLM 报错时，不应崩溃，而是返回 error 信息"""

        # Mock Loader 正常
        mock_loader = mock_loader_factory.get_loader.return_value
        mock_loader.peek.return_value = pd.DataFrame({"a": [1]})

        # Mock LLM 报错
        mock_ai_client.query_json.side_effect = Exception("API Timeout")

        # 执行
        result = analyzer.analyze("data.csv")

        # 验证
        assert "error" in result
        assert "API Timeout" in result["error"]