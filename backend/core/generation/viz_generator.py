import logging
import re
import json
from typing import Dict, Any, List
from core.llm.AI_client import AIClient
# 引入 Scaffold
from core.generation.scaffold import STChartScaffold

logger = logging.getLogger(__name__)


class CodeGenerator:
    """
    代码生成器 (V3.2 路径依赖修正与静态约束版)：
    1. [Logic Integration] 深度整合 Scaffold 中的空间计算与时间聚合食谱。
    2. [Anti-Hallucination] 增加“静态图强约束”，防止非动画需求被误转为动画帧。
    3. [Safety Guard] 强化变量名、数据副本 (.copy())、列类型 (Dtype) 及大小写敏感性约束。
    4. [Protocol Sync] 动态提取 timeline_config 的 frame_format 契约下发给 LLM。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client
        self.scaffold = STChartScaffold()

    def _clean_markdown(self, text: str) -> str:
        """正则提取代码块"""
        if not text:
            return ""
        pattern = r"```(?:python)?\s*(.*?)```"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        text = text.strip()
        text = re.sub(r"^```(python)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        return text.strip()

    def _build_context_str(self, summaries: List[Dict[str, Any]]) -> str:
        """
        统一构建标准化数据上下文，供 generate 和 fix 共用。
        """
        context_str = ""
        for s in summaries:
            var_name = s.get('variable_name')

            # 1. 获取物理统计信息 (修复路径)
            col_stats = s.get('column_stats')
            if not col_stats:
                col_stats = s.get('basic_stats', {}).get('column_stats', {})

            # 2. 获取语义信息
            sem_analysis = s.get('semantic_analysis', {})
            col_meta = sem_analysis.get('column_metadata', {})

            # 3. 构建列描述列表，标注 Dtype 并强调大小写敏感
            col_desc_list = []
            if col_stats:
                for col, info in col_stats.items():
                    dtype = info.get('dtype', 'unknown')
                    col_desc_list.append(f"{col}({dtype})")
            else:
                col_desc_list = ["(无列信息)"]

            # 4. 提取关键语义标签
            semantic_hints = {}
            for col, meta in col_meta.items():
                if isinstance(meta, dict) and meta.get('semantic_tag'):
                    semantic_hints[col] = meta.get('semantic_tag')

            context_str += f"- 变量 `{var_name}`:\n"
            context_str += f"  - 原始列名(!!!区分大小写!!!): {', '.join(col_desc_list[:50])}\n"
            if semantic_hints:
                context_str += f"  - 关键语义 (Hints): {json.dumps(semantic_hints, ensure_ascii=False)}\n"
            context_str += "\n"

        return context_str

    async def generate_dashboard_code(
            self,
            query: str,
            summaries: List[Dict[str, Any]],
            component_plans: List[Any],
            interaction_hint: str = ""
    ) -> str:
        """
        生成看板代码 (异步版)
        """

        # 1. 构建数据背景字符串 (Context)
        context_str = self._build_context_str(summaries)
        available_vars = [s.get('variable_name') for s in summaries]

        # 2. 获取 System Prompt
        system_prompt = self.scaffold.get_system_prompt(context_str)

        # 3. 构建组件需求描述与组件隔离
        comp_desc = ""
        frame_format_hint = "%H:00"
        time_bounds_hint = ""

        if component_plans:
            for comp in component_plans:
                is_dict = isinstance(comp, dict)
                c_id = comp.get('id') if is_dict else getattr(comp, 'id', 'unknown')
                c_type = comp.get('type') if is_dict else getattr(comp, 'type', 'unknown')
                c_title = comp.get('title') if is_dict else getattr(comp, 'title', 'unknown')
                c_type_str = str(c_type).split('.')[-1].lower()

                # --- 隔离并提取系统组件配置 ---
                if c_type_str == 'timeline_controller':
                    t_conf = comp.get('timeline_config', {}) if is_dict else getattr(comp, 'timeline_config', {})
                    if t_conf:
                        start = t_conf.get('start_time') if isinstance(t_conf, dict) else getattr(t_conf, 'start_time',
                                                                                                  '')
                        end = t_conf.get('end_time') if isinstance(t_conf, dict) else getattr(t_conf, 'end_time', '')
                        fmt = t_conf.get('frame_format') if isinstance(t_conf, dict) else getattr(t_conf,
                                                                                                  'frame_format', '')
                        if start and end: time_bounds_hint = f"FROM {start} TO {end}"
                        if fmt: frame_format_hint = fmt
                    continue

                c_conf = comp.get('chart_config', {}) if is_dict else getattr(comp, 'chart_config', {})
                m_conf = comp.get('map_config', []) if is_dict else getattr(comp, 'map_config', [])

                config_hint = ""
                # A. 处理统计图表配置
                if c_conf:
                    t_bucket = c_conf.get('time_bucket') if isinstance(c_conf, dict) else getattr(c_conf, 'time_bucket',
                                                                                                  None)
                    ctype = c_conf.get('chart_type') if isinstance(c_conf, dict) else getattr(c_conf, 'chart_type', '')
                    config_hint = f" [Type: {ctype}, Bucket: {t_bucket}]"

                # B. 识别动画意图并设置硬约束标签
                is_anim = False
                if m_conf and isinstance(m_conf, list) and len(m_conf) > 0:
                    first_layer = m_conf[0]
                    is_anim = first_layer.get('is_animated') if isinstance(first_layer, dict) else getattr(first_layer,
                                                                                                           'is_animated',
                                                                                                           False)
                    anim_col = first_layer.get('animation_column') if isinstance(first_layer, dict) else getattr(
                        first_layer, 'animation_column', None)

                if is_anim:
                    config_hint += f" [🚨 ANIMATED by {anim_col}]"
                else:
                    config_hint += f" [🔒 STRICTLY STATIC - NO ANIMATION]"

                comp_desc += f"- 组件ID: `{c_id}` ({c_type_str}){config_hint}, 标题: {c_title}\n"

        # [核心修复] 强化执行标准，严禁动画幻觉与大小写错误
        user_prompt = f"""
        User Query: "{query}"

        === 🚨 TEMPORAL CONSTRAINTS 🚨 ===
        The target timeline range: {time_bounds_hint}
        The animation frame format contract (if applicable): `{frame_format_hint}`

        === 🚨 CRITICAL EXECUTION STANDARDS 🚨 ===
        1. **NO ANIMATION HALLUCINATION**: If a component is marked as [STRICTLY STATIC], you MUST NOT use `animation_frame` or create frame-based data loops. Use Recipe A instead of Recipe G.
        2. **COLUMN NAMES**: You MUST use the EXACT column names provided in the context. They are CASE-SENSITIVE (e.g., 'zone' is NOT 'Zone').
        3. **VARIABLE ACCESS**: Use ONLY {json.dumps(available_vars)}. Use `.copy()` for each component block.
        4. **DATA CLIPPING**: For components with time bounds, you MUST filter your dataframes to stay within: {time_bounds_hint}.
        5. **JOIN SAFETY**: Check `dtype` in Context. If joining, ensure ID columns are cast to string: `.astype(str)`.
        6. **SPATIAL PROJECTION**: MUST use `.to_crs(epsg=4326)` for all Mapbox figures.
        7. **ANIMATION CONTRACT**: For [ANIMATED] map, use Recipe G and format the frame column strictly as `{frame_format_hint}`.

        === DASHBOARD COMPONENTS TO IMPLEMENT ===
        {comp_desc}

        === INTERACTION HINTS ===
        {interaction_hint}

        Please write the `get_dashboard_data(data_context)` function. Apply the correct Recipes from the System Prompt.
        """

        logger.info(
            f"Generating optimized STV code for components (Animation Check: {is_anim if 'is_anim' in locals() else 'N/A'})...")

        raw_response = await self.llm.chat_async([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ], json_mode=False)

        return self._clean_markdown(raw_response)

    async def fix_code(self, original_code: str, error_trace: str, summaries: List[Dict[str, Any]]) -> str:
        """
        自愈修复逻辑 (异步版)
        """
        context_str = self._build_context_str(summaries)
        base_prompt = self.scaffold.get_system_prompt(context_str)
        available_vars = [s.get('variable_name') for s in summaries]

        fix_prompt = f"""
        CODE EXECUTION FAILED. 

        === ERROR TRACEBACK ===
        {error_trace}

        === ORIGINAL CODE ===
        {original_code}

        === 🚨 DIAGNOSTIC CHECKLIST 🚨 ===
        1. **Column Names**: CHECK THE CONTEXT CAREFULLY. Note the case sensitivity.
        2. **Animation check**: Did you add animation frames to a STATIC component? If so, remove them.
        3. **Variable Keys**: Only {json.dumps(available_vars)} exist.
        4. **Join Error**: Ensure ID columns are cast to string `.astype(str)` before merge.
        5. **CRS Error**: Ensure EPSG:4326 for maps.

        Please return the complete FIXED code block.
        """

        logger.warning("Attempting self-healing fix for STV code...")

        raw_response = await self.llm.chat_async([
            {"role": "system", "content": base_prompt},
            {"role": "user", "content": fix_prompt}
        ], json_mode=False)

        return self._clean_markdown(raw_response)