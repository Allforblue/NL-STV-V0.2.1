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
        # 预加载常用库，防止 LLM 忘记 import 导致报错
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
        [增强] 递归将 Numpy/Pandas 类型转换为 Python 原生类型，防止序列化报错
        """
        # 1. 处理 Numpy 基础类型
        if isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
            if np.isnan(obj) or np.isinf(obj): return None
            return float(obj)
        elif isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        # 2. [新增] 处理 Pandas 时间戳
        elif isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        # 3. 处理集合/数组
        elif isinstance(obj, np.ndarray):
            return self._make_serializable(obj.tolist())
        elif isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
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
        执行看板逻辑并捕获多个组件结果，增加时间特征自动捕捉逻辑
        """
        clean_code = self._dedent_code(code_str)
        local_scope = {}

        old_stdout = sys.stdout
        redirected_output = io.StringIO()
        sys.stdout = redirected_output

        try:
            logger.info("Executing dashboard logic...")

            exec(clean_code, self.global_context, local_scope)

            if "get_dashboard_data" not in local_scope:
                raise ValueError("Generated code must contain 'get_dashboard_data(data_context)' function.")

            all_results = local_scope["get_dashboard_data"](data_context)

            final_results = {}
            insight_payload = {}

            for cid in component_ids:
                if cid in all_results:
                    res_obj = all_results[cid]
                    summary = {}

                    try:
                        # 3.1 DataFrame 特征提取 (增强时间分析)
                        if hasattr(res_obj, 'to_dict'):
                            # 基础描述统计
                            if len(res_obj) < 100:
                                summary["data_raw"] = res_obj.to_dict()
                            else:
                                desc = res_obj.describe(include='all').to_dict()
                                summary["basic_stats"] = {k: v for k, v in desc.items() if isinstance(v, dict)}

                            # --- [核心新增] 时间序列特征捕捉 ---
                            # 如果索引或列包含时间属性，提取波峰/波谷/趋势
                            target_df = res_obj if isinstance(res_obj, pd.DataFrame) else None
                            if target_df is not None:
                                time_cols = [c for c in target_df.columns if
                                             pd.api.types.is_datetime64_any_dtype(target_df[c])]
                                # 若索引是时间类型（resample 后的常态）
                                is_time_index = pd.api.types.is_datetime64_any_dtype(target_df.index)

                                if is_time_index or time_cols:
                                    # 寻找数值列进行趋势分析
                                    num_cols = target_df.select_dtypes(include=[np.number]).columns
                                    if not num_cols.empty:
                                        col = num_cols[0]
                                        summary["temporal_insights"] = {
                                            "max_value": target_df[col].max(),
                                            "peak_time": str(target_df[col].idxmax()) if is_time_index else None,
                                            "min_value": target_df[col].min(),
                                            "valley_time": str(target_df[col].idxmin()) if is_time_index else None,
                                            "overall_growth": float((target_df[col].iloc[-1] - target_df[col].iloc[0]) /
                                                                    target_df[col].iloc[0]) if len(target_df) > 1 and
                                                                                               target_df[col].iloc[
                                                                                                   0] != 0 else 0
                                        }

                        # 3.2 Plotly Figure 特征提取
                        elif hasattr(res_obj, 'data') and len(res_obj.data) > 0:
                            trace = res_obj.data[0]
                            trace_stats = {}
                            for key in ['x', 'y', 'lat', 'lon', 'values']:
                                if hasattr(trace, key) and getattr(trace, key) is not None:
                                    arr = getattr(trace, key)
                                    if hasattr(arr, '__len__'):
                                        trace_stats[key] = {"count": len(arr)}
                            if trace_stats: summary["figure_preview"] = trace_stats

                        # 3.3 文本
                        elif isinstance(res_obj, str):
                            summary = {"text": res_obj[:200]}

                    except Exception as e:
                        logger.warning(f"Feature extraction warning for {cid}: {e}")

                    if summary:
                        insight_payload[cid] = summary

                    final_results[cid] = ComponentResult(
                        component_id=cid,
                        data=res_obj,
                        summary_stats=summary
                    )

            sys.stdout = old_stdout
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
            logger.error(f"Execution Failed:\n{error_trace}")
            return DashboardExecutionResult(
                success=False,
                error=error_trace,
                code=clean_code
            )