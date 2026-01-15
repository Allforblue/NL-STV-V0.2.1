import logging
import re
from typing import Dict, Any, List
from core.llm.AI_client import AIClient
from core.generation.scaffold import STChartScaffold

logger = logging.getLogger(__name__)


class CodeGenerator:
    def __init__(self, llm_client: AIClient):
        self.llm = llm_client
        self.scaffold = STChartScaffold()

    def _clean_markdown(self, text: str) -> str:
        """
        [新增] 内部工具方法：去除 LLM 返回的 Markdown 代码块标记。
        兼容 ```python, ```, 以及前后空白。
        """
        if not text:
            return ""

        # 去除首尾空白
        text = text.strip()

        # 1. 尝试去除开头的 ```python 或 ```
        # 使用正则匹配开头，忽略大小写
        text = re.sub(r"^```(python)?\s*", "", text, flags=re.IGNORECASE)

        # 2. 尝试去除结尾的 ```
        text = re.sub(r"\s*```$", "", text)

        return text.strip()

    def generate_code(self, query: str, summaries: List[Dict[str, Any]]) -> str:
        """
        利用 Scaffold 生成代码 (带 Markdown 清洗)
        """
        system_prompt = self.scaffold.get_system_prompt(summaries)
        template = self.scaffold.get_template(library="plotly")

        user_prompt = f"""
        User Query: "{query}"

        Complete the following code template to solve the query.

        Template:
        {template}

        Return the COMPLETE python code block (including imports and the function).
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        logger.info(f"Generating code with scaffold for: '{query}'...")
        raw_response = self.llm.chat(messages, json_mode=False)

        # 清洗并返回
        return self._clean_markdown(raw_response)

    def fix_code(self, original_code: str, error_trace: str, summaries: List[Dict[str, Any]]) -> str:
        """
        自愈修复方法 (增强版 v5 - 导入修正 + 反逻辑谬误 + Markdown 清洗)
        """
        system_prompt = self.scaffold.get_system_prompt(summaries)

        # 构建变量名和列名清单
        available_columns_hint = "=== REAL AVAILABLE COLUMNS & VARIABLES ===\n"
        for summary in summaries:
            var_name = summary.get('variable_name', 'unknown')
            columns = list(summary.get("basic_stats", {}).get("column_stats", {}).keys())
            columns_str = str(columns[:50])
            available_columns_hint += f"Variable `{var_name}` columns: {columns_str}\n"

        specific_hint = ""

        # [针对 Pandas Drop 错误]
        if "not found in axis" in error_trace and "drop" in original_code:
            specific_hint += """
           [HINT: DataFrame Column Error]
           - You tried to `.drop()` a column (e.g. LocationID_y) that does not exist.
           - `pd.merge` ONLY adds suffixes (_x, _y) if columns have the SAME name in both dataframes.
           - FIX: Remove the `.drop()` call. Check `merged_df.columns` logic.
           """

        # [针对 Merge 逻辑的优化建议]
        if "pd.merge" in original_code and "groupby" in original_code:
            specific_hint += """
           [HINT: Optimization & Logic Flow]
           - Current logic (Merge -> Group -> Merge) is risky and slow.
           - BETTER LOGIC: 
             1. Group the Trips DataFrame by ID first: `df_counts = df_trips.groupby('PULocationID')...`
             2. THEN merge with Zones GeoDataFrame: `gdf = df_zones.merge(df_counts, left_on='LocationID', right_on='PULocationID')`
             3. Plot `gdf`.
           - This ensures you don't lose the geometry column or confuse column names.
           """

        # [针对 导入错误 (ModuleNotFoundError)]
        if "No module named" in error_trace:
            specific_hint += """
            [HINT: Import Error]
            - You likely wrote `import gpd` or similar. THIS IS WRONG.
            - Standard imports ONLY: 
              `import pandas as pd`
              `import geopandas as gpd`
              `import plotly.express as px`
            """

        # [针对 几何捏造错误 (points_from_xy 使用了 ID)]
        if "points_from_xy" in original_code and ("ID" in original_code or "id" in original_code):
            specific_hint += """
            [HINT: LOGIC ERROR - DO NOT CREATE GEOMETRY FROM IDs]
            - You are trying to create points/polygons using an ID column (e.g. LocationID). This is IMPOSSIBLE.
            - LocationID is NOT a coordinate.
            - SOLUTION: Merge your data with the Shapefile DataFrame (available in data_context) to get the 'geometry' column.
            - Pattern: `df_map = df_zones_shapefile.merge(df_stats, on='LocationID')`.
            """

        # [针对 KeyError]
        if "KeyError" in error_trace:
            specific_hint += """
            [HINT: KeyError detected] 
            1. LOOK AT THE 'REAL AVAILABLE COLUMNS' LIST ABOVE! 
            2. Check Case Sensitivity ('zone' vs 'Zone').
            3. Check if you lost columns during a merge.
            """

        # [针对 幻觉代码]
        if "Example usage" in original_code or "data_context =" in original_code or "plot(data_context)" in original_code:
            specific_hint += """
            [HINT: Clean Code]
            - Remove `# Example usage`, mock data, or function calls at the bottom.
            - ONLY return the `def plot(data_context):` function.
            """

        # 重复的 hints 合并处理 (你的原始代码中有部分重复逻辑，保留以维持原样，或可清理)
        if "No module named" in error_trace and "import gpd" not in specific_hint:
            specific_hint += "\n[HINT] Use `import geopandas as gpd`.\n"

        if "KeyError" in error_trace and "Case Sensitivity" not in specific_hint:
            specific_hint += "\n[HINT] Check Column Case Sensitivity (e.g. 'Zone' vs 'zone'). Check available columns list.\n"

        fix_prompt = f"""
        The code you generated previously failed to execute.

        {available_columns_hint}

        === BROKEN CODE ===
        {original_code}

        === ERROR TRACEBACK ===
        {error_trace}

        === INSTRUCTION ===
        1. Analyze the error using the hints above.
        {specific_hint}
        2. Fix the code.
        3. [CRITICAL] Ensure you use `import geopandas as gpd` (NOT `import gpd`).
        4. Return ONLY the fixed Python code block inside markdown.
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": fix_prompt}
        ]

        logger.warning(f"Attempting to FIX code based on error...")
        raw_response = self.llm.chat(messages, json_mode=False)

        # 清洗并返回
        return self._clean_markdown(raw_response)