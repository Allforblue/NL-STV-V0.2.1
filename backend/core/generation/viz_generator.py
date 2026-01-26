import logging
import re
from typing import Dict, Any, List
from core.llm.AI_client import AIClient
# [新增] 引入 Scaffold
from core.generation.scaffold import STChartScaffold

logger = logging.getLogger(__name__)


class CodeGenerator:
    """
    代码生成器：
    利用 STChartScaffold 的食谱生成高质量绘图代码。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client
        # [新增] 实例化脚手架
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

    def generate_dashboard_code(
            self,
            query: str,
            summaries: List[Dict[str, Any]],
            component_plans: List[Any],
            interaction_hint: str = ""
    ) -> str:

        # 1. 构建数据背景字符串 (Context)
        context_str = ""
        for s in summaries:
            var_name = s.get('variable_name')
            stats = s.get('basic_stats', {}) or {}
            cols = list(stats.get('column_stats', {}).keys())
            context_str += f"- 变量 `{var_name}` 可用列: {cols[:50]}\n"

        # 2. [修改] 从 Scaffold 获取 System Prompt (包含 Recipes)
        system_prompt = self.scaffold.get_system_prompt(context_str)

        # 3. 构建用户需求
        comp_desc = ""
        if component_plans:
            for comp in component_plans:
                if isinstance(comp, dict):
                    c_id, c_type, c_title = comp.get('id'), comp.get('type'), comp.get('title')
                    c_conf = comp.get('chart_config', {})
                else:
                    c_id = getattr(comp, 'id', 'unknown')
                    c_type = getattr(comp, 'type', 'unknown')
                    c_title = getattr(comp, 'title', 'unknown')
                    c_conf = getattr(comp, 'chart_config', {})

                # 如果是 Chart 类型，把 chart_type 也传进去 (方便识别是用 Bar 还是 Pie)
                chart_type_hint = ""
                if c_type == 'chart' and c_conf:
                    # chart_config 可能是 dict 或 object
                    ctype = c_conf.get('chart_type') if isinstance(c_conf, dict) else getattr(c_conf, 'chart_type', '')
                    chart_type_hint = f" (Preferred Chart Type: {ctype})"

                comp_desc += f"- 组件ID: `{c_id}` ({c_type}){chart_type_hint}, 标题: {c_title}\n"

        user_prompt = f"""
        User Query: "{query}"

        === DASHBOARD COMPONENTS TO IMPLEMENT ===
        {comp_desc}

        === INTERACTION HINTS ===
        {interaction_hint}

        Please write the `get_dashboard_data` function. 
        Apply the Recipes (A/B/C/D) that best fit each component.
        """

        logger.info(f"Generating code with Scaffold for {len(component_plans)} components...")
        raw_response = self.llm.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ], json_mode=False)

        return self._clean_markdown(raw_response)

    def fix_code(self, original_code: str, error_trace: str, summaries: List[Dict[str, Any]]) -> str:
        """自愈修复逻辑"""
        # 修复时也可以带上 scaffold 的规则，防止越修越错
        base_prompt = self.scaffold.get_system_prompt("")  # 空 context 仅获取规则

        fix_prompt = f"""
        CODE EXECUTION FAILED.

        === ERROR TRACEBACK ===
        {error_trace}

        === ORIGINAL CODE ===
        {original_code}

        === FIX INSTRUCTIONS ===
        1. Check imports (numpy, shapely, etc).
        2. Check dictionary access (`data_context['key']`).
        3. Check for empty/NaN data before plotting.
        4. Return the FIXED complete code block.
        """

        logger.warning("Attempting to fix code with Scaffold rules...")
        raw_response = self.llm.chat([
            {"role": "system", "content": base_prompt},
            {"role": "user", "content": fix_prompt}
        ], json_mode=False)

        return self._clean_markdown(raw_response)