import logging
import traceback
import json
import asyncio
import orjson
from typing import List, Dict, Any, Optional
from datetime import date, datetime

# --- 核心模块导入 ---
from core.llm.AI_client import AIClient
from core.profiler.semantic_analyzer import SemanticAnalyzer
from core.profiler.relation_mapper import RelationMapper
from core.profiler.interaction_mapper import InteractionMapper
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
import pandas as pd

logger = logging.getLogger(__name__)


class AnalysisWorkflow:
    """
    全链路指挥官 (V2.5 时空组件保护版)：
    1. [Performance] 优化 orjson 序列化管道，支持地理几何对象转换。
    2. [Stability] 强化异步画像分析，注入物理统计量指纹。
    3. [State] 优化 UI 交互模式下的视角（ViewState）保持。
    4. [Fix] 增加了系统级组件 (Timeline) 在合并过程中的强保护，防止丢失。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client
        self.analyzer = SemanticAnalyzer(llm_client)
        self.relation_mapper = RelationMapper(llm_client)
        self.interaction_mapper = InteractionMapper(llm_client)
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
            session_service: Any
    ) -> DashboardSchema:

        # === 0. 逻辑分流：历史回溯 ===
        if payload.trigger_type == InteractionTriggerType.BACKTRACK and payload.target_snapshot_id:
            logger.info(f">>> [Backtrack] 正在还原历史快照: {payload.target_snapshot_id}")
            snapshot = session_service.get_snapshot(payload.session_id, payload.target_snapshot_id)
            if snapshot:
                return snapshot.layout_data
            else:
                logger.error("快照不存在，降级为普通分析")

        # === 1. 数据增强与交互映射 (Profiling) ===

        # 1.1 并行执行语义分析 (注入基础指纹以提高准确率)
        analysis_tasks = []
        task_indices = []

        for i, summary in enumerate(data_summaries):
            sem_analysis = summary.get("semantic_analysis", {})
            # 只有当缺少核心列元数据时才触发分析
            if not sem_analysis.get("column_metadata") and "file_info" in summary:
                logger.info(f">>>[Analysis] 调度异步语义画像: {summary['variable_name']}")
                # 注入 basic_stats 提供的物理指纹，避免重复计算
                fingerprint = summary.get("basic_stats", {})
                task = self.analyzer.analyze(summary["file_info"].get("path"), fingerprint)
                analysis_tasks.append(task)
                task_indices.append(i)
            else:
                logger.info(f">>> [Skip] 变量 {summary['variable_name']} 已有完整画像")

        if analysis_tasks:
            results = await asyncio.gather(*analysis_tasks)
            for idx, res in zip(task_indices, results):
                # 合并语义分析结果，保留原有的物理统计信息
                data_summaries[idx]["semantic_analysis"] = res.get("semantic_analysis", {})
                data_summaries[idx]["variable_name"] = res.get("variable_name", data_summaries[idx]["variable_name"])

        # ---[Eager Loading] 后台全量预加载 ---
        session_info = session_service.get_session(payload.session_id)
        if session_info and not session_info.get("is_full_data"):
            logger.info(">>> [Eager Load] 触发后台全量数据预加载 (Non-Blocking)...")
            # asyncio.create_task(asyncio.to_thread(session_service.ensure_full_data_context, payload.session_id))

        # 1.2 交互锚点识别 (带缓存机制)
        session_state = session_service.get_session(payload.session_id)
        cached_anchors = session_state.get("cached_interaction_anchors")

        if not cached_anchors:
            logger.info(">>> [Interaction] 计算并缓存多数据集交互锚点...")
            interaction_anchors = await self.interaction_mapper.identify_interaction_anchors(data_summaries)
            session_state["cached_interaction_anchors"] = interaction_anchors
        else:
            logger.info(">>> [Cache] 命中交互锚点缓存")
            interaction_anchors = cached_anchors

        interaction_hint = self.interaction_mapper.get_planner_hints(interaction_anchors)

        try:
            # === 2. 逻辑决策：编辑模式 vs 生成模式 ===
            last_state = session_state.get("last_workflow_state") if session_state else None

            is_edit_mode = (
                    payload.trigger_type == InteractionTriggerType.UI_ACTION or
                    (last_state and last_state.get("last_code") and not payload.force_new)
            )

            current_code = ""
            dashboard_plan: DashboardSchema = None

            if is_edit_mode:
                # === 模式 A: 基于现有代码的增量编辑 (VizEditor) ===
                logger.info(f">>> [Edit Mode] 响应交互动作，正在修改代码逻辑...")
                dashboard_plan = DashboardSchema(**last_state["last_layout"])

                active_comp = next((c for c in dashboard_plan.components if c.id == payload.active_component_id), None)
                links = active_comp.links if active_comp else []

                current_code = await self.editor.edit_dashboard_code(
                    original_code=last_state["last_code"],
                    payload=payload,
                    summaries=data_summaries,
                    links=links
                )
            else:
                # === 模式 B: 从零规划并生成看板 (Planner + Generator) ===
                logger.info(">>>[Generate Mode] 正在规划全新时空看板...")
                dashboard_plan = await self.planner.plan_dashboard(
                    query=f"{payload.query}\n{interaction_hint}",
                    summaries=data_summaries
                )
                current_code = await self.generator.generate_dashboard_code(
                    query=payload.query,
                    summaries=data_summaries,
                    component_plans=dashboard_plan.components,
                    interaction_hint=interaction_hint
                )

            # 同步全局时间范围与视图状态
            if payload.time_range:
                dashboard_plan.global_time_range = payload.time_range
            if payload.view_state:
                dashboard_plan.initial_view_state.update(payload.view_state)

            # === 3. 代码执行 ===
            # 确保在正式绘图执行前，全量数据已加载完毕
            session_service.ensure_full_data_context(payload.session_id)

            full_session = session_service.get_session(payload.session_id)
            actual_data_context = full_session["data_context"]

            comp_ids = [c.id for c in dashboard_plan.components]

            exec_result = self.executor.execute_dashboard_logic(
                code_str=current_code,
                data_context=actual_data_context,
                component_ids=comp_ids
            )

            # 自愈机制
            if not exec_result.success:
                logger.warning(f"代码执行失败，启动 AI 自动纠错: {exec_result.error[:100]}...")
                current_code = await self.generator.fix_code(current_code, exec_result.error, data_summaries)
                exec_result = self.executor.execute_dashboard_logic(
                    current_code, actual_data_context, comp_ids
                )
                if not exec_result.success: raise Exception(f"代码修复失败: {exec_result.error}")

            # === 4. 结果装配与洞察提取 ===
            insight_card = await self.insight_extractor.generate_insights(
                query=payload.query or "交互更新分析",
                execution_stats=exec_result.global_insight_data,
                summaries=data_summaries
            )

            # logger.info(">>> [Serialization] 正在进行时空数据极速脱敏与序列化...")
            #
            # for component in dashboard_plan.components:
            #     # [核心修复] 系统级组件保护：为时间轴强制注入存活标记
            #     if component.type == ComponentType.TIMELINE_CONTROLLER:
            #         # 强行赋予 data_payload 避免被 Pydantic 或前端意外剥离
            #         component.data_payload = {"status": "active", "type": "system_controller"}
            #         continue
            #
            #     # 常规数据驱动组件装配
            #     if component.id in exec_result.results:
            #         res = exec_result.results[component.id]
            #         component.data_payload = self._sanitize_data_fast(res.data)
            #
            #     # 显式处理洞察组件
            #     if component.type == ComponentType.INSIGHT:
            #         component.insight_config = self._sanitize_data_fast(insight_card)
            #         component.data_payload = component.insight_config

            logger.info(">>> [Serialization] 正在进行时空数据极速脱敏与序列化...")

            for component in dashboard_plan.components:
                if component.id in exec_result.results:
                    res = exec_result.results[component.id]

                    # [诊断探针] 检查 Python 运行出来的对象里到底有没有帧
                    if hasattr(res.data, 'frames') and res.data.frames:
                        logger.info(f"📊 [Workflow Probe] 组件 {component.id} 包含 {len(res.data.frames)} 个动画帧")

                    # 执行脱敏
                    component.data_payload = self._sanitize_data_fast(res.data)

                    # [诊断探针] 检查脱敏之后，字典里还有没有 frames 键
                    if isinstance(component.data_payload, dict) and 'frames' in component.data_payload:
                        logger.info(f"✅ [Workflow Probe] 组件 {component.id} 序列化后 frames 依然存在")
                    else:
                        if hasattr(res.data, 'frames') and res.data.frames:
                            logger.error(f"❌ [Workflow Probe] 警告！组件 {component.id} 的 frames 在序列化过程中丢失了！")

                    # 显式处理洞察组件
                    if component.type == ComponentType.INSIGHT:
                        # component.insight_config = self._sanitize_data_fast(insight_card)
                        # component.data_payload = component.insight_config
                        # 检查 data 是否是字典（代表 AI 生成的结果）
                        raw_insight = exec_result.results[
                            component.id].data if component.id in exec_result.results else insight_card

                        # [修复警告] 确保传给 insight_config 的字典键名是 Pydantic 期望的
                        clean_insight = self._sanitize_data_fast(raw_insight)
                        if isinstance(clean_insight, dict):
                            # 对齐 detail 字段，消除 Pydantic 验证警告
                            if 'Description' in clean_insight and 'detail' not in clean_insight:
                                clean_insight['detail'] = clean_insight.pop('Description')

                        component.insight_config = clean_insight
                        component.data_payload = clean_insight

            # === 5. 状态固化与快照存档 ===
            snapshot_id = session_service.save_snapshot(
                session_id=payload.session_id,
                query=payload.query or f"交互: {payload.active_component_id or '全局筛选'}",
                code=current_code,
                layout_data=dashboard_plan,
                summary=insight_card.summary
            )
            print("最终代码\n", current_code)

            dashboard_plan.metadata = {
                "last_code": current_code,
                # 注意：使用 model_dump 时不排除 None，确保 timeline_config 等被保留
                "last_layout": dashboard_plan.model_dump(),
                "snapshot_id": snapshot_id
            }
            session_service.update_session_metadata(payload.session_id, dashboard_plan.metadata)

            logger.info("=== [探针 2: Workflow 装配完毕] ===")
            timeline_comp = next((c for c in dashboard_plan.components if c.type == ComponentType.TIMELINE_CONTROLLER),
                                 None)
            if timeline_comp:
                logger.info(f"✅ 工作流装配后，时间轴组件仍存活！")
                logger.info(
                    f"Config 是否存在: {hasattr(timeline_comp, 'timeline_config') and timeline_comp.timeline_config is not None}")
            else:
                logger.error("❌ 时间轴组件在 workflow 合并过程中神秘消失！")

            # [极其关键] 检查 Pydantic 的 dump 结果
            dumped_data = dashboard_plan.model_dump()
            dumped_timeline = next((c for c in dumped_data['components'] if c['type'] == 'timeline_controller'), None)
            logger.info(f"Pydantic Dump 后的时间轴状态: {dumped_timeline}")

            return dashboard_plan

        except Exception as e:
            logger.error(f"Analysis Workflow Failed: {traceback.format_exc()}")
            raise e

    def _sanitize_data_fast(self, obj: Any) -> Any:
        """[极速序列化 V3.1 - 时空增强版]
        专门优化了处理大规模 NumPy 数组和 Shapely 地理几何对象的效率。
        """

        def deep_clean(o):
            if isinstance(o, (str, int, float, bool, type(None))):
                return o
            if isinstance(o, dict):
                return {str(k): deep_clean(v) for k, v in o.items()}
            if isinstance(o, (list, tuple, set)):
                return [deep_clean(i) for i in o]

            # NumPy/Pandas 处理
            if isinstance(o, np.ndarray):
                return o.tolist()
            if isinstance(o, (np.integer, np.floating)):
                return o.item()
            if isinstance(o, (pd.Series, pd.Index)):
                return o.tolist()
            if isinstance(o, pd.DataFrame):
                # 针对超大规模 DataFrame 的记录转换优化
                return o.to_dict(orient='records')

            # 时空地理对象处理 (GeoJSON 转换)
            if hasattr(o, "__geo_interface__"):
                return o.__geo_interface__

            # Plotly / Pydantic 处理
            # if hasattr(o, "to_plotly_json"):
            #     return deep_clean(o.to_plotly_json())
            # [核心修复] Plotly 对象处理
            if hasattr(o, "to_dict") and hasattr(o, "layout") and hasattr(o, "data"):
                return deep_clean(o.to_dict())
            if hasattr(o, "model_dump"):
                return deep_clean(o.model_dump())

            # 时间类型处理
            if isinstance(o, (date, datetime, pd.Timestamp)):
                return o.isoformat()

            return str(o)

        try:
            # 执行深度清洗
            clean_obj = deep_clean(obj)
            # 使用 orjson 进行二进制加速
            return orjson.loads(orjson.dumps(clean_obj, option=orjson.OPT_NON_STR_KEYS))
        except Exception as e:
            logger.error(f"Fast sanitization failed: {e}")
            return self._sanitize_data_legacy(obj)

    def _sanitize_data_legacy(self, obj: Any) -> Any:
        """兜底清洗逻辑"""
        if hasattr(obj, "to_dict"):
            try:
                return self._sanitize_data_legacy(obj.to_dict(orient='records'))
            except:
                return self._sanitize_data_legacy(obj.to_dict())
        if isinstance(obj, (np.ndarray, np.generic)):
            return obj.tolist() if isinstance(obj, np.ndarray) else obj.item()
        elif hasattr(obj, "to_plotly_json"):
            return self._sanitize_data_legacy(obj.to_plotly_json())
        elif isinstance(obj, dict):
            return {str(k): self._sanitize_data_legacy(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize_data_legacy(i) for i in obj]
        return str(obj)