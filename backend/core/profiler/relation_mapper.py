import logging
import json
from typing import Dict, Any, List, Optional
from core.llm.AI_client import AIClient

logger = logging.getLogger(__name__)


class RelationMapper:
    """
    关系映射器：
    负责检测多个数据集之间的关联逻辑（ID关联、空间包含或属性匹配）。
    为 VizEditor/CodeGenerator 提供数据关联路径的“导航信息”。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    async def map_relations(self, summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        分析多个数据摘要，识别它们之间的潜在关联。
        """
        if not summaries or len(summaries) < 2:
            return []

        logger.info(f">>> 正在分析 {len(summaries)} 个数据集之间的逻辑关系...")

        # 1. 提取深度元数据：LLM 需要知道字段名和类型才能准确判断 ID_LINK
        datasets_meta = []
        for s in summaries:
            meta = {
                "variable_name": s.get("variable_name"),
                "dataset_type": s.get("semantic_analysis", {}).get("dataset_type"),
                "description": s.get("semantic_analysis", {}).get("description"),
                "is_geospatial": s.get("is_geospatial", False),
                # 提取列名及其语义标签，这是关联的核心
                "columns": [
                    {
                        "name": col,
                        "dtype": info.get("dtype"),
                        "tag": s.get("semantic_analysis", {}).get("semantic_tags", {}).get(col),
                        "geom_type": info.get("geom_type") if "geom_type" in info else None
                    }
                    for col, info in s.get("column_stats", {}).items()
                ]
            }
            datasets_meta.append(meta)

        # 2. 构建系统提示词
        system_prompt = """
        你是一位高级数据仓库架构师和 GIS 专家。你的任务是识别不同 DataFrame 之间的关联路径。

        关联类型定义：
        1. ID_LINK: 两个数据集通过共同的 ID 字段（如 'order_id', 'zone_code'）关联。
        2. SPATIAL_LINK (重要): 一个数据集包含点数据(Point)，另一个包含面数据(Polygon/MultiPolygon)。可以通过 'sjoin' (Spatial Join) 进行包含关系分析。
        3. ATTRIBUTE_LINK: 通过相同的分类/文本属性关联（如 'city_name', 'category'）。

        准则：
        - 优先寻找语义标签一致的字段。
        - 如果一个变量是 GeoDataFrame 且含 Polygon，另一个含 Point，务必标注 SPATIAL_LINK。
        - strength 代表关联的明确程度（0.0-1.0），字段名完全一致且语义一致为 1.0。
        """

        user_prompt = f"""
        待分析的数据集元数据如下:
        {json.dumps(datasets_meta, indent=2, ensure_ascii=False)}

        请分析关联路径并以 JSON 数组格式输出：
        [
          {{
            "source": "变量A",
            "target": "变量B",
            "type": "ID_LINK | SPATIAL_LINK | ATTRIBUTE_LINK",
            "join_on": ["字段A", "字段B"], 
            "strength": 0.9,
            "reason": "原因描述，例如：pickup_location_id 与 zone_id 语义匹配且均为整数类型"
          }}
        ]
        """

        try:
            # 调用异步请求
            relations = await self.llm.query_json_async(prompt=user_prompt, system_prompt=system_prompt)

            # 兼容性处理
            if isinstance(relations, dict) and "relations" in relations:
                relations = relations["relations"]

            if not isinstance(relations, list):
                logger.warning(f"LLM 返回格式非数组: {type(relations)}")
                return []

            logger.info(f"✅ 识别到 {len(relations)} 条潜在关联路径。")
            return relations

        except Exception as e:
            logger.error(f"关系映射失败: {e}")
            return []

    def get_drilldown_hint(self, source_var: str, relations: List[Dict[str, Any]]) -> str:
        """
        根据当前操作的变量，生成用于 CodeGenerator 的提示语。
        帮助 LLM 决定如何写数据合并或过滤的代码。
        """
        relevant = [r for r in relations if r.get('source') == source_var or r.get('target') == source_var]
        if not relevant:
            return ""

        hint = "\n=== 数据关联与钻取提示 (Data Relation Hints) ===\n"
        for r in relevant:
            other = r['target'] if r['source'] == source_var else r['source']
            join_cols = " & ".join(r.get('join_on', []))

            if r['type'] == 'SPATIAL_LINK':
                hint += f"- 空间关联: `{source_var}` 可以通过地理空间位置(Point-in-Polygon)与 `{other}` 进行关联分析。\n"
            else:
                hint += f"- 逻辑关联: `{source_var}` 可通过字段 `{join_cols}` 钻取/连接到数据集 `{other}`。\n"
                hint += f"  (依据: {r.get('reason', '语义匹配')})\n"

        return hint