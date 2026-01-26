import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# ==========================================
# 1. 核心修复：解决路径引用问题
# ==========================================
# 获取当前文件 (test_code_generator.py) 的目录
current_dir = os.path.dirname(os.path.abspath(__file__))
# 获取父目录 (即 backend 目录)
backend_path = os.path.dirname(current_dir)
# 将 backend 目录加入 Python 搜索路径，这样才能识别 "core" 包
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# ==========================================
# 2. 解决依赖 Mock 问题 (防止缺少其他模块报错)
# ==========================================
# 这里的 Mock 是为了防止 import core.generation.code_generator 时
# 因为它内部 import 了其他你可能还没写好的模块而报错
# 如果你的环境已经很完整，这一段 sys.modules 可以注释掉
sys.modules['core.llm.AI_client'] = MagicMock()
# 注意：不要 Mock core.generation.code_generator 本身，因为我们要测它

# ==========================================
# 3. 正确导入模块
# ==========================================
# 我们需要导入 module 对象本身来做 patch.object
# 根据你的截图，路径是 core.generation.code_generator
from core.generation import viz_generator
# 同时导入类方便实例化
from core.generation.viz_generator import CodeGenerator


class TestCodeGenerator(unittest.TestCase):

    def setUp(self):
        # 模拟 AIClient 实例
        self.mock_llm = MagicMock()

        # 模拟数据摘要 (Summaries)
        self.dummy_summaries = [
            {
                "variable_name": "df_trips",
                "basic_stats": {
                    "column_stats": {"PULocationID": {}, "passenger_count": {}}
                }
            }
        ]

    # ==========================
    # 测试 Markdown 清洗 (无需 Patch)
    # ==========================
    def test_clean_markdown_normal(self):
        """测试去除标准的 markdown 代码块"""
        # 实例化时会尝试创建 STChartScaffold，我们在这里做一个临时的类 patch
        with patch.object(code_generator, 'STChartScaffold'):
            generator = CodeGenerator(self.mock_llm)
            raw_text = "```python\nimport pandas as pd\nprint('hello')\n```"
            expected = "import pandas as pd\nprint('hello')"
            result = generator._clean_markdown(raw_text)
            self.assertEqual(result, expected)

    def test_clean_markdown_no_lang(self):
        with patch.object(code_generator, 'STChartScaffold'):
            generator = CodeGenerator(self.mock_llm)
            raw_text = "```\nx = 1\n```"
            expected = "x = 1"
            result = generator._clean_markdown(raw_text)
            self.assertEqual(result, expected)

    def test_clean_markdown_whitespace(self):
        with patch.object(code_generator, 'STChartScaffold'):
            generator = CodeGenerator(self.mock_llm)
            raw_text = "   print('test')   "
            expected = "print('test')"
            result = generator._clean_markdown(raw_text)
            self.assertEqual(result, expected)

    # ==========================
    # 测试生成代码 (Generate)
    # ==========================
    # 使用 patch.object 针对导入的 code_generator 模块进行打补丁
    # 这样不管路径多深，只要模块对象对了就能 Mock 成功
    @patch.object(code_generator, 'STChartScaffold')
    def test_generate_code_flow(self, MockScaffold):
        """测试 generate_code 的主要流程"""
        # 1. 设置 Mock 行为
        mock_instance = MockScaffold.return_value
        mock_instance.get_system_prompt.return_value = "System Prompt"
        mock_instance.get_template.return_value = "def plot(data): pass"

        # 2. 设置 LLM 返回值
        self.mock_llm.chat.return_value = "```python\n# Generated Code\n```"

        # 3. 执行
        generator = CodeGenerator(self.mock_llm)
        code = generator.generate_code("Draw chart", self.dummy_summaries)

        # 4. 断言
        mock_instance.get_system_prompt.assert_called_once()
        self.mock_llm.chat.assert_called_once()
        self.assertEqual(code, "# Generated Code")

    # ==========================
    # 测试修复代码 (Fix)
    # ==========================
    @patch.object(code_generator, 'STChartScaffold')
    def test_fix_code_import_error(self, MockScaffold):
        """测试 Import 错误提示"""
        generator = CodeGenerator(self.mock_llm)
        self.mock_llm.chat.return_value = "fixed"

        generator.fix_code("import gpd", "ModuleNotFoundError: No module named 'gpd'", self.dummy_summaries)

        # 检查 Prompt 是否包含提示
        call_args = self.mock_llm.chat.call_args
        # user prompt 是 messages 列表的第二个元素
        user_prompt = call_args[0][0][1]['content']

        self.assertIn("[HINT: Import Error]", user_prompt)
        self.assertIn("import geopandas as gpd", user_prompt)

    @patch.object(code_generator, 'STChartScaffold')
    def test_fix_code_pandas_drop_error(self, MockScaffold):
        """测试 Pandas Drop 错误提示"""
        generator = CodeGenerator(self.mock_llm)
        self.mock_llm.chat.return_value = "fixed"

        generator.fix_code("df.drop('col')", "['col'] not found in axis", self.dummy_summaries)

        user_prompt = self.mock_llm.chat.call_args[0][0][1]['content']
        self.assertIn("[HINT: DataFrame Column Error]", user_prompt)

    @patch.object(code_generator, 'STChartScaffold')
    def test_fix_code_logic_points_from_xy(self, MockScaffold):
        """测试几何逻辑错误提示"""
        generator = CodeGenerator(self.mock_llm)
        self.mock_llm.chat.return_value = "fixed"

        generator.fix_code("gpd.points_from_xy(df.ID, df.ID)", "Error", self.dummy_summaries)

        user_prompt = self.mock_llm.chat.call_args[0][0][1]['content']
        self.assertIn("[HINT: LOGIC ERROR - DO NOT CREATE GEOMETRY FROM IDs]", user_prompt)

    @patch.object(code_generator, 'STChartScaffold')
    def test_fix_code_key_error(self, MockScaffold):
        """测试 KeyError 提示"""
        generator = CodeGenerator(self.mock_llm)
        self.mock_llm.chat.return_value = "fixed"

        generator.fix_code("df['Zone']", "KeyError: 'Zone'", self.dummy_summaries)

        user_prompt = self.mock_llm.chat.call_args[0][0][1]['content']
        self.assertIn("[HINT: KeyError detected]", user_prompt)

    @patch.object(code_generator, 'STChartScaffold')
    def test_fix_code_return_cleaned(self, MockScaffold):
        """测试修复后的代码是否被清洗"""
        generator = CodeGenerator(self.mock_llm)
        self.mock_llm.chat.return_value = "```python\ncleaned_code\n```"

        result = generator.fix_code("bad", "error", self.dummy_summaries)
        self.assertEqual(result, "cleaned_code")


if __name__ == '__main__':
    unittest.main()