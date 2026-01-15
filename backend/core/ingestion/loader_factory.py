import pandas as pd
import geopandas as gpd
from abc import ABC, abstractmethod


class BaseLoader(ABC):
    @abstractmethod
    def load(self, path: str): pass

    @abstractmethod
    def peek(self, path: str, n: int = 5): pass

    def count_rows(self, path: str) -> int:
        # 默认实现，子类可优化（如 Parquet 直接读元数据）
        return len(self.load(path))


class CSVLoader(BaseLoader):
    def load(self, path: str):
        return pd.read_csv(path)

    def peek(self, path: str, n: int = 5):
        return pd.read_csv(path, nrows=n)


class ParquetLoader(BaseLoader):
    def load(self, path: str):
        return pd.read_parquet(path)

    def peek(self, path: str, n: int = 5):
        # Parquet 不支持直接 nrows，通常读取后再 head
        return pd.read_parquet(path).head(n)


class SHPLoader(BaseLoader):
    """
    Shapefile 加载器：时空数据的关键。
    它返回的是 GeoDataFrame，自带 geometry 属性。
    """

    def load(self, path: str):
        return gpd.read_file(path)

    def peek(self, path: str, n: int = 5):
        return gpd.read_file(path, rows=n)


class LoaderFactory:
    @staticmethod
    def get_loader(path: str) -> BaseLoader:
        ext = path.split('.')[-1].lower()
        if ext == 'csv':
            return CSVLoader()
        elif ext == 'parquet':
            return ParquetLoader()
        elif ext in ['shp', 'geojson', 'json']:
            return SHPLoader()
        else:
            raise ValueError(f"Unsupported file format: {ext}")