import pytest
import json
from unittest.mock import MagicMock
from typing import Dict, Any, List

# 适配引用路径
from core.profiler.relation_mapper import RelationMapper


class TestRelationMapper:

    @pytest.fixture
    def mock_ai_client(self):
        return MagicMock()

    @pytest.fixture
    def mapper(self, mock_ai_client):
        return RelationMapper(llm_client=mock_ai_client)

    @pytest.fixture
    def sample_summaries(self) -> List[Dict[str, Any]]:
        """模拟两个可能会关联的数据集摘要"""
        return [
            {
                "variable_name": "df_trips",
                "semantic_analysis": {
                    "dataset_type": "transaction",
                    "description": "出租车行程记录",
                    "semantic_tags": {"PULocationID": "ID", "fare": "BIZ_METRIC"}
                }
            },
            {
                "variable_name": "df_zones",
                "semantic_analysis": {
                    "dataset_type": "dimension",
                    "description": "区域对照表",
                    "semantic_tags": {"LocationID": "ID", "Zone": "BIZ_CAT"}
                }
            }
        ]

    def test_map_relations_not_enough_data(self, mapper):
        """测试：如果只有一个数据集，应跳过分析"""
        single_summary = [{"variable_name": "df_only_one"}]
        result = mapper.map_relations(single_summary)

        assert result == []
        # 验证没有调用 LLM
        mapper.llm.query_json.assert_not_called()

    def test_map_relations_success(self, mapper, sample_summaries, mock_ai_client):
        """测试：LLM 成功识别出关联关系"""

        # 1. 模拟 LLM 返回的 JSON 结构
        mock_response = [
            {
                "source": "df_trips",
                "target": "df_zones",
                "type": "ID_LINK",
                "join_on": ["PULocationID", "LocationID"],
                "strength": 0.95,
                "reason": "Variable names suggest a foreign key relationship."
            }
        ]
        mock_ai_client.query_json.return_value = mock_response

        # 2. 执行
        relations = mapper.map_relations(sample_summaries)

        # 3. 验证
        assert len(relations) == 1
        assert relations[0]["type"] == "ID_LINK"
        assert relations[0]["target"] == "df_zones"

        # 4. 验证 Prompt 构建 (确保传递了元数据)
        call_args = mock_ai_client.query_json.call_args
        prompt_sent = call_args.kwargs['prompt']
        assert "df_trips" in prompt_sent
        assert "df_zones" in prompt_sent
        assert "LocationID" in prompt_sent  # 确保 tag 信息也在里面

    def test_map_relations_failure(self, mapper, sample_summaries, mock_ai_client):
        """测试：LLM 调用失败时的容错处理"""
        # 模拟抛出异常
        mock_ai_client.query_json.side_effect = Exception("LLM Error")

        result = mapper.map_relations(sample_summaries)

        # 应该返回空列表而不是崩溃
        assert result == []

    def test_get_drilldown_hint(self, mapper):
        """测试：Hint 字符串生成逻辑"""

        # 构造已知的关系列表
        relations = [
            {
                "source": "df_A",
                "target": "df_B",
                "type": "SPATIAL_LINK",
                "join_on": "contains"
            },
            {
                "source": "df_C",
                "target": "df_D",
                "type": "ID_LINK",
                "join_on": "id"
            }
        ]

        # 1. 测试查找与 df_A 有关的 Hint
        hint_a = mapper.get_drilldown_hint("df_A", relations)
        assert "SPATIAL_LINK" in hint_a
        assert "df_B" in hint_a
        assert "df_C" not in hint_a  # 不应包含无关信息

        # 2. 测试查找与 df_B 有关的 Hint (作为 target)
        hint_b = mapper.get_drilldown_hint("df_B", relations)
        assert "df_A" in hint_b  # 应该能反向找到 source

        # 3. 测试无关变量
        hint_none = mapper.get_drilldown_hint("df_E", relations)
        assert hint_none == ""