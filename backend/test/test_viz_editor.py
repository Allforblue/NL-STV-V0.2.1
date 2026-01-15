import pytest
from unittest.mock import MagicMock
from typing import Any

# 适配引用路径
from core.generation.viz_editor import VizEditor


# 简单的 Mock 类模拟 Payload 数据结构
class MockPayload:
    def __init__(self, query="", bbox=None, selected_ids=None):
        self.query = query
        self.bbox = bbox
        self.selected_ids = selected_ids


class TestVizEditor:

    @pytest.fixture
    def mock_ai_client(self):
        return MagicMock()

    @pytest.fixture
    def editor(self, mock_ai_client):
        return VizEditor(llm_client=mock_ai_client)

    @pytest.fixture
    def sample_code(self):
        return "def get_dashboard_data(ctx): return {}"

    @pytest.fixture
    def sample_summaries(self):
        return [{"variable_name": "df_test"}]

    def test_prompt_includes_original_code(self, editor, mock_ai_client, sample_code, sample_summaries):
        """测试：系统提示词中是否包含了'旧代码'"""

        # 1. 模拟交互 payload
        payload = MockPayload(query="Change color to red")
        mock_ai_client.chat.return_value = "def modified(): pass"

        # 2. 执行
        editor.edit_dashboard_code(sample_code, payload, sample_summaries)

        # 3. 检查 Prompt
        call_args = mock_ai_client.chat.call_args
        messages = call_args[0][0]
        system_prompt = messages[0]["content"]

        # 断言旧代码存在于 System Prompt 中
        assert sample_code in system_prompt
        assert "def get_dashboard_data(data_context):" in system_prompt

    def test_interaction_bbox(self, editor, mock_ai_client, sample_code, sample_summaries):
        """测试：BBox 框选逻辑是否注入 Prompt"""

        # 模拟前端传来的 BBox
        payload = MockPayload(query="", bbox=[-74.0, 40.0, -73.0, 41.0])
        mock_ai_client.chat.return_value = "pass"

        editor.edit_dashboard_code(sample_code, payload, sample_summaries)

        call_args = mock_ai_client.chat.call_args
        user_prompt = call_args[0][0][1]["content"]

        # 断言包含框选描述
        assert "地图交互动作" in user_prompt
        assert "-74.0" in user_prompt
        assert "下钻分析" in user_prompt

    def test_interaction_selection(self, editor, mock_ai_client, sample_code, sample_summaries):
        """测试：ID 选中逻辑是否注入 Prompt"""

        payload = MockPayload(query="", selected_ids=["Zone1", "Zone2"])
        mock_ai_client.chat.return_value = "pass"

        editor.edit_dashboard_code(sample_code, payload, sample_summaries)

        call_args = mock_ai_client.chat.call_args
        user_prompt = call_args[0][0][1]["content"]

        assert "选中了 ID" in user_prompt
        assert "Zone1" in user_prompt

    def test_clean_markdown_output(self, editor, mock_ai_client, sample_code, sample_summaries):
        """测试：LLM 返回 Markdown 时是否被清洗"""

        # 模拟脏输出
        dirty_response = """
```python
def get_dashboard_data(ctx):
    # Modified code
    return {}
        """
        mock_ai_client.chat.return_value = dirty_response
        payload = MockPayload(query="fix it")

        # 执行
        clean_code = editor.edit_dashboard_code(sample_code, payload, sample_summaries)

        # 断言
        assert "```" not in clean_code
        assert clean_code.startswith("def get_dashboard_data")