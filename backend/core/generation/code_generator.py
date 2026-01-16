import logging
import re
from typing import Dict, Any, List, Union
from core.llm.AI_client import AIClient

logger = logging.getLogger(__name__)


class CodeGenerator:
    """
    代码生成器：
    负责生成符合 get_dashboard_data(data_context) 协议的 Python 代码。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    def _clean_markdown(self, text: str) -> str:
        """
        [关键修复] 健壮的代码提取逻辑
        不再只是去除首尾标记，而是正则匹配提取代码块内容，丢弃所有 LLM 的废话。
        """
        if not text:
            return ""

        # 1. 尝试匹配 ```python ... ``` (包含换行)
        # re.DOTALL 让 . 匹配换行符
        pattern = r"```(?:python)?\s*(.*?)```"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)

        if match:
            # 提取中间的内容并去空格
            return match.group(1).strip()

        # 2. 如果没找到代码块标记，尝试直接清洗首尾（兜底）
        # 有时候 LLM 可能会忘记写结尾的 ```
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

        # 1. 构建变量背景
        context_str = ""
        for s in summaries:
            var_name = s.get('variable_name')
            stats = s.get('basic_stats', {}) or {}
            cols = list(stats.get('column_stats', {}).keys())
            context_str += f"- 变量 `{var_name}` 可用列: {cols[:50]}\n"

        # 2. 构建组件需求
        comp_desc = ""
        if component_plans:
            for comp in component_plans:
                if isinstance(comp, dict):
                    c_id = comp.get('id')
                    c_type = comp.get('type')
                    c_title = comp.get('title')
                else:
                    c_id = getattr(comp, 'id', 'unknown')
                    c_type = getattr(comp, 'type', 'unknown')
                    c_title = getattr(comp, 'title', 'unknown')

                comp_desc += f"- 组件ID: `{c_id}` ({c_type}), 标题: {c_title}\n"

        system_prompt = f"""
        你是时空数据分析专家。请编写 Python 代码以生成看板数据。

        === 数据环境 ===
        {context_str}

        === 强制约束 (CRITICAL) ===
        1. 函数签名：必须定义为 `def get_dashboard_data(data_context):`。
        2. 数据访问：`data_context` 是一个字典(Dict)。
           - ❌ 错误写法: `df = data_context.df_name`
           - ✅ 正确写法: `df = data_context['df_name']`
        3. 必须显式导入所有库：
           - `import pandas as pd`, `import geopandas as gpd`, `import plotly.express as px`
           - `import numpy as np`, `import random`, `import json`
           - `from shapely.geometry import Point, Polygon`
        4. 返回格式：必须返回 Dict，Key是组件ID，Value是 Figure 或 DataFrame。
        """

        user_prompt = f"""
        用户需求: "{query}"

        === 看板组件清单 ===
        {comp_desc}

        === 交互/关联提示 ===
        {interaction_hint}

        请编写完整的 Python 代码块。不要包含任何解释性文字。
        """

        logger.info(f"Generating code for {len(component_plans)} components...")
        raw_response = self.llm.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ], json_mode=False)

        return self._clean_markdown(raw_response)

    def fix_code(self, original_code: str, error_trace: str, summaries: List[Dict[str, Any]]) -> str:
        """自愈修复逻辑"""
        system_prompt = "你是 Python 代码修复专家。"

        fix_prompt = f"""
        代码执行失败。

        === 错误堆栈 ===
        {error_trace}

        === 原始代码 ===
        {original_code}

        === 修复指南 ===
        1. 如果是 AttributeError: 'dict' object has no attribute... -> 请改用 `data_context['key']` 访问。
        2. 如果是 NameError -> 请检查 import。
        3. 如果是 SyntaxError -> 请检查是否包含非代码文本。

        请返回修复后的完整代码。只返回代码块。
        """

        logger.warning("Attempting to fix code...")
        raw_response = self.llm.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": fix_prompt}
        ], json_mode=False)

        return self._clean_markdown(raw_response)