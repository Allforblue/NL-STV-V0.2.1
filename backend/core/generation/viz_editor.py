import logging
import re
import json
from typing import Dict, Any, List, Optional
from core.llm.AI_client import AIClient
from core.schemas.interaction import InteractionTriggerType

logger = logging.getLogger(__name__)


class VizEditor:
    """
    可视化编辑器 (V2 联动增强版)：
    负责根据用户的交互动作（点选、框选、指令）增量修改 Python 代码。
    支持“联动响应”逻辑：即一个组件的动作如何影响其他组件的数据。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    def _clean_markdown(self, text: str) -> str:
        """去除 Markdown 格式，提取纯 Python 代码"""
        if not text: return ""
        text = text.strip()
        text = re.sub(r"^```(python)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        return text.strip()

    def _get_editor_prompt(self, original_code: str, summaries: List[Dict[str, Any]]) -> str:
        # 提取语义背景，方便 AI 知道哪个字段对应经纬度或 ID
        context_str = ""
        for s in summaries:
            var_name = s.get('variable_name')
            tags = s.get('semantic_analysis', {}).get('semantic_tags', {})
            context_str += f"- 变量 `{var_name}` 语义标签: {json.dumps(tags, ensure_ascii=False)}\n"

        return f"""
你是一位资深时空数据工程师。你的任务是根据用户的交互动作（Interaction），对现有的分析代码进行【手术级】的增量修改。

=== 现有代码 ===
{original_code}

=== 数据语义背景 ===
{context_str}

=== 强制约束 ===
1. 保持函数签名不变：`def get_dashboard_data(data_context):`。
2. 增量修改原则：
   - 尽可能保留原有的变量定义和数据加载逻辑。
   - 【核心】在聚合计算（groupby, count 等）之前，插入过滤代码。
3. 空间过滤规则：
   - 如果用户提供 BBox，优先使用 GeoPandas 的 `.cx[lon_min:lon_max, lat_min:lat_max]`。
   - 确保坐标系一致，必要时调用 `df = df.to_crs(epsg=4326)`。
4. 联动响应规则：
   - 如果是 UI 交互，请识别受影响的组件 ID。
   - 只针对受影响的数据流进行修改，不要破坏其他无关组件。
"""

    def edit_dashboard_code(
            self,
            original_code: str,
            payload: Any,  # InteractionPayload
            summaries: List[Dict[str, Any]],
            links: List[Any] = None  # 来自 DashboardSchema 的联动元数据
    ) -> str:
        """
        核心方法：基于交互载荷编辑代码，实现语义钻取与联动。
        """
        system_prompt = self._get_editor_prompt(original_code, summaries)

        # 1. 构造交互描述（告诉 AI 发生了什么）
        interaction_desc = f"触发源类型: {payload.trigger_type}\n"

        if payload.trigger_type == InteractionTriggerType.UI_ACTION:
            interaction_desc += f"触发组件: `{payload.active_component_id}`\n"
            if payload.bbox:
                interaction_desc += f"动作：在地图上框选了范围 {payload.bbox}。请对受影响的数据流进行空间过滤(Spatially Filter)。\n"
            if payload.selected_ids:
                interaction_desc += f"动作：点击选中了 ID 列表 {payload.selected_ids}。请进行属性过滤(Attribute Filter)。\n"
        else:
            interaction_desc += f"自然语言指令: \"{payload.query}\"。请根据指令修改看板内容或分析维度。\n"

        # 2. 注入联动上下文（告诉 AI 谁应该跟着变）
        if links:
            link_hints = "\n=== 联动规则提示 ===\n"
            for link in links:
                link_hints += f"- 当 `{payload.active_component_id}` 动作时，应过滤 `{link.target_id}` 的数据，关联键为 `{link.link_key}`。\n"
            interaction_desc += link_hints

        user_prompt = f"""
=== 交互描述 ===
{interaction_desc}

=== 任务目标 ===
请修改原有代码，使看板响应上述交互。
如果涉及空间过滤，请务必在代码最开始的部分对相关的 GeoDataFrame 应用 `.cx` 过滤。
如果涉及属性过滤，请使用 `df[df[key].isin(ids)]` 逻辑。

请只输出修改后的完整 Python 代码块。
"""

        logger.info(f">>> Editing code for interaction on: {payload.active_component_id or 'Chat'}")

        try:
            raw_response = self.llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ], json_mode=False)

            return self._clean_markdown(raw_response)
        except Exception as e:
            logger.error(f"Code editing failed: {e}")
            return original_code  # 失败则返回原代码，保证系统不崩溃