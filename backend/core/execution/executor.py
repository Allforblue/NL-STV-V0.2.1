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
        [新增] 递归将 Numpy 类型转换为 Python 原生类型，防止 FastAPI 序列化报错
        """
        if isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
            # 处理 NaN 和 Inf，JSON 不支持
            if np.isnan(obj) or np.isinf(obj):
                return None
            return float(obj)
        elif isinstance(obj, (np.bool_, bool)):  # 覆盖 numpy bool
            return bool(obj)
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
        执行看板逻辑并捕获多个组件结果
        """
        clean_code = self._dedent_code(code_str)
        local_scope = {}

        # 准备执行输出重定向
        old_stdout = sys.stdout
        redirected_output = io.StringIO()
        sys.stdout = redirected_output

        try:
            logger.info("Executing dashboard logic...")

            # 1. 执行代码定义
            exec(clean_code, self.global_context, local_scope)

            if "get_dashboard_data" not in local_scope:
                raise ValueError("Generated code must contain 'get_dashboard_data(data_context)' function.")

            # 2. 调用逻辑函数
            all_results = local_scope["get_dashboard_data"](data_context)

            # 3. 结果解析
            final_results = {}
            insight_payload = {}

            for cid in component_ids:
                if cid in all_results:
                    res_obj = all_results[cid]
                    summary = None

                    try:
                        # 3.1 DataFrame 特征提取
                        if hasattr(res_obj, 'describe'):
                            desc = res_obj.describe(include='all').to_dict()
                            # 过滤掉全是 NaN 的列
                            summary = {k: v for k, v in desc.items() if isinstance(v, dict)}

                        # 3.2 Plotly Figure 特征提取
                        elif hasattr(res_obj, 'data') and len(res_obj.data) > 0:
                            trace = res_obj.data[0]
                            trace_stats = {}
                            # 尝试提取部分数据预览
                            for key in ['x', 'y', 'lat', 'lon', 'values']:
                                if hasattr(trace, key) and getattr(trace, key) is not None:
                                    arr = getattr(trace, key)
                                    if hasattr(arr, '__len__'):
                                        trace_stats[key] = {
                                            "count": len(arr),
                                            "sample_len": len(arr)
                                        }
                            if trace_stats:
                                summary = {"figure_preview": trace_stats}

                        # 3.3 文本
                        elif isinstance(res_obj, str):
                            summary = {"text": res_obj[:100]}

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

            # [关键修复] 在返回前清洗所有数据，移除 Numpy 类型
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