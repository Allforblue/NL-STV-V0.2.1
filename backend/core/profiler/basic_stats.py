import pandas as pd
import geopandas as gpd
import numpy as np
from typing import Dict, Any, List


def get_column_stats(df: pd.DataFrame) -> Dict[str, Any]:
    """
    提取每一列的基础统计信息，用于构建 LLM Prompt。
    不涉及复杂计算，重点在于类型、范围和样本值。
    """
    stats = {}

    # 确保 geometry 列也被包含（如果是 GeoDataFrame）
    columns_to_process = df.columns.tolist()

    # GeoDataFrame 有时 geometry 列不显示在 columns 中（视版本而定），强制检查
    if isinstance(df, gpd.GeoDataFrame) and df.geometry.name not in columns_to_process:
        columns_to_process.append(df.geometry.name)

    for col in df.columns:
        col_type = str(df[col].dtype)
        # 获取非空样本 (最多 3 个)
        samples = df[col].dropna().head(3).tolist()
        # 将 timestamp 转字符串以免 JSON 序列化报错
        samples = [str(s) for s in samples]

        col_info = {
            "dtype": col_type,
            "samples": samples,
            "missing_count": int(df[col].isna().sum())
        }

        # 针对数值类型的额外统计
        if pd.api.types.is_numeric_dtype(df[col]):
            try:
                col_info["min"] = float(df[col].min())
                col_info["max"] = float(df[col].max())
                col_info["mean"] = float(df[col].mean())
            except Exception:
                pass  # 忽略无法计算的情况

        # 针对几何类型的额外统计 (GeoPandas)
        if isinstance(df, gpd.GeoDataFrame) and col == df.geometry.name:
            col_info["dtype"] = "geometry"
            col_info["geom_type"] = df.geom_type.mode()[0] if not df.empty else "unknown"
            # 获取边界框
            bounds = df.total_bounds  # [minx, miny, maxx, maxy]
            col_info["bounds"] = bounds.tolist() if len(bounds) == 4 else []

        stats[col] = col_info

    return stats


def get_dataset_fingerprint(df: pd.DataFrame) -> Dict[str, Any]:
    """
    获取数据集层面的指纹信息
    """
    fingerprint = {
        "rows": len(df),
        "cols": len(df.columns),
        "column_stats": get_column_stats(df)
    }

    # 检测是否为 GeoDataFrame 并提取 CRS
    if isinstance(df, gpd.GeoDataFrame):
        fingerprint["is_geospatial"] = True
        fingerprint["crs"] = df.crs.to_string() if df.crs else "MISSING"
    else:
        fingerprint["is_geospatial"] = False

    return fingerprint