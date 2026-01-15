import logging
import traceback
from typing import List, Dict, Any, Optional

# --- 核心模块导入 ---
from core.llm.AI_client import AIClient
from core.profiler.semantic_analyzer import SemanticAnalyzer
from core.profiler.relation_mapper import RelationMapper  # [新增]
from core.generation.dashboard_planner import DashboardPlanner
from core.generation.code_generator import CodeGenerator
from core.generation.viz_editor import VizEditor
from core.execution.executor import CodeExecutor
from core.execution.insight_extractor import InsightExtractor

# --- 协议与 Schema 导入 ---
from core.schemas.dashboard import DashboardSchema, ComponentType
from core.schemas.interaction import InteractionPayload

logger = logging.getLogger(__name__)


class AnalysisWorkflow:
    """
    分析工作流（Final Version）：
    全链路编排：语义理解 -> 关系发现 -> 看板规划 -> 代码生成 -> 自动修复 -> 智能洞察。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

        # 1. 实例化所有原子能力模块
        self.analyzer = SemanticAnalyzer(llm_client)
        self.relation_mapper = RelationMapper(llm_client)  # [新增] 关系映射器
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
            last_session_state: Optional[Dict[str, Any]] = None
    ) -> DashboardSchema:
        """
        执行一次完整的分析循环。
        注意：Ingestion (数据加载) 和 Profiling (基础统计) 假定在 SessionService 中已完成，
        并通过 data_context 和 data_summaries 传入。
        """

        for summary in data_summaries:
            semantic_data = summary.get("semantic_analysis", {})
            tags = semantic_data.get("semantic_tags", {})

            # 如果没有标签，且有文件路径，则调用 Analyzer
            if not tags and "file_info" in summary:
                logger.info(f">>> [Auto-Enrich] 正在补充语义分析: {summary['variable_name']}")
                file_path = summary["file_info"].get("path")
                if file_path:
                    # 调用语义分析器
                    analysis_result = self.analyzer.analyze(file_path)

                    # 回填结果到 summary 中 (引用传递，会直接更新 Session 中的对象)
                    if "semantic_analysis" in analysis_result:
                        summary["semantic_analysis"] = analysis_result["semantic_analysis"]

        try:
            # --- 0. 预计算：关系发现 (New) ---
            # 分析多表之间是否存在关联（如外键、空间包含），辅助代码生成
            # 仅在非编辑模式下计算，节省 Token
            relation_hint = ""
            if not last_session_state and len(data_summaries) > 1:
                logger.info(">>> 正在分析数据集关联关系...")
                relations = self.relation_mapper.map_relations(data_summaries)
                # 针对当前 Query 涉及的变量提取 Hint
                # 这里简单处理：将所有关系都作为背景知识
                for r in relations:
                    relation_hint += f"- 检测到关联: {r['source']} 和 {r['target']} 可通过 {r['type']} 连接 (Key: {r['join_on']})\n"

            # --- 1. 逻辑分流 ---
            is_edit_mode = last_session_state and last_session_state.get("last_code") and not payload.force_new

            current_code = ""
            dashboard_plan: DashboardSchema = None

            if is_edit_mode:
                # === A: 编辑模式 (VizEditor) ===
                logger.info(">>> 模式：语义钻取/增量修改")
                dashboard_plan = DashboardSchema(**last_session_state["last_layout"])

                current_code = self.editor.edit_dashboard_code(
                    original_code=last_session_state["last_code"],
                    payload=payload,
                    summaries=data_summaries
                )
            else:
                # === B: 生成模式 (Planner + Generator) ===
                logger.info(">>> 模式：自动构建新看板")

                # Step 1: 规划
                dashboard_plan = self.planner.plan_dashboard(payload.query, data_summaries)

                # Step 2: 构造综合 Hint (交互 + 关系)
                combined_hint = ""
                if payload.bbox:
                    combined_hint += f"交互过滤: 用户框选了范围 {payload.bbox}，请先进行空间过滤。\n"
                if relation_hint:
                    combined_hint += f"数据关联提示:\n{relation_hint}"

                # Step 3: 生成代码
                current_code = self.generator.generate_dashboard_code(
                    query=payload.query,
                    summaries=data_summaries,
                    component_plans=dashboard_plan.components,
                    interaction_hint=combined_hint  # 注入关系提示
                )

            # --- 2. 代码执行 ---
            logger.info(">>> 正在执行分析逻辑...")
            comp_ids = [c.id for c in dashboard_plan.components]

            exec_result = self.executor.execute_dashboard_logic(
                code_str=current_code,
                data_context=data_context,
                component_ids=comp_ids
            )

            # --- 3. 错误熔断与自愈 (简版) ---
            if not exec_result.success:
                logger.error(f"Execution Failed: {exec_result.error}")

                # [自愈逻辑] 尝试修复一次
                logger.info(">>> 触发自动修复机制...")
                fixed_code = self.generator.fix_code(
                    original_code=current_code,
                    error_trace=exec_result.error,
                    summaries=data_summaries
                )

                # 重试执行
                exec_result = self.executor.execute_dashboard_logic(
                    code_str=fixed_code,
                    data_context=data_context,
                    component_ids=comp_ids
                )

                if exec_result.success:
                    current_code = fixed_code  # 更新为修复后的代码
                    logger.info(">>> 自动修复成功！")
                else:
                    # 依然失败，抛出异常
                    raise Exception(f"分析引擎无法生成有效代码。错误信息: {exec_result.error}")

            # --- 4. 智能洞察 ---
            logger.info(">>> 生成洞察结论...")
            insight_card = self.insight_extractor.generate_insights(
                query=payload.query or "数据概览",
                execution_stats=exec_result.global_insight_data,
                summaries=data_summaries
            )

            # --- 5. 结果装配 ---
            # 填充 Insight 组件
            for component in dashboard_plan.components:
                if component.type == ComponentType.INSIGHT:
                    component.insight_config = insight_card
                # 注意：实际的图表数据 (exec_result.results) 通常由 API 层单独返回或在此处挂载
                # 这里为了 schema 简洁，假设数据通过另外的接口获取，或者前端直接根据 ID 渲染

            # --- 6. 状态保存 ---
            dashboard_plan.metadata = {
                "last_code": current_code,
                "last_layout": dashboard_plan.model_dump(),  # Pydantic V2 推荐用法
                "execution_summary": exec_result.global_insight_data
            }

            return dashboard_plan

        except Exception as e:
            logger.error(f"Workflow Critical Error: {traceback.format_exc()}")
            raise e