import logging
import json
from typing import Dict, Any, List, Optional
from core.llm.AI_client import AIClient
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

    def identify_interaction_anchors(self, summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        分析多个数据集的画像，找出潜在的交互联动点。

        返回示例:
        [
          {"source": "df_taxi", "target": "df_zones", "key": "LocationID", "type": "click"},
          {"source": "df_taxi", "target": "ANY", "key": ["lat", "lon"], "type": "bbox"}
        ]
        """
        if not summaries:
            return []

        logger.info(f">>> 正在识别 {len(summaries)} 个数据集间的交互联动锚点...")

        # 1. 提取核心语义标签供 LLM 分析
        meta_context = []
        for s in summaries:
            meta = {
                "var_name": s.get("variable_name"),
                "semantic_tags": s.get("semantic_analysis", {}).get("semantic_tags", {}),
                "description": s.get("semantic_analysis", {}).get("description")
            }
            meta_context.append(meta)

        # 2. 构建 Prompt
        system_prompt = """
        你是一位时空数据交互专家。你需要分析多个数据集的元数据，识别它们之间如何通过 UI 操作进行联动。

        联动类型定义：
        1. BBOX (框选): 源数据含经纬度(ST_LAT/LON)，操作地图时可过滤目标数据。
        2. CLICK (点击): 源数据与目标数据含共同的 ID 或分类字段(ST_LOC_ID, BIZ_CAT, ID_KEY)。
        3. TIME (时间): 源数据含时间戳(ST_TIME)，操作时间轴时联动。
        """

        user_prompt = f"""
        数据集元数据如下:
        {json.dumps(meta_context, indent=2, ensure_ascii=False)}

        请列出所有高价值的交互联动逻辑。输出格式为 JSON 数组：
        [
          {{
            "source_var": "源变量名",
            "target_var": "目标变量名 (若为全局过滤则填 'GLOBAL')",
            "interaction_type": "BBOX | CLICK",
            "anchor_key": "用于联动的字段名 (若是 BBOX 可填经纬度字段列表)",
            "description": "描述交互效果，如 '点击地图区域，联动更新右侧饼图'"
          }}
        ]
        """

        try:
            anchors = self.llm.query_json(prompt=user_prompt, system_prompt=system_prompt)
            logger.info(f"✅ 识别到 {len(anchors)} 条潜在交互联动规则。")
            return anchors
        except Exception as e:
            logger.error(f"交互锚点识别失败: {e}")
            return []

    def get_planner_hints(self, anchors: List[Dict[str, Any]]) -> str:
        """
        将识别到的锚点转化为 DashboardPlanner 可理解的 Prompt 提示。
        """
        if not anchors:
            return ""

        hint = "\n=== 建议的交互联动规划 (Interaction Hints) ===\n"
        for a in anchors:
            hint += f"- {a['description']}: "
            hint += f"建议在规划时让 `{a['source_var']}` 的组件 Links 指向 `{a['target_var']}`，"
            hint += f"使用键值 `{a['anchor_key']}`。\n"
        return hint

    def filter_data_by_interaction(self, df: Any, payload: Any) -> Any:
        """
        [工具方法] 根据交互载荷对 DataFrame 进行预过滤。
        支撑后期 VizEditor 生成更高效的代码。
        """
        # 如果是 BBox 框选
        if payload.bbox and len(payload.bbox) == 4:
            min_lon, min_lat, max_lon, max_lat = payload.bbox
            # 假设 df 是 GeoDataFrame
            if hasattr(df, 'cx'):
                return df.cx[min_lon:max_lon, min_lat:max_lat]

        # 如果是特定 ID 点击
        if payload.selected_ids:
            # 这里需要根据语义分析确定的 ID 字段进行过滤
            # 逻辑将由 VizEditor 在生成的 Python 代码中实现
            pass

        return df