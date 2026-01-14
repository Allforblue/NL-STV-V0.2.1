# import requests
# import json
# import logging
# from typing import Dict, List, Optional, Any, Union
#
# # 配置简单的日志
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)
#
#
# class AIClient:
#     """
#     与本地部署的 Ollama 服务进行交互的客户端。
#     主要用于处理 Llama 3.1 的 API 请求，特别是 JSON 格式的结构化输出。
#     """
#
#     def __init__(self,
#                  base_url: str = "http://localhost:11434",
#                  model_name: str = "llama3.1:latest",
#                  timeout: int = 120):
#         """
#         初始化客户端。
#
#         Args:
#             base_url: Ollama API 地址，默认为 http://localhost:11434
#             model_name: 模型名称，需与 'ollama list' 中的名称一致
#             timeout: 请求超时时间（秒），处理大文件摘要时建议设置较长
#         """
#         self.base_url = base_url.rstrip('/')
#         self.model_name = model_name
#         self.timeout = timeout
#         self.api_chat_endpoint = f"{self.base_url}/api/chat"
#
#         # 初始化检查
#         if not self.is_alive():
#             logger.warning(f"无法连接到 Ollama 服务 ({self.base_url})。请确保 Ollama 正在运行。")
#         else:
#             logger.info(f"Ollama 服务连接成功，使用模型: {self.model_name}")
#
#     def is_alive(self) -> bool:
#         """检查 Ollama 服务是否健康"""
#         try:
#             response = requests.get(self.base_url, timeout=5)
#             return response.status_code == 200
#         except requests.RequestException:
#             return False
#
#     def chat(self, messages: List[Dict[str, str]], json_mode: bool = False) -> str:
#         """
#         发送聊天请求并获取回复内容。
#
#         Args:
#             messages: 消息列表，格式如 [{"role": "user", "content": "..."}]
#             json_mode: 是否强制模型输出 JSON 格式 (Ollama 原生支持)
#
#         Returns:
#             str: 模型的回复文本
#         """
#         payload = {
#             "model": self.model_name,
#             "messages": messages,
#             "stream": False  # 关闭流式输出，便于一次性获取完整结果
#         }
#
#         if json_mode:
#             payload["format"] = "json"
#
#         try:
#             response = requests.post(
#                 self.api_chat_endpoint,
#                 json=payload,
#                 timeout=self.timeout
#             )
#             response.raise_for_status()
#
#             result = response.json()
#             return result.get('message', {}).get('content', '')
#
#         except requests.RequestException as e:
#             logger.error(f"LLM 请求失败: {e}")
#             raise ConnectionError(f"Failed to communicate with Ollama: {e}")
#
#     def query_json(self, prompt: str, system_prompt: str = "You are a helpful data assistant.") -> Dict[str, Any]:
#         """
#         专门用于获取 JSON 结构化数据的的高级方法。
#         包含自动清洗 Markdown 标记的逻辑。
#
#         Args:
#             prompt: 用户的指令
#             system_prompt: 系统设定
#
#         Returns:
#             dict: 解析后的 Python 字典
#         """
#         messages = [
#             {"role": "system", "content": system_prompt},
#             {"role": "user", "content": prompt}
#         ]
#
#         raw_response = self.chat(messages, json_mode=True)
#
#         # 数据清洗：有时候模型即使在 JSON 模式下也会包裹 ```json ... ```
#         clean_response = self._clean_markdown(raw_response)
#
#         try:
#             return json.loads(clean_response)
#         except json.JSONDecodeError:
#             logger.error(f"JSON 解析失败。原始返回: {raw_response}")
#             # 这里可以添加重试逻辑 (Phase 2 实现)
#             raise ValueError("LLM 未返回有效的 JSON 格式")
#
#     def _clean_markdown(self, text: str) -> str:
#         """去除可能存在的 Markdown 代码块标记"""
#         text = text.strip()
#         if text.startswith("```json"):
#             text = text[7:]
#         if text.startswith("```"):
#             text = text[3:]
#         if text.endswith("```"):
#             text = text[:-3]
#         return text.strip()
#
#
# # --- 单元测试/使用示例 ---
# if __name__ == "__main__":
#     # 简单的测试脚本，直接运行此文件可验证连接
#     print("正在测试本地 Ollama 连接...")
#
#     client = AIClient(model_name="llama3.1:latest")
#
#     # 1. 测试普通对话
#     try:
#         reply = client.chat([{"role": "user", "content": "Say hello to NL-STV project!"}])
#         print(f"\n[普通对话测试]\nAI: {reply}")
#     except Exception as e:
#         print(f"普通对话测试失败: {e}")
#
#     # 2. 测试 JSON 提取 (这是后续功能的核心)
#     print("\n[JSON 提取测试]")
#     test_prompt = """
#     Analyze this file metadata:
#     Filename: nyc_taxi_2025.csv
#     Columns: pickup_lat, pickup_lon, fare_amount
#
#     Return a JSON with "file_type" and "columns_detected".
#     """
#
#     try:
#         json_result = client.query_json(test_prompt)
#         print("解析结果:", json.dumps(json_result, indent=2))
#
#         if "file_type" in json_result:
#             print("✅ JSON 测试通过")
#         else:
#             print("❌ JSON 结构不符合预期")
#
#     except Exception as e:
#         print(f"JSON 测试失败: {e}")
#
import json
import logging
from typing import Dict, List, Any
from openai import OpenAI, APIError, AuthenticationError, APIConnectionError

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class AIClient:
    """
    使用 OpenAI SDK 封装 DeepSeek API 的客户端。
    保持与原 OllamaClient 相同的方法签名，以确保业务代码兼容性。
    """

    def __init__(self,
                 api_key: str = "sk-60160407beb64fb989638a7e1aaadf12",  # 在这里输入KEY
                 model_name: str = "deepseek-chat",  # deepseek-chat (V3)
                 timeout: int = 120):
        """
        初始化 DeepSeek 客户端。

        Args:
            api_key: DeepSeek API Key
            model_name: 模型名称 (deepseek-chat 或 deepseek-reasoner)
            timeout: 请求超时时间
        """
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
            timeout=timeout
        )
        self.model_name = model_name

        logger.info(f"AI Client (DeepSeek via OpenAI SDK) 初始化完成，使用模型: {self.model_name}")

    def is_alive(self) -> bool:
        """
        连通性测试。
        通过调用 list models 接口来验证 API Key 和网络连接。
        """
        try:
            self.client.models.list()
            return True
        except AuthenticationError:
            logger.error("API Key 无效")
            return False
        except APIConnectionError:
            logger.error("无法连接到 DeepSeek API 服务器")
            return False
        except Exception as e:
            logger.error(f"健康检查失败: {e}")
            return False

    def chat(self, messages: List[Dict[str, str]], json_mode: bool = False) -> str:
        """
        发送聊天请求。

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            json_mode: 是否强制输出 JSON 格式
        """
        try:
            # 构造请求参数
            params = {
                "model": self.model_name,
                "messages": messages,
                "stream": False,
                "temperature": 0.0 if json_mode else 0.7,  # JSON 模式通常需要更确定的输出
            }

            # 启用 JSON Mode (DeepSeek 支持 OpenAI 格式的 json_object)
            if json_mode:
                params["response_format"] = {"type": "json_object"}

            # 发起请求
            response = self.client.chat.completions.create(**params)

            # 获取内容
            content = response.choices[0].message.content
            return content

        except APIError as e:
            logger.error(f"DeepSeek API 返回错误: {e}")
            raise ConnectionError(f"DeepSeek API Error: {e}")
        except Exception as e:
            logger.error(f"LLM 请求发生未知错误: {e}")
            raise e

    def query_json(self, prompt: str, system_prompt: str = "You are a helpful data assistant.") -> Dict[str, Any]:
        """
        获取 JSON 结构化数据的高级封装。
        """
        # DeepSeek/OpenAI 要求：使用 json_mode 时，Prompt 中必须包含 "json" 字样
        if "json" not in system_prompt.lower() and "json" not in prompt.lower():
            system_prompt += " Please output the result strictly in JSON format."

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        # 调用 chat 获取原始字符串
        raw_response = self.chat(messages, json_mode=True)

        # 数据清洗 (防止 Markdown 包裹)
        clean_response = self._clean_markdown(raw_response)

        try:
            return json.loads(clean_response)
        except json.JSONDecodeError:
            logger.error(f"JSON 解析失败。原始返回: {raw_response}")
            raise ValueError("LLM 未返回有效的 JSON 格式")

    def _clean_markdown(self, text: str) -> str:
        """去除可能存在的 Markdown 代码块标记 (```json ... ```)"""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]

        if text.endswith("```"):
            text = text[:-3]
        return text.strip()


