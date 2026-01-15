import logging
from typing import List, Dict, Any, Optional

# 核心模块导入 - 严格匹配你的树状图路径
from core.llm.AI_client import AIClient
from core.profiler.semantic_analyzer import SemanticAnalyzer
from core.generation.dashboard_planner import DashboardPlanner
from core.generation.code_generator import CodeGenerator
from core.generation.viz_editor import VizEditor
from core.execution.executor import CodeExecutor
from core.execution.insight_extractor import InsightExtractor

# 协议与 Schema 导入
from core.schemas.dashboard import DashboardSchema, ComponentType
from core.schemas.interaction import InteractionPayload

logger = logging.getLogger(__name__)


class AnalysisWorkflow:
    """
    分析工作流（V2.1 编排器）：
    串联语义分析、看板规划、多模态代码生成、代码执行、特征提取及智能洞察。
    实现“自然语言 + 地图交互”的闭环。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

        # 实例化所有原子模块
        self.analyzer = SemanticAnalyzer(llm_client)
        self.planner = DashboardPlanner(llm_client)
        self.generator = CodeGenerator(llm_client)
        self.editor = VizEditor(llm_client)  # 处理增量修改
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
        根据用户载荷执行一次完整的分析循环
        """

        # --- 1. 逻辑分流：生成新看板 vs 语义钻取/修改 ---
        # 如果存在旧代码且用户没有强制新建，则进入“编辑模式”
        is_edit_mode = last_session_state and last_session_state.get("last_code") and not payload.force_new

        current_code = ""
        dashboard_plan: DashboardSchema = None

        if is_edit_mode:
            # === 情况 A: 语义钻取 (Requirement 2) ===
            logger.info(">>> 模式：语义钻取/增量修改")
            # 复用上次的看板布局方案
            dashboard_plan = DashboardSchema(**last_session_state["last_layout"])
            # 调用 VizEditor 修改代码逻辑（如植入 BBox 过滤）
            current_code = self.editor.edit_dashboard_code(
                original_code=last_session_state["last_code"],
                payload=payload,
                summaries=data_summaries
            )
        else:
            # === 情况 B: 自动构建新看板 (Requirement 1) ===
            logger.info(">>> 模式：自动构建新看板")
            # 1. 规划布局
            dashboard_plan = self.planner.plan_dashboard(payload.query, data_summaries)
            # 2. 生成初始执行代码
            current_code = self.generator.generate_dashboard_code(
                query=payload.query,
                summaries=data_summaries,
                component_plans=dashboard_plan.components,
                interaction_hint=f"BBox: {payload.bbox}" if payload.bbox else ""
            )

        # --- 2. 代码执行与数据捕获 ---
        logger.info(">>> 正在执行时空分析逻辑...")
        comp_ids = [c.id for c in dashboard_plan.components]
        exec_result = self.executor.execute_dashboard_logic(
            code_str=current_code,
            data_context=data_context,
            component_ids=comp_ids
        )

        if not exec_result.success:
            logger.error(f"代码执行失败: {exec_result.error}")
            # 这里可以调用 Generator.fix_code 进行一次自愈，篇幅关系此处略
            raise Exception(f"分析引擎报错: {exec_result.error}")

        # --- 3. 智能特征提取与分析解释 (Requirement 1) ---
        logger.info(">>> 正在生成智能分析解释...")
        # 将执行后的统计摘要发送给 InsightExtractor
        insight_card = self.insight_extractor.generate_insights(
            query=payload.query or "交互式下钻分析",
            execution_stats=exec_result.global_insight_data,
            summaries=data_summaries
        )

        # --- 4. 装配最终看板 JSON (DashboardSchema) ---
        # 填充每个组件的真实数据载荷
        for component in dashboard_plan.components:
            if component.id in exec_result.results:
                comp_data = exec_result.results[component.id]
                # 这一步将 Python 对象（Plotly/DF）转化为前端可渲染的格式
                # 实际开发中需实现 _serialize_component_data 方法
                # component.data_payload = self._serialize_component_data(comp_data.data)

            # 将生成的文字结论挂载到 INSIGHT 组件上
            if component.type == ComponentType.INSIGHT:
                component.insight_config = insight_card

        # --- 5. 状态持久化准备 ---
        # 将当前的代码和布局存入元数据，供下一轮交互使用
        dashboard_plan.metadata = {
            "last_code": current_code,
            "last_layout": dashboard_plan.dict(),
            "execution_summary": exec_result.global_insight_data
        }

        return dashboard_plan

    def _serialize_component_data(self, data: Any) -> Any:
        """将 Python 数据对象转化为前端序列化 JSON"""
        # 如果是 Plotly Figure，调用 .to_json()
        # 如果是 GeoDataFrame，调用 .to_json() 转 GeoJSON
        pass