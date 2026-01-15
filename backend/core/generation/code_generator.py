import logging
from typing import Dict, Any, List
from core.llm.AI_client import AIClient

logger = logging.getLogger(__name__)


class CodeGenerator:
    """
    代码生成器（看板版）：
    负责生成符合 get_dashboard_data(data_context) 协议的 Python 代码。
    支持多组件并行处理及多模态交互过滤。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    def _get_system_prompt(self, summaries: List[Dict[str, Any]]) -> str:
        # 提取字段背景，防止 LLM 幻觉
        context_str = ""
        for s in summaries:
            var_name = s.get('variable_name')
            cols = list(s.get('basic_stats', {}).get('column_stats', {}).keys())
            context_str += f"- 变量 `{var_name}` 可用列: {cols}\n"

        return f"""
你是时空数据分析专家。请根据要求编写 Python 函数。

=== 数据上下文 ===
{context_str}

=== 强制约束 ===
1. 函数签名：必须定义为 `def get_dashboard_data(data_context):`。
2. 返回格式：必须返回一个 Dict，Key 是组件 ID，Value 是数据对象（Plotly Figure 或 DataFrame/GeoDataFrame）。
3. 地理处理：
   - 必须使用 `geopandas` 处理空间数据。
   - 坐标系统一使用 WGS84 (EPSG:4326)。
   - 地图组件请优先返回 `px.scatter_mapbox` 或 `px.choropleth_mapbox`。
4. 交互处理：
   - 如果用户提供了 BBox (框选) 信息，必须在代码最开始对主数据集进行空间过滤。
   - 空间过滤示例: `df = df[(df.lon >= min_x) & (df.lon <= max_x) & ...]` 或使用 `gdf.cx`。
"""

    def generate_dashboard_code(
            self,
            query: str,
            summaries: List[Dict[str, Any]],
            component_plans: List[Any],
            interaction_hint: str = ""
    ) -> str:
        """
        为多个组件生成统一的数据处理逻辑
        """
        system_prompt = self._get_system_prompt(summaries)

        # 构造组件需求描述
        comp_desc = ""
        for comp in component_plans:
            comp_desc += f"- 组件 ID `{comp.id}` ({comp.type}): {comp.title}\n"

        user_prompt = f"""
用户分析需求: "{query}"

=== 看板规划清单 ===
{comp_desc}

=== 交互与钻取上下文 ===
{interaction_hint}

=== 任务 ===
请编写 Python 代码。代码逻辑如下：
1. 从 data_context 中提取相关变量。
2. 【关键】如果存在交互上下文，应用空间过滤或属性过滤。
3. 为清单中的每个组件计算对应的数据/图表。
4. 返回字典，例如：return {{ "map_1": fig, "chart_1": fig_bar }}

请只输出代码块，不要有解释。
"""

        logger.info("Generating multi-component dashboard code...")
        return self.llm.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ], json_mode=False)

    def fix_code(self, original_code: str, error: str, summaries: List[Dict[str, Any]]) -> str:
        """
        自愈逻辑 (保留原有优势)
        """
        # ... 这里可以复用你之前实现的 fix_code 逻辑，针对报错进行修复 ...
        pass