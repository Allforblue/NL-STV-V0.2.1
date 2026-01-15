import pytest
import pandas as pd
import numpy as np
import geopandas as gpd
from shapely.geometry import Point, Polygon
from pathlib import Path

# 适配引用路径
from core.profiler.basic_stats import get_dataset_fingerprint, get_column_stats


# ==========================================
# 第一部分：单元测试 (使用内存造的数据)
# ==========================================

class TestBasicStatsUnit:

    @pytest.fixture
    def standard_df(self):
        """创建一个包含 数值、字符串、时间、空值 的标准 DataFrame"""
        return pd.DataFrame({
            "age": [25, 30, 35, np.nan],  # 数值 + 空值
            "city": ["NY", "London", "Paris", "NY"],  # 字符串
            "score": [1.5, 2.5, 3.5, 4.5],  # 浮点数
            "date": pd.to_datetime(["2023-01-01", "2023-01-02", "2023-01-03", "2023-01-04"])  # 时间
        })

    def test_standard_stats(self, standard_df):
        """测试标准 DataFrame 的统计结果"""
        result = get_dataset_fingerprint(standard_df)

        # 1. 验证整体结构
        assert result["rows"] == 4
        assert result["cols"] == 4
        assert result["is_geospatial"] is False

        # 2. 验证数值列 (age)
        age_stats = result["column_stats"]["age"]
        assert age_stats["missing_count"] == 1
        assert age_stats["min"] == 25.0
        assert age_stats["max"] == 35.0
        assert age_stats["mean"] == 30.0  # (25+30+35)/3

        # 3. 验证样本数据类型 (必须转为 string)
        # 你的代码里写了 samples = [str(s) for s in samples]
        # 即使是时间类型，样本里也应该是字符串
        date_stats = result["column_stats"]["date"]
        assert isinstance(date_stats["samples"][0], str)
        assert "2023" in date_stats["samples"][0]

    def test_geo_stats(self):
        """测试 GeoDataFrame 的特有统计"""
        # 创建两个点和一个多边形
        df = pd.DataFrame({'val': [1, 2]})
        gdf = gpd.GeoDataFrame(df, geometry=[Point(0, 0), Point(1, 1)])
        gdf.crs = "EPSG:4326"  # 设置坐标系

        result = get_dataset_fingerprint(gdf)

        # 1. 验证地理标志
        assert result["is_geospatial"] is True
        assert "EPSG:4326" in result["crs"]

        # 2. 验证 Geometry 列统计
        geo_stats = result["column_stats"]["geometry"]
        assert geo_stats["dtype"] == "geometry"
        assert geo_stats["geom_type"] == "Point"

        # 3. 验证边界 (Bounds) [minx, miny, maxx, maxy]
        # (0,0) 到 (1,1) -> [0.0, 0.0, 1.0, 1.0]
        assert geo_stats["bounds"] == [0.0, 0.0, 1.0, 1.0]


# ==========================================
# 第二部分：集成测试 (使用真实沙箱文件)
# ==========================================

class TestBasicStatsIntegration:

    @pytest.fixture
    def real_sandbox_path(self):
        """自动查找沙箱路径 (复用之前的逻辑)"""
        current_test_dir = Path(__file__).parent
        path_from_subdir = current_test_dir.parent / "core" / "data_sandbox"
        path_from_root = current_test_dir / "core" / "data_sandbox"

        if path_from_subdir.exists(): return path_from_subdir
        return path_from_root

    def test_profiler_on_real_csv(self, real_sandbox_path):
        """测试 taxi_zone_lookup.csv"""
        csv_path = real_sandbox_path / "taxi_zone_lookup.csv"
        if not csv_path.exists(): pytest.skip("CSV文件不存在")

        df = pd.read_csv(csv_path)
        result = get_dataset_fingerprint(df)

        print(f"\n[CSV Profile] Rows: {result['rows']}, Cols: {result['cols']}")

        # 断言我们知道存在的列
        assert "LocationID" in result["column_stats"]
        assert "Zone" in result["column_stats"]
        # LocationID 应该是数字
        assert "min" in result["column_stats"]["LocationID"]

    def test_profiler_on_real_parquet(self, real_sandbox_path):
        """测试 yellow_tripdata...parquet"""
        pq_path = real_sandbox_path / "yellow_tripdata_2025-01.parquet"
        if not pq_path.exists(): pytest.skip("Parquet文件不存在")

        # 读取前 1000 行做测试即可，不用全读
        df = pd.read_parquet(pq_path).head(1000)
        result = get_dataset_fingerprint(df)

        print(f"\n[Parquet Profile] Rows: {result['rows']}")

        # 验证时间列是否被正确处理 (tpep_pickup_datetime)
        pickup_stats = result["column_stats"].get("tpep_pickup_datetime")
        if pickup_stats:
            # 确保样本被转成了字符串，没有报错
            assert isinstance(pickup_stats["samples"][0], str)