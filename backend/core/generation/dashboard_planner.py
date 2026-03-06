import logging
import uuid
import json
import re
from typing import Dict, Any, List
from datetime import datetime

from core.llm.AI_client import AIClient
from core.schemas.dashboard import (
    DashboardSchema, DashboardComponent, ComponentType,
    LayoutZone, LayoutConfig, ChartType, InsightCard
)
from core.generation.templates import LayoutTemplates

logger = logging.getLogger(__name__)


class DashboardPlanner:
    """
    看板编排器 (V6.8 意图驱动时间轴版)：
    1. [Logic] 贪婪寻找所有数据源中的最佳时间轴。
    2. [Intent] AI 深度提取用户提到的特定日期/时段约束。
    3. [Alignment] 自动计算“用户意图时间”与“数据物理时间”的交集，精准缩放进度条跨度。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    def _unwrap_llm_json(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """提取 AI 返回的有效载荷"""
        if not isinstance(data, dict): return {}
        for key in ['planned_charts', 'analysis', 'config']:
            if key in data:
                return data
        return data

    async def plan_dashboard(self, query: str, summaries: List[Dict[str, Any]]) -> DashboardSchema:
        logger.info(f">>> [Planner] 启动 AI 深度意图解析模式...")

        # 1. 确定主数据变量 (用于地图几何)
        main_summary = next((s for s in summaries if s.get('is_geospatial')), summaries[0])
        main_var = main_summary['variable_name']

        # 2. 构建数据上下文并寻找时间源
        context_str = ""
        found_time_col = None
        time_source_summary = None

        for s in summaries:
            var_name = s['variable_name']
            cols = list(s.get('column_stats', {}).keys())
            time_ctx = s.get('semantic_analysis', {}).get('temporal_context', {})
            p_time = time_ctx.get('primary_time_col')

            time_hint = f"(主时间列: {p_time}, 建议粒度: {time_ctx.get('suggested_resampling')})" if p_time else "无时间维度"
            context_str += f"- 数据集 `{var_name}`: {time_hint}, 可用列 {cols[:20]}\n"

            if p_time and not found_time_col:
                found_time_col = p_time
                time_source_summary = s

        # 3. 构建深度规划提示词
        system_prompt = f"""
        你是一位资深时空数据分析专家。请根据用户的【分析意图】和【数据特征】，规划一套仪表板方案。

        === 数据上下文 ===
        {context_str}

        === 任务 1：识别时空动态意图 ===
        - 判断用户是否想要观察数据随时间的“演变”、“变化”、“播放”或“流转”。如果是，设置 `is_animated` 为 true。
        - 决定聚合步长 `time_granularity`（可选值：'1S', '1T', '1H', '1D', '1W'）。

        === 任务 2：提取时间约束 (CRITICAL) ===
        - 仔细分析用户是否提到了特定的日期、时间点或时段（如“1月1日”、“2025年第一周”）。
        - 如果提到了，请在 `requested_time_range` 中输出 ISO 格式的 `start` 和 `end`。
        - 如果用户只提到了某一天，`start` 应为该日的 00:00:00，`end` 为该日的 23:59:59。
        - 如果用户没提，设置 `requested_time_range` 为 null。

        === 任务 3：规划统计图表 ===
        - 在右侧边栏规划 1-2 个统计图表（bar, line, pie, scatter）。
        - 切勿包含地图组件。

        === 输出格式 (JSON) ===
        {{
            "is_animated": true,
            "time_granularity": "1H",
            "requested_time_range": {{
                "start": "2025-01-01T00:00:00",
                "end": "2025-01-01T23:59:59"
            }},
            "planned_charts": [
                {{ "title": "标题", "chart_type": "bar", "analysis_intent": "原因" }}
            ]
        }}
        """

        user_prompt = f"用户原始指令: \"{query}\"\n请分析意图并给出规划方案。"

        ai_plan = {}
        try:
            ai_plan = await self.llm.query_json_async(prompt=user_prompt, system_prompt=system_prompt)
        except Exception as e:
            logger.error(f"AI 意图解析失败: {e}")
            ai_plan = {"is_animated": False, "planned_charts": []}

        # 4. 提取 AI 决策
        is_anim_requested = ai_plan.get("is_animated", False)

        default_resample = '1H'
        if time_source_summary:
            default_resample = time_source_summary.get('semantic_analysis', {}).get('temporal_context', {}).get(
                'suggested_resampling', '1H')

        final_step = ai_plan.get("time_granularity", default_resample).upper()
        chart_list = ai_plan.get("planned_charts", [])

        # 5. 动态组装组件与时间范围对齐
        components = []
        start_t, end_t = None, None

        if is_anim_requested and found_time_col and time_source_summary:
            # 5.1 获取物理边界
            time_stats = time_source_summary.get('column_stats', {}).get(found_time_col, {})
            physical_min = time_stats.get('min', "2025-01-01T00:00:00")
            physical_max = time_stats.get('max', "2025-01-01T23:59:59")

            # 5.2 获取 AI 提取的用户意图跨度
            req_range = ai_plan.get("requested_time_range")
            if req_range and req_range.get("start") and req_range.get("end"):
                # 执行“交集”逻辑：取 (用户需求 vs 物理存在) 的重叠部分
                # 这里简单处理：如果用户有需求，优先尊重用户，但做一层物理保护
                start_t = max(req_range["start"], physical_min)
                end_t = min(req_range["end"], physical_max)

                # 防护：如果交集导致逻辑错误，回退到物理跨度
                if start_t >= end_t:
                    start_t, end_t = physical_min, physical_max
            else:
                start_t, end_t = physical_min, physical_max

            # 5.3 确定格式契约
            if 'D' in final_step:
                f_format = "%Y-%m-%d"
            elif 'H' in final_step:
                f_format = "%H:00"
            elif 'T' in final_step or 'M' in final_step:
                f_format = "%H:%M"
            else:
                f_format = "%Y-%m-%d %H:%M"

            components.append(DashboardComponent(
                id="global_timeline",
                title=f"时间轴：{found_time_col}",
                type=ComponentType.TIMELINE_CONTROLLER,
                layout=LayoutConfig(zone=LayoutZone.TOP_NAV),
                timeline_config={
                    "start_time": start_t,
                    "end_time": end_t,
                    "step": final_step,
                    "frame_format": f_format,
                    "column": found_time_col
                }
            ))

        # B. 地图组件
        components.append(DashboardComponent(
            id="main_map",
            title="时空演变视图" if is_anim_requested else "时空分布视图",
            type=ComponentType.MAP,
            layout=LayoutConfig(zone=LayoutZone.CENTER_MAIN),
            map_config=[{
                "layer_id": "L1",
                "layer_type": "ScatterplotLayer",
                "data_var": main_var,
                "is_animated": is_anim_requested,
                "animation_column": found_time_col
            }]
        ))

        # C. 统计图表
        if not chart_list:
            chart_list = [{"title": "指标分析", "chart_type": "bar"}]

        for i, chart_plan in enumerate(chart_list[:2]):
            components.append(DashboardComponent(
                id=f"chart_dynamic_{i + 1}",
                title=chart_plan.get("title", f"分析图表 {i + 1}"),
                type=ComponentType.CHART,
                layout=LayoutConfig(zone=LayoutZone.RIGHT_SIDEBAR, index=i),
                chart_config={
                    "chart_type": chart_plan.get("chart_type", "bar"),
                    "theme": "plotly_dark"
                }
            ))

        # D. 底部洞察
        components.append(DashboardComponent(
            id="ai_insight",
            title="智能分析结论",
            type=ComponentType.INSIGHT,
            layout=LayoutConfig(zone=LayoutZone.BOTTOM_INSIGHT),
            insight_config={
                "summary": "正在执行深度时空推理...",
                "detail": "系统正在分析数据特征并为您提取业务价值。",
                "tags": ["AI Reasoning"]
            }
        ))

        # 6. 生成对象
        dashboard = DashboardSchema(
            dashboard_id=f"dash_{uuid.uuid4().hex[:6]}",
            title="时空智能看板",
            global_time_range=[start_t, end_t] if (is_anim_requested and start_t) else None,
            components=components
        )

        LayoutTemplates.apply_layout(dashboard.components)

        # === 探针 1：Planner 输出检查 ===
        logger.info("=== [探针 1: Planner 输出] ===")
        timeline_comp = next((c for c in dashboard.components if c.type == ComponentType.TIMELINE_CONTROLLER), None)
        if timeline_comp:
            logger.info(f"✅ 成功生成时间轴组件: ID={timeline_comp.id}")
            logger.info(f"   起始: {start_t}, 结束: {end_t}, 步长: {final_step}")
        else:
            logger.error(f"❌ 依然没有时间轴！ is_anim={is_anim_requested}, found_time_col={found_time_col}")

        return dashboard