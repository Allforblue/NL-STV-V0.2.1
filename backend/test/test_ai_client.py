import pytest
import json
from unittest.mock import MagicMock, patch
from openai import AuthenticationError, APIConnectionError

# 适配引用路径
from core.llm.AI_client import AIClient


class TestAIClient:

    @pytest.fixture
    def mock_openai(self):
        """
        这个 Fixture 用于 Mock 整个 OpenAI 类。
        Patch 的路径必须是 'core.llm.AI_client.OpenAI'，
        指代的是 AI_client.py 文件里导入的那个 OpenAI 类。
        """
        with patch("core.llm.AI_client.OpenAI") as mock_class:
            yield mock_class

    def test_init(self, mock_openai):
        """测试初始化是否正确传递了参数"""
        client = AIClient(api_key="fake_key", model_name="deepseek-test")

        # 验证 OpenAI 是否被调用，以及参数是否正确
        mock_openai.assert_called_once()
        _, kwargs = mock_openai.call_args
        assert kwargs["api_key"] == "fake_key"
        assert kwargs["base_url"] == "https://api.deepseek.com"
        assert client.model_name == "deepseek-test"

    def test_is_alive_true(self, mock_openai):
        """测试连接正常的情况"""
        # 模拟 client.models.list() 成功执行
        mock_instance = mock_openai.return_value
        mock_instance.models.list.return_value = ["model1", "model2"]

        client = AIClient(api_key="fake")
        assert client.is_alive() is True

    def test_is_alive_false_auth_error(self, mock_openai):
        """测试 API Key 错误的情况"""
        # 模拟抛出 AuthenticationError
        mock_instance = mock_openai.return_value
        # 注意：这里需要构造一个带 request, body, message 的 response，或者直接只传 message
        # 简单起见，我们直接抛出异常类型
        mock_instance.models.list.side_effect = AuthenticationError("Invalid Key", response=MagicMock(), body={})

        client = AIClient(api_key="fake")
        assert client.is_alive() is False

    def test_chat_success(self, mock_openai):
        """测试普通对话功能"""
        # 1. 构造复杂的 OpenAI 响应结构
        mock_instance = mock_openai.return_value

        # 模拟 response.choices[0].message.content
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Hello, Human!"
        mock_response.choices = [MagicMock(message=mock_message)]

        # 将构造好的响应赋给 chat.completions.create
        mock_instance.chat.completions.create.return_value = mock_response

        # 2. 执行测试
        client = AIClient(api_key="fake")
        response = client.chat([{"role": "user", "content": "Hi"}])

        # 3. 断言
        assert response == "Hello, Human!"
        # 验证是否调用了正确的方法
        mock_instance.chat.completions.create.assert_called_once()
        # 验证参数中是否关闭了流式输出
        _, kwargs = mock_instance.chat.completions.create.call_args
        assert kwargs["stream"] is False

    def test_query_json_cleaning(self, mock_openai):
        """测试 JSON 提取和 Markdown 清洗功能"""
        # 1. 模拟 LLM 返回带 Markdown 格式的 JSON 字符串
        mock_instance = mock_openai.return_value

        raw_json_string = "```json\n{\"file_type\": \"csv\", \"cols\": 3}\n```"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=raw_json_string))]
        mock_instance.chat.completions.create.return_value = mock_response

        # 2. 执行测试
        client = AIClient(api_key="fake")
        result = client.query_json("Analyze this", system_prompt="You are a bot")

        # 3. 断言
        assert isinstance(result, dict)
        assert result["file_type"] == "csv"
        assert result["cols"] == 3

        # 4. 验证是否自动在 System Prompt 中添加了 'JSON' 提示
        _, kwargs = mock_instance.chat.completions.create.call_args
        messages = kwargs["messages"]
        system_content = messages[0]["content"]
        assert "JSON" in system_content or "json" in system_content

    def test_query_json_failure(self, mock_openai):
        """测试 LLM 返回了坏数据，无法解析 JSON"""
        mock_instance = mock_openai.return_value

        # 模拟返回了一段纯文本，不是 JSON
        bad_response = "I cannot do that."

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=bad_response))]
        mock_instance.chat.completions.create.return_value = mock_response

        client = AIClient(api_key="fake")

        # 断言应该抛出 ValueError
        with pytest.raises(ValueError, match="LLM 未返回有效的 JSON"):
            client.query_json("Analyze this")