# --- 单元测试 ---
if __name__ == "__main__":
    print("正在测试 DeepSeek (OpenAI SDK) 连接...")

    # 请在此处填入您的真实 Key 进行测试
    client = AIClient(api_key="sk-60160407beb64fb989638a7e1aaadf12", model_name="deepseek-chat")

    # 1. 测试连通性
    if client.is_alive():
        print("✅ API 连接正常")
    else:
        print("❌ 无法连接，请检查 API Key 或网络")
        exit()

    # 2. 测试普通对话
    try:
        print("\n[普通对话测试] 9.11 和 9.9 哪个大？")
        reply = client.chat([{"role": "user", "content": "9.11 和 9.9 哪个大？只告诉我结果。"}])
        print(f"AI: {reply}")
    except Exception as e:
        print(f"普通对话失败: {e}")

    # 3. 测试 JSON
    try:
        print("\n[JSON 测试] 提取信息")
        res = client.query_json("""
        Analyze this file:
        Filename: nyc_taxi_2025.csv
        Columns: pickup_lat, pickup_lon, fare_amount
        Return JSON with "file_type" and "columns".
        """)
        print(f"JSON: {json.dumps(res, indent=2)}")
        try:
            if "file_type" in res:
                print("✅ JSON 测试通过")
        except Exception as e:
            print(f"JSON 测试失败: {e}")
    except Exception as e:
        print(f"JSON 测试失败: {e}")
