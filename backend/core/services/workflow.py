import logging
import traceback
import json
from typing import List, Dict, Any, Optional

# --- 核心模块导入 ---
from core.llm.AI_client import AIClient
from core.profiler.semantic_analyzer import SemanticAnalyzer
from core.profiler.relation_mapper import RelationMapper
from core.profiler.interaction_mapper import InteractionMapper  # [新增]
from core.generation.dashboard_planner import DashboardPlanner
from core.generation.viz_generator import CodeGenerator
from core.generation.viz_editor import VizEditor
from core.execution.executor import CodeExecutor
from core.execution.insight_extractor import InsightExtractor

# --- 协议与 Schema 导入 ---
from core.schemas.dashboard import DashboardSchema, ComponentType
from core.schemas.interaction import InteractionPayload, InteractionTriggerType
from core.schemas.state import SessionStateSnapshot

import numpy as np

logger = logging.getLogger(__name__)


class AnalysisWorkflow:
    """
    全链路指挥官 (V2 高交互版)：
    负责协调从“用户动作”到“状态快照”的完整生命周期。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client
        self.analyzer = SemanticAnalyzer(llm_client)
        self.relation_mapper = RelationMapper(llm_client)
        self.interaction_mapper = InteractionMapper(llm_client)  # [新增]
        self.planner = DashboardPlanner(llm_client)
        self.generator = CodeGenerator(llm_client)
        self.editor = VizEditor(llm_client)
        self.executor = CodeExecutor()
        self.insight_extractor = InsightExtractor(llm_client)

    async def execute_step(
            self,
            payload: InteractionPayload,
            data_summaries: List[Dict[str, Any]],
            data_context: Dict[str, Any],
            session_service: Any  # 传入 session_service 以便存取快照
    ) -> DashboardSchema:

        # === 0. 逻辑分流：历史回溯 (Backtracking) ===
        # 如果是点击左侧历史记录，直接返回存档，不走 AI 逻辑
        if payload.trigger_type == InteractionTriggerType.BACKTRACK and payload.target_snapshot_id:
            logger.info(f">>> [Backtrack] 正在还原历史快照: {payload.target_snapshot_id}")
            snapshot = session_service.get_snapshot(payload.session_id, payload.target_snapshot_id)
            if snapshot:
                return snapshot.layout_data
            else:
                logger.error("快照不存在，降级为普通分析")

        # === 1. 数据增强与交互映射 (Profiling) ===
        # [关键修改]：检查语义画像是否已存在，避免每轮对话重复分析
        for summary in data_summaries:
            sem_analysis = summary.get("semantic_analysis", {})
            # 如果没有 column_metadata (V3版核心字段)，且有文件路径，则执行分析
            if not sem_analysis.get("column_metadata") and "file_info" in summary:
                logger.info(f">>> [Analysis] 正在执行初次语义画像: {summary['variable_name']}")
                analysis = self.analyzer.analyze(summary["file_info"].get("path"))
                summary["semantic_analysis"] = analysis.get("semantic_analysis", {})
            else:
                logger.info(f">>> [Skip] 变量 {summary['variable_name']} 已有画像，跳过 AI 分析")

        # 预识别交互锚点 (为联动提供依据)
        interaction_anchors = self.interaction_mapper.identify_interaction_anchors(data_summaries)
        interaction_hint = self.interaction_mapper.get_planner_hints(interaction_anchors)

        try:
            # === 2. 逻辑决策：编辑模式 vs 生成模式 ===
            session_state = session_service.get_session(payload.session_id)
            last_state = session_state.get("last_workflow_state") if session_state else None

            # 判断是否为增量修改 (点地图、拖动时间轴或基于已有看板对话)
            is_edit_mode = (
                    payload.trigger_type == InteractionTriggerType.UI_ACTION or
                    (last_state and last_state.get("last_code") and not payload.force_new)
            )

            current_code = ""
            dashboard_plan: DashboardSchema = None

            if is_edit_mode:
                # === 模式 A: 语义钻取/联动修改 (VizEditor) ===
                logger.info(f">>> [Edit Mode] 响应组件 {payload.active_component_id} 的交互")
                # 1. 还原上次的布局结构
                dashboard_plan = DashboardSchema(**last_state["last_layout"])

                # 2. 提取当前组件的联动规则 (从 Schema 中获取)
                active_comp = next((c for c in dashboard_plan.components if c.id == payload.active_component_id), None)
                links = active_comp.links if active_comp else []

                # 3. 编辑代码
                current_code = self.editor.edit_dashboard_code(
                    original_code=last_state["last_code"],
                    payload=payload,
                    summaries=data_summaries,
                    links=links  # 注入联动上下文
                )
            else:
                # === 模式 B: 全量构建新看板 (Planner + Generator) ===
                logger.info(">>> [Generate Mode] 规划新看板布局")
                # 1. 规划看板 (携带交互锚点提示)
                dashboard_plan = self.planner.plan_dashboard(
                    query=f"{payload.query}\n{interaction_hint}",
                    summaries=data_summaries
                )
                # 2. 生成初始执行代码
                current_code = self.generator.generate_dashboard_code(
                    query=payload.query,
                    summaries=data_summaries,
                    component_plans=dashboard_plan.components
                )

            # 同步交互产生的时间范围到看板协议中，确保 UI 状态一致
            if payload.time_range:
                dashboard_plan.global_time_range = payload.time_range

            # === 3. 代码执行与自愈 (Executor) ===
            # [关键修改]：只有在真正运行代码前，才确保加载全量数据，极大提升分析阶段响应速度
            logger.info(">>> [Full Load] 正在按需准备全量数据上下文...")
            session_service.ensure_full_data_context(payload.session_id)
            # 获取最新的上下文（因为 ensure_full_data_context 之后 data_context 会变更为全量）
            full_session = session_service.get_session(payload.session_id)
            actual_data_context = full_session["data_context"]

            logger.info(">>> 执行看板代码逻辑...")
            comp_ids = [c.id for c in dashboard_plan.components]

            exec_result = self.executor.execute_dashboard_logic(
                code_str=current_code,
                data_context=actual_data_context, # 使用全量数据
                component_ids=comp_ids
            )

            if not exec_result.success:
                # 自动修复
                logger.warning("执行失败，尝试自动修复...")
                current_code = self.generator.fix_code(current_code, exec_result.error, data_summaries)
                exec_result = self.executor.execute_dashboard_logic(
                    current_code, actual_data_context, comp_ids
                )
                if not exec_result.success: raise Exception(f"代码引擎崩溃: {exec_result.error}")

            # === 4. 结果装配与洞察 (Extractor) ===
            # 生成业务洞察
            insight_card = self.insight_extractor.generate_insights(
                query=payload.query or "交互更新分析",
                execution_stats=exec_result.global_insight_data,
                summaries=data_summaries
            )

            # 填充数据负载
            for component in dashboard_plan.components:
                if component.id in exec_result.results:
                    res = exec_result.results[component.id]
                    component.data_payload = self._sanitize_data(res.data)

                if component.type == ComponentType.INSIGHT:
                    component.insight_config = self._sanitize_data(insight_card)

            # === 5. 状态固化与回溯存档 (Snapshot) ===
            # 将本次结果存入 Session 以便左侧列表回溯
            snapshot_id = session_service.save_snapshot(
                session_id=payload.session_id,
                query=payload.query or f"交互: {payload.active_component_id or '时间筛选'}",
                code=current_code,
                layout_data=dashboard_plan,
                summary=insight_card.summary
            )

            # 更新当前会话状态，供下一轮交互参考
            dashboard_plan.metadata = {
                "last_code": current_code,
                "last_layout": dashboard_plan.model_dump(),
                "snapshot_id": snapshot_id
            }
            session_service.update_session_metadata(payload.session_id, dashboard_plan.metadata)

            return dashboard_plan

        except Exception as e:
            logger.error(f"Workflow 致命错误: {traceback.format_exc()}")
            raise e

    def _sanitize_data(self, obj: Any) -> Any:
        """深度数据清洗，确保 NumPy/Pandas 对象可 JSON 序列化"""
        if hasattr(obj, "to_dict"):
            try:
                return self._sanitize_data(obj.to_dict(orient='records'))
            except:
                return self._sanitize_data(obj.to_dict())
        if isinstance(obj, (np.ndarray, np.generic)):
            return obj.tolist() if isinstance(obj, np.ndarray) else obj.item()
        elif hasattr(obj, "to_plotly_json"):
            return self._sanitize_data(obj.to_plotly_json())
        elif isinstance(obj, dict):
            return {k: self._sanitize_data(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize_data(i) for i in obj]
        return obj