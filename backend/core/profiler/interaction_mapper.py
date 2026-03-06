import logging
import json
from typing import Dict, Any, List, Optional
from core.llm.AI_client import AIClient
# 假设你的 InteractionType 定义了 BBOX, CLICK, TIME, FILTER 等
from core.schemas.dashboard import InteractionType

logger = logging.getLogger(__name__)


class InteractionMapper:
    """
    交互映射器：
    专门识别数据集之间可用于“联动过滤”的语义锚点。
    为 DashboardPlanner 提供具体的交互逻辑建议。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    async def identify_interaction_anchors(self, summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        分析多个数据集的画像，找出潜在的交互联动点。
        """
        if not summaries or len(summaries) < 1:
            return []

        logger.info(f">>> 正在分析 {len(summaries)} 个数据集间的潜在交互...")

        # 1. 提取更丰富的元数据上下文，帮助 LLM 判断
        meta_context = []
        for s in summaries:
            # 结合了 basic_stats 和 semantic_analyzer 的输出
            meta = {
                "var_name": s.get("variable_name"),
                "description": s.get("semantic_analysis", {}).get("description"),
                "columns": [
                    {
                        "name": col,
                        "dtype": info.get("dtype"),
                        "semantic_tag": s.get("semantic_analysis", {}).get("semantic_tags", {}).get(col),
                        "unique_count": info.get("unique_count")
                    }
                    for col, info in s.get("column_stats", {}).items()
                ],
                "is_geospatial": s.get("is_geospatial", False)
            }
            meta_context.append(meta)

        # 2. 构建 Prompt
        system_prompt = f"""
        你是一位时空数据交互设计专家。你需要分析多个数据集的元数据，识别它们之间如何通过 UI 操作进行联动。

        可选交互类型 (InteractionType):
        - {InteractionType.BBOX.value} (框选): 适用于带有地理坐标的数据集，在地图上缩放或圈选时，其他数据集按空间范围过滤。
        - {InteractionType.CLICK.value} (点击): 适用于具有共同 ID 或类别字段的数据集，点击图表元素时，其他图表高亮或过滤对应项。
        - {InteractionType.TIME.value} (时间): 适用于都含有时间戳的数据集，拖动时间轴时同步更新。

        准则：
        1. 寻找具有相同语义标签 (semantic_tag) 或相同列名的字段作为 anchor_key。
        2. 如果一个数据集有空间信息而另一个没有，可以建立 BBOX 到 GLOBAL 的空间过滤映射。
        """

        user_prompt = f"""
        以下是当前任务中的数据集元数据:
        {json.dumps(meta_context, indent=2, ensure_ascii=False)}

        请分析并列出所有合理的交互联动逻辑。输出格式必须为 JSON 数组:
        [
          {{
            "source_var": "源变量名",
            "target_var": "目标变量名 (若影响全部则填 'GLOBAL')",
            "interaction_type": "BBOX | CLICK | TIME",
            "anchor_key": "用于联动的字段名 (若是 BBOX 可填 [lat, lon] 字段名)",
            "description": "简单描述交互效果"
          }}
        ]
        """

        try:
            # 调用异步 LLM
            # 注意：确保提示词中要求返回的是数组
            response = await self.llm.query_json_async(prompt=user_prompt, system_prompt=system_prompt)

            # 兼容处理：有些 LLM 可能会返回 {"interactions": [...]}
            if isinstance(response, dict):
                for key in ["interactions", "data", "anchors"]:
                    if key in response:
                        anchors = response[key]
                        break
                else:
                    anchors = []  # 无法识别的结构
            else:
                anchors = response

            logger.info(f"✅ 成功识别到 {len(anchors)} 条交互规则。")
            return anchors

        except Exception as e:
            logger.error(f"交互锚点识别发生错误: {e}")
            return []

    def get_planner_hints(self, anchors: List[Dict[str, Any]]) -> str:
        """
        将识别到的锚点转化为 DashboardPlanner 可理解的 Prompt 提示。
        """
        if not anchors:
            return "（未发现明显的跨数据集联动需求）"

        hint = "\n### 💡 交互联动设计建议 (Interaction Design Hints)\n"
        for i, a in enumerate(anchors, 1):
            source = a.get('source_var')
            target = a.get('target_var')
            i_type = a.get('interaction_type')
            key = a.get('anchor_key')
            desc = a.get('description')

            hint += f"{i}. **{i_type} 联动**: {desc}\n"
            hint += f"   - 实现逻辑: 当 `{source}` 发生操作时，通过 `{key}` 字段过滤 `{target}`。\n"

        return hint

    def filter_data_by_interaction(self, df: Any, interaction_type: InteractionType, payload: Dict[str, Any]) -> Any:
        """
        [工具方法] 根据交互载荷对 DataFrame 进行预过滤。
        该方法常用于后端执行器，在生成静态图表或切片数据时调用。
        """
        try:
            # 1. 处理地理空间框选
            if interaction_type == InteractionType.BBOX:
                bbox = payload.get("bbox")  # [min_lon, min_lat, max_lon, max_lat]
                if bbox and len(bbox) == 4:
                    # 如果是 GeoDataFrame，使用 cx 高效过滤
                    if hasattr(df, 'cx'):
                        return df.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]

            # 2. 处理点击/分类过滤
            elif interaction_type == InteractionType.CLICK:
                selected_val = payload.get("value")
                key = payload.get("anchor_key")
                if key in df.columns and selected_val is not None:
                    return df[df[key] == selected_val]

            # 3. 处理时间区间过滤
            elif interaction_type == InteractionType.TIME:
                time_range = payload.get("range")  # [start, end]
                key = payload.get("anchor_key")
                if key in df.columns and time_range:
                    return df[(df[key] >= time_range[0]) & (df[key] <= time_range[1])]

        except Exception as e:
            logger.warning(f"过滤数据时出错: {e}")

        return df