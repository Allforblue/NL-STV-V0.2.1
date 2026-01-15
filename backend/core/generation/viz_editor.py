import logging
import re
from typing import Dict, Any, List
from core.llm.AI_client import AIClient

logger = logging.getLogger(__name__)


class VizEditor:
    """
    可视化编辑器：
    负责将用户的交互动作（如框选、指令）映射为对现有代码的修改。
    实现“语义钻取”的核心引擎。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    def _clean_markdown(self, text: str) -> str:
        """
        [新增] 去除 LLM 返回的 Markdown 代码块标记。
        复用 CodeGenerator 中的逻辑，确保 Executor 能正确执行。
        """
        if not text:
            return ""

        text = text.strip()
        # 去除开头的 ```python 或 ```
        text = re.sub(r"^```(python)?\s*", "", text, flags=re.IGNORECASE)
        # 去除结尾的 ```
        text = re.sub(r"\s*```$", "", text)

        return text.strip()

    def _get_editor_prompt(self, original_code: str, summaries: List[Dict[str, Any]]) -> str:
        return f"""
你是一位资深时空数据工程师。你的任务是根据用户的交互动作，修改现有的分析代码。

=== 现有代码 ===
{original_code}

=== 强制约束 ===
1. 保持函数签名不变：`def get_dashboard_data(data_context):`。
2. 增量修改：尽可能保留原有的数据处理逻辑，只根据新的交互动作进行过滤或变换。
3. 空间钻取逻辑：
   - 如果用户提供了 BBox，在代码中使用 `.cx` (GeoPandas) 或 经纬度过滤。
   - 过滤必须在所有聚合计算之前完成。
4. 返回结构：确保返回的 Dict 依然包含原有的组件 ID，除非用户要求删除。
"""

    def edit_dashboard_code(
            self,
            original_code: str,
            payload: Any,  # InteractionPayload
            summaries: List[Dict[str, Any]]
    ) -> str:
        """
        基于交互动作编辑代码，实现下钻
        """
        system_prompt = self._get_editor_prompt(original_code, summaries)

        # 构造交互指令描述
        interaction_desc = f"用户指令: {payload.query}\n"

        # 处理可能的 None 情况
        if getattr(payload, 'bbox', None):
            interaction_desc += f"地图交互动作：框选了区域 {payload.bbox}。请针对该区域进行下钻分析。\n"

        if getattr(payload, 'selected_ids', None):
            interaction_desc += f"地图交互动作：选中了 ID 为 {payload.selected_ids} 的对象。\n"

        user_prompt = f"""
=== 交互动作描述 ===
{interaction_desc}

=== 任务 ===
请修改现有代码以响应上述交互。
如果是 BBox 框选，请在代码开头应用空间过滤器。
如果是文字指令，请相应调整可视化组件的类型或分析指标。

请只输出修改后的 Python 代码块。
"""

        logger.info("Editing existing dashboard code for drill-down...")
        raw_response = self.llm.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ], json_mode=False)

        return self._clean_markdown(raw_response)