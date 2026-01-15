import pytest
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

# 适配引用路径
from core.execution.executor import CodeExecutor


class TestCodeExecutor:

    @pytest.fixture
    def executor(self):
        return CodeExecutor()

    @pytest.fixture
    def sample_context(self):
        """准备一个标准的测试数据上下文"""
        df = pd.DataFrame({
            "A": [1, 2, 3],
            "B": [10, 20, 30]
        })
        return {"df_test": df}

    def test_dedent_code(self, executor):
        """测试代码缩进清洗功能"""
        raw_code = """
            def foo():
                return 1
        """
        # dedent 后应该是顶格写的
        clean = executor._dedent_code(raw_code)
        assert clean.startswith("def foo():")
        assert "    return 1" in clean

    def test_execute_success_logic(self, executor, sample_context):
        """测试正常执行流程：读取数据 -> 处理 -> 返回结果"""

        # 模拟 LLM 生成的代码
        code = """
        def get_dashboard_data(data_context):
            df = data_context['df_test']
            # 简单的逻辑：B列求和
            total = df['B'].sum()
            return {
                "kpi_card": total
            }
        """

        result = executor.execute_dashboard_logic(
            code_str=code,
            data_context=sample_context,
            component_ids=["kpi_card"]
        )

        assert result.success is True
        assert result.error is None
        # 验证结果字典
        assert "kpi_card" in result.results
        # 验证数值正确性 (10+20+30 = 60)
        assert result.results["kpi_card"].data == 60

    def test_execute_auto_summary_stats(self, executor, sample_context):
        """测试：当返回的是 DataFrame 时，是否自动提取了统计信息"""

        code = """
        def get_dashboard_data(data_context):
            # 直接返回原始 DF
            return {
                "table_1": data_context['df_test']
            }
        """

        result = executor.execute_dashboard_logic(
            code_str=code,
            data_context=sample_context,
            component_ids=["table_1"]
        )

        assert result.success is True
        res_obj = result.results["table_1"]

        # 验证是否自动生成了 summary_stats
        assert res_obj.summary_stats is not None
        # DataFrame.describe() 生成的字典应该包含 count, mean 等
        assert "count" in res_obj.summary_stats["A"]

    def test_error_missing_function(self, executor, sample_context):
        """测试：代码中没有定义规定的 get_dashboard_data 函数"""

        code = """
        def wrong_function_name(ctx):
            return {}
        """

        result = executor.execute_dashboard_logic(code, sample_context, [])

        assert result.success is False
        # [修改] 拆分断言，避开复杂的引号匹配问题
        # 只要确认报错信息里包含核心函数名和错误提示关键词即可
        assert "get_dashboard_data" in result.error
        assert "Generated code must contain" in result.error

    def test_error_syntax(self, executor, sample_context):
        """测试：Python 语法错误"""

        code = """
        def get_dashboard_data(ctx):
            return {  # 缺少闭合括号
        """

        result = executor.execute_dashboard_logic(code, sample_context, [])

        assert result.success is False
        assert "SyntaxError" in result.error

    def test_error_runtime(self, executor, sample_context):
        """测试：运行时逻辑错误 (如除以零)"""

        code = """
        def get_dashboard_data(ctx):
            x = 1 / 0
            return {}
        """

        result = executor.execute_dashboard_logic(code, sample_context, [])

        assert result.success is False
        assert "ZeroDivisionError" in result.error
        # 确保 Traceback 被捕获，方便发回给 LLM 修复
        assert "Traceback" in result.error

    def test_security_imports(self, executor, sample_context):
        """
        测试预加载的全局库是否可用 (pd, gpd, px)
        """
        code = """
        def get_dashboard_data(ctx):
            # 尝试使用 pd 和 px，虽然没有 import，但 global_context 应该有
            df = pd.DataFrame({'x': [1]})
            # 只是测试引用是否报错，不需要真画图
            return {"test": "ok"}
        """

        result = executor.execute_dashboard_logic(code, sample_context, ["test"])
        assert result.success is True