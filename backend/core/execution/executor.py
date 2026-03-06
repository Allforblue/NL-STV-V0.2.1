import pandas as pd
import geopandas as gpd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import random
import json
from shapely.geometry import Point, Polygon, LineString
import traceback
import sys
import io
import textwrap
from typing import Dict, Any, List, Optional
import logging
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ComponentResult(BaseModel):
    """单个组件的执行结果"""
    component_id: str
    data: Any
    summary_stats: Optional[Dict[str, Any]] = None


class DashboardExecutionResult(BaseModel):
    """整个看板的执行结果包"""
    success: bool
    results: Dict[str, ComponentResult] = {}
    global_insight_data: Dict[str, Any] = {}
    error: Optional[str] = None
    code: str = ""


class CodeExecutor:
    def __init__(self):
        # 预加载常用库，增加时空计算核心库，防止 LLM 忘记 import
        self.global_context = {
            "pd": pd,
            "gpd": gpd,
            "px": px,
            "go": go,
            "np": np,
            "random": random,
            "json": json,
            "Point": Point,
            "Polygon": Polygon,
            "LineString": LineString,
            "print": print
        }

    def _dedent_code(self, code: str) -> str:
        """精准去除多余缩进"""
        return textwrap.dedent(code).strip()

    def _make_serializable(self, obj: Any) -> Any:
        """
        [增强] 递归将 Numpy/Pandas 类型转换为 Python 原生类型。
        [修复] 增加了对复杂对象（如 Plotly Figure）的拦截，防止深度递归破坏动画帧或引发卡顿。
        """
        # 0. [核心修复] 拦截 Plotly 对象，使用官方序列化方法，防止内部的 frames 数组在下方递归中丢失
        # if hasattr(obj, "to_plotly_json"):
        #     return obj.to_plotly_json()

        # [核心修复] 使用 to_dict() 替代 to_plotly_json()
        # to_dict() 是 Plotly 最全的序列化方法，能确保 frames 不丢失
        if hasattr(obj, "to_dict") and hasattr(obj, "layout") and hasattr(obj, "data"):
            return obj.to_dict()

        # 1. 处理 Numpy 基础类型
        if isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
            if np.isnan(obj) or np.isinf(obj): return None
            return float(obj)
        elif isinstance(obj, (np.bool_, bool)):
            return bool(obj)

        # 2. 处理 Pandas 时间戳与时间差
        elif isinstance(obj, (pd.Timestamp, pd.Timedelta)):
            return str(obj)

        # 3. 处理地理几何对象接口 (为 InsightExtractor 提供描述)
        elif hasattr(obj, "__geo_interface__"):
            return "GEOMETRY_OBJECT"

        # 4. 递归处理集合/数组
        elif isinstance(obj, np.ndarray):
            return self._make_serializable(obj.tolist())
        elif isinstance(obj, dict):
            # 只有纯字典才深度清洗
            return {str(k): self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple, set)):
            return [self._make_serializable(v) for v in obj]
        else:
            return obj

    def execute_dashboard_logic(
            self,
            code_str: str,
            data_context: Dict[str, Any],
            component_ids: List[str]
    ) -> DashboardExecutionResult:
        """
        执行看板逻辑并捕获多个组件结果，针对超大规模数据增强了统计稳定性。
        """
        clean_code = self._dedent_code(code_str)
        local_scope = {}

        old_stdout = sys.stdout
        redirected_output = io.StringIO()
        sys.stdout = redirected_output

        try:
            logger.info(">>> [Executor] 启动沙箱执行环境...")

            # [关键] 深度隔离数据上下文
            # 确保在多表 Join 或空间计算时，不会通过引用修改 Session 原始数据
            safe_data_context = {}
            for k, v in data_context.items():
                if hasattr(v, 'copy'):
                    safe_data_context[k] = v.copy()
                else:
                    safe_data_context[k] = v

            # 执行代码块
            exec(clean_code, self.global_context, local_scope)

            if "get_dashboard_data" not in local_scope:
                raise ValueError("Generated code missing 'get_dashboard_data' function.")

            # 调用生成函数
            all_results = local_scope["get_dashboard_data"](safe_data_context)

            final_results = {}
            insight_payload = {}

            for cid in component_ids:
                if cid in all_results:
                    res_obj = all_results[cid]
                    summary = {}

                    try:
                        # 3.1 结构化数据特征提取 (DataFrame / GeoDataFrame)
                        if isinstance(res_obj, (pd.DataFrame, pd.Series, gpd.GeoDataFrame)):
                            row_count = len(res_obj)
                            # 性能防护：对于超大规模数据，Insight 提取仅使用头部采样
                            stats_df = res_obj if row_count < 100000 else res_obj.sample(100000)

                            if hasattr(res_obj, 'describe'):
                                summary["basic_stats"] = self._make_serializable(
                                    stats_df.describe(include='all').to_dict())

                            summary["row_count"] = row_count

                            # --- [新增] 地理空间指纹提取 ---
                            if isinstance(res_obj, gpd.GeoDataFrame) and not res_obj.empty:
                                summary["spatial_info"] = {
                                    "crs": str(res_obj.crs),
                                    "geom_type": str(res_obj.geom_type.mode()[0]) if not res_obj.empty else None,
                                    "bounds": [float(x) for x in res_obj.total_bounds]  # [minx, miny, maxx, maxy]
                                }

                            # --- [核心] 时间序列特征提取 ---
                            # 识别时间列或时间索引
                            time_cols = [c for c in res_obj.columns if
                                         pd.api.types.is_datetime64_any_dtype(res_obj[c])] if isinstance(res_obj,
                                                                                                         pd.DataFrame) else []
                            is_time_index = pd.api.types.is_datetime64_any_dtype(res_obj.index)

                            if is_time_index or time_cols:
                                num_cols = res_obj.select_dtypes(include=[np.number]).columns
                                if not num_cols.empty:
                                    col = num_cols[0]
                                    series = res_obj[col]
                                    summary["temporal_insights"] = {
                                        "peak_value": float(series.max()),
                                        "valley_value": float(series.min()),
                                        "start_time": str(
                                            res_obj.index[0] if is_time_index else res_obj[time_cols[0]].min()),
                                        "end_time": str(
                                            res_obj.index[-1] if is_time_index else res_obj[time_cols[0]].max())
                                    }

                        # 3.2 可视化对象特征提取
                        elif hasattr(res_obj, 'data') and isinstance(res_obj.data, (list, tuple)):
                            if len(res_obj.data) > 0:
                                trace = res_obj.data[0]
                                summary["viz_type"] = type(res_obj).__name__
                                # 记录数据点大致规模，辅助洞察生成
                                for attr in ['x', 'lat', 'values']:
                                    if hasattr(trace, attr) and getattr(trace, attr) is not None:
                                        summary["data_points"] = len(getattr(trace, attr))
                                        break

                    except Exception as e:
                        logger.warning(f"Feature extraction failed for {cid}: {e}")

                    if summary:
                        insight_payload[cid] = summary

                    # 这里的 res_obj 尚未执行 _make_serializable，保留了原始的 Figure 对象
                    final_results[cid] = ComponentResult(
                        component_id=cid,
                        data=res_obj,
                        summary_stats=summary
                    )

            sys.stdout = old_stdout

            # [关键修复生效处] 这里的清洗现在不会破坏 Plotly 动画帧了
            clean_results = self._make_serializable(final_results)
            clean_insight = self._make_serializable(insight_payload)

            return DashboardExecutionResult(
                success=True,
                results=clean_results,
                global_insight_data=clean_insight,
                code=clean_code
            )

        except Exception:
            sys.stdout = old_stdout
            error_trace = traceback.format_exc()
            logger.error(f"Sandbox Execution Failed:\n{error_trace}")
            return DashboardExecutionResult(
                success=False,
                error=error_trace,
                code=clean_code
            )
        finally:
            sys.stdout = old_stdout
            captured = redirected_output.getvalue()
            if captured.strip():
                logger.info(f"Sandbox Log Output:\n{captured.strip()}")