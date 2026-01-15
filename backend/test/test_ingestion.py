import os
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from pathlib import Path

# 假设你的项目根目录在 backend 上一层，或者你已经在 pythonpath 中
# 请根据实际情况调整 import 路径
from core.ingestion.ingestion import IngestionManager


# ==========================================
# 第一部分：单元测试 (使用 Mock，不读取真实文件)
# 目的：测试逻辑分支、变量命名、错误捕获
# ==========================================

class TestIngestionManagerUnit:

    @pytest.fixture
    def manager(self, tmp_path):
        """创建一个使用临时目录的 Manager 实例"""
        # 使用 tmp_path 防止在项目里创建垃圾文件夹
        return IngestionManager(sandbox_dir=str(tmp_path))

    @patch("core.ingestion.ingestion.LoaderFactory")
    def test_load_all_to_context_peek(self, mock_factory, manager):
        """测试：默认模式下应该调用 peek (采样)"""
        # 1. 准备 Mock
        mock_loader = MagicMock()
        # 模拟返回一个空的 DataFrame
        mock_loader.peek.return_value = pd.DataFrame({"col1": [1, 2]})
        mock_factory.get_loader.return_value = mock_loader

        # 2. 执行
        file_paths = ["data_sandbox/test_data.csv"]
        context = manager.load_all_to_context(file_paths, use_full=False)

        # 3. 断言
        # 检查是否生成了正确的变量名 (df_ + 文件名stem + 小写)
        assert "df_test_data" in context
        # 检查是否调用了 peek 而不是 load
        mock_loader.peek.assert_called_once()
        mock_loader.load.assert_not_called()
        # 检查参数 n=50000
        mock_loader.peek.assert_called_with("data_sandbox/test_data.csv", n=50000)

    @patch("core.ingestion.ingestion.LoaderFactory")
    def test_load_all_to_context_full(self, mock_factory, manager):
        """测试：use_full=True 时应该调用 load (全量)"""
        mock_loader = MagicMock()
        mock_loader.load.return_value = pd.DataFrame({"col1": [1, 2]})
        mock_factory.get_loader.return_value = mock_loader

        file_paths = ["data_sandbox/my_shapefile.shp"]
        context = manager.load_all_to_context(file_paths, use_full=True)

        assert "df_my_shapefile" in context
        mock_loader.load.assert_called_once()
        mock_loader.peek.assert_not_called()

    @patch("core.ingestion.ingestion.LoaderFactory")
    def test_error_handling(self, mock_factory, manager):
        """测试：单个文件加载失败不应导致程序崩溃"""
        # 让 get_loader 抛出异常
        mock_factory.get_loader.side_effect = Exception("Format not supported")

        file_paths = ["bad_file.xyz"]
        context = manager.load_all_to_context(file_paths)

        # 应该返回空字典，而不是抛出异常
        assert context == {}


# ==========================================
# 第二部分：集成测试 (使用你截图中的真实文件)
# 目的：确保能真正读取沙箱中的文件
# ==========================================

class TestIngestionRealFiles:

    @pytest.fixture
    def real_sandbox_path(self):
        """指向你真实的沙箱路径 (自动适配路径)"""
        # 获取当前测试文件所在的目录 (例如: .../backend/test)
        current_test_dir = Path(__file__).parent

        # 方案1: 假设测试在 backend/test 下，需要往上跳一级 (.parent) 找到 backend
        path_from_subdir = current_test_dir.parent / "core" / "data_sandbox"

        # 方案2: 假设测试直接在 backend 下
        path_from_root = current_test_dir / "core" / "data_sandbox"

        # 检查并返回存在的那个路径
        if path_from_subdir.exists():
            print(f"\n[Debug] 找到沙箱路径: {path_from_subdir}")
            return path_from_subdir
        elif path_from_root.exists():
            print(f"\n[Debug] 找到沙箱路径: {path_from_root}")
            return path_from_root
        else:
            # 如果都找不到，打印出来方便调试
            print(f"\n[Error] 无法找到沙箱路径。尝试了:\n1. {path_from_subdir}\n2. {path_from_root}")
            return path_from_subdir

    def test_load_real_csv(self, real_sandbox_path):
        """测试读取 taxi_zone_lookup.csv"""
        csv_path = real_sandbox_path / "taxi_zone_lookup.csv"

        # 如果文件不存在则跳过测试 (防止CI报错)
        if not csv_path.exists():
            pytest.skip(f"文件未找到: {csv_path}，跳过真实文件测试")

        manager = IngestionManager(sandbox_dir=str(real_sandbox_path))

        # 执行加载
        context = manager.load_all_to_context([str(csv_path)], use_full=False)

        # 验证
        var_name = "df_taxi_zone_lookup"
        assert var_name in context
        df = context[var_name]

        # 基本验证：DataFrame 应该有内容
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        print(f"\n[Success] Loaded CSV shape: {df.shape}")

    def test_load_real_parquet(self, real_sandbox_path):
        """测试读取 yellow_tripdata_2025-01.parquet"""
        parquet_path = real_sandbox_path / "yellow_tripdata_2025-01.parquet"

        if not parquet_path.exists():
            pytest.skip(f"文件未找到: {parquet_path}")

        manager = IngestionManager(sandbox_dir=str(real_sandbox_path))

        # Parquet 通常比较大，我们测试 peek 模式
        context = manager.load_all_to_context([str(parquet_path)], use_full=False)

        var_name = "df_yellow_tripdata_2025-01"
        assert var_name in context
        df = context[var_name]

        assert isinstance(df, pd.DataFrame)
        # 验证是否遵守了采样限制 (虽然 peek 具体实现取决于 Loader，但通常不会超过 50k)
        assert len(df) <= 50000
        print(f"\n[Success] Loaded Parquet sample shape: {df.shape}")