import logging
import json
from typing import Dict, Any, List, Optional
from core.llm.AI_client import AIClient

logger = logging.getLogger(__name__)


class RelationMapper:
    """
    关系映射器：
    负责检测多个数据集之间的关联逻辑（ID关联或空间关联）。
    为 VizEditor 提供钻取路径的“导航信息”。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    def map_relations(self, summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        分析多个数据摘要，识别它们之间的潜在关联。
        """
        if len(summaries) < 2:
            return []

        logger.info(f"正在分析 {len(summaries)} 个数据集之间的关联关系...")

        # 1. 提取每个数据集的关键语义特征
        datasets_meta = []
        for s in summaries:
            meta = {
                "variable_name": s.get("variable_name"),
                "dataset_type": s.get("semantic_analysis", {}).get("dataset_type"),
                "semantic_tags": s.get("semantic_analysis", {}).get("semantic_tags"),
                "description": s.get("semantic_analysis", {}).get("description")
            }
            datasets_meta.append(meta)

        # 2. 构建 Prompt 让 LLM 识别关联路径
        system_prompt = """
        你是一位数据仓库架构师。你需要分析多个数据集的元数据，找出它们如何相互关联。
        关联类型包括：
        1. ID_LINK: 通过共同的 ID 字段关联（如 LocationID, zone_id）。
        2. SPATIAL_LINK: 一个数据集包含点坐标(ST_LAT/LON)，另一个包含区域边界(ST_GEO)，可以通过空间包含关系(Point-in-Polygon)关联。
        3. ATTRIBUTE_LINK: 通过相同的分类字段关联（如 district_name）。
        """

        user_prompt = f"""
        待分析的数据集元数据:
        {json.dumps(datasets_meta, indent=2, ensure_ascii=False)}

        请分析并列出所有可能的关联路径。输出格式为 JSON 数组：
        [
          {{
            "source": "变量A",
            "target": "变量B",
            "type": "ID_LINK | SPATIAL_LINK | ATTRIBUTE_LINK",
            "join_on": ["字段1", "字段2"],  # 如果是空间关联，此处可描述逻辑
            "strength": 0.0-1.0,         # 关联的可信度
            "reason": "为什么认为它们有关联"
          }}
        ]
        """

        try:
            relations = self.llm.query_json(prompt=user_prompt, system_prompt=system_prompt)
            logger.info(f"✅ 识别到 {len(relations)} 条潜在关联路径。")
            return relations
        except Exception as e:
            logger.error(f"关系映射失败: {e}")
            return []

    def get_drilldown_hint(self, source_var: str, relations: List[Dict[str, Any]]) -> str:
        """
        根据当前操作的变量，提取用于辅助 CodeGenerator 的钻取提示。
        """
        relevant = [r for r in relations if r['source'] == source_var or r['target'] == source_var]
        if not relevant:
            return ""

        hint = "检测到数据集关联，可用于钻取分析：\n"
        for r in relevant:
            hint += f"- 可通过 {r['type']} 与 `{r['target'] if r['source'] == source_var else r['source']}` 关联 (依据: {r['join_on']})\n"
        return hint