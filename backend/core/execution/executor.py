import pandas as pd
import geopandas as gpd
import plotly.express as px
import plotly.graph_objects as go
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
    data: Any  # 可能是 Plotly JSON, 也可能是 GeoJSON (用于 Deck.gl)
    summary_stats: Optional[Dict[str, Any]] = None  # 该组件对应数据的统计特征


class DashboardExecutionResult(BaseModel):
    """整个看板的执行结果包"""
    success: bool
    results: Dict[str, ComponentResult] = {}
    global_insight_data: Dict[str, Any] = {}  # 供 Insight Generator 使用的原始数据
    error: Optional[str] = None
    code: str = ""


class CodeExecutor:
    def __init__(self):
        # 预加载基础库，减少 LLM 重复 import
        self.global_context = {
            "pd": pd,
            "gpd": gpd,
            "px": px,
            "go": go,
            "print": print
        }

    def _dedent_code(self, code: str) -> str:
        """精准去除多余缩进"""
        return textwrap.dedent(code).strip()

    def execute_dashboard_logic(
            self,
            code_str: str,
            data_context: Dict[str, Any],
            component_ids: List[str]
    ) -> DashboardExecutionResult:
        """
        执行看板逻辑并捕获多个组件结果

        Args:
            code_str: AI 生成的 Python 代码
            data_context: 原始数据字典
            component_ids: DashboardPlanner 规划的组件 ID 列表
        """
        clean_code = self._dedent_code(code_str)
        local_scope = {}

        # 准备执行输出重定向（捕获 print）
        old_stdout = sys.stdout
        redirected_output = io.StringIO()
        sys.stdout = redirected_output

        try:
            logger.info("Executing dashboard logic...")

            # 1. 执行代码定义
            # 约定：AI 应该在代码中定义一个 func: def get_dashboard_data(data_context):
            # 并且返回一个 Dict[component_id, result_object]
            exec(clean_code, self.global_context, local_scope)

            if "get_dashboard_data" not in local_scope:
                raise ValueError("Generated code must contain 'get_dashboard_data(data_context)' function.")

            # 2. 调用逻辑函数
            # 此时的 data_context 已经包含了所有加载的 DataFrame
            all_results = local_scope["get_dashboard_data"](data_context)

            # 3. 结果解析与特征提取 (为智能洞察做准备)
            final_results = {}
            insight_payload = {}

            for cid in component_ids:
                if cid in all_results:
                    res_obj = all_results[cid]

                    # 自动提取该组件对应数据的特征 (如果是 DataFrame/GeoDataFrame)
                    # 这里的逻辑是为了满足你提出的“自动提取核心特征并提供深度解释”
                    summary = None
                    if hasattr(res_obj, 'df') or isinstance(res_obj, (pd.DataFrame, gpd.GeoDataFrame)):
                        target_df = res_obj if isinstance(res_obj, pd.DataFrame) else res_obj.data
                        summary = target_df.describe(include='all').to_dict()
                        insight_payload[cid] = summary

                    final_results[cid] = ComponentResult(
                        component_id=cid,
                        data=res_obj,  # 暂时保留对象，后续由 API 层转为 JSON
                        summary_stats=summary
                    )

            sys.stdout = old_stdout
            return DashboardExecutionResult(
                success=True,
                results=final_results,
                global_insight_data=insight_payload,
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