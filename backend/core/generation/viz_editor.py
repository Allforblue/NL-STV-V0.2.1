import logging
import re
import json
from typing import Dict, Any, List, Optional
from core.llm.AI_client import AIClient
from core.schemas.interaction import InteractionTriggerType

logger = logging.getLogger(__name__)


class VizEditor:
    """
    可视化编辑器 (V3.4 级联过滤版)：
    1. [Cascade Filter] 实现从 地理表(BBox) -> ID列表 -> 业务表(ID) 的级联过滤。
    2. [Auto Focus] 保持自动对焦逻辑。
    3. [Fix] 彻底解决“地图变了但统计图没变”的问题。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    def _clean_previous_injections(self, code: str) -> str:
        code = re.sub(r"\s*# \[FAST_FILTER_START\].*?# \[FAST_FILTER_END\]\n", "", code, flags=re.DOTALL)
        code = re.sub(r"\s*# \[AUTOFOCUS_START\].*?# \[AUTOFOCUS_END\]\n", "", code, flags=re.DOTALL)
        code = code.replace("_final_results = ", "")
        code = code.replace("return _final_results", "")
        return code

    def _inject_v2_logic(self, code: str, payload: Any, summaries: List[Dict[str, Any]], links: List[Any]) -> str:
        filter_lines = []

        if payload.bbox and len(payload.bbox) == 4:
            ln_min, lt_min, ln_max, lt_max = payload.bbox

            # 1. 第一阶段：识别地理表和潜在的关联 ID 列
            geo_vars = []
            valid_id_cols = set()  # 存储可能用于关联的 ID 列名 (如 LocationID, zone_id)

            for s in summaries:
                var_name = s['variable_name']
                is_geo = s.get('is_geospatial', False) or s.get('basic_stats', {}).get('is_geospatial', False)

                # 尝试从语义元数据中寻找 ID 列
                col_meta = s.get('semantic_analysis', {}).get('column_metadata', {})
                id_col = next((c for c, m in col_meta.items() if m.get('semantic_tag') in ['ST_LOC_ID', 'ID_KEY']),
                              None)

                # 简单的启发式备选：如果列名包含 'id' 且unique值较多，也可能是关联键
                if not id_col:
                    cols = s.get('column_stats', {}).keys()
                    candidates = [c for c in cols if 'id' in c.lower() and 'transaction' not in c.lower()]
                    if candidates: id_col = candidates[0]

                if is_geo:
                    geo_vars.append({'name': var_name, 'id_col': id_col})
                    if id_col: valid_id_cols.add(id_col)

            # 2. 第二阶段：生成过滤代码
            filter_lines.append(f"    # --- Cascading Spatial Filter ---")
            filter_lines.append(f"    _valid_ids = set()")

            # A. 先过滤地理表，并收集剩下的 ID
            for g in geo_vars:
                v = g['name']
                id_c = g['id_col']
                filter_lines.append(f"    if '{v}' in data_context:")
                filter_lines.append(f"        _gdf = data_context['{v}'].copy()")
                filter_lines.append(
                    f"        if hasattr(_gdf, 'crs') and str(_gdf.crs) != 'EPSG:4326': _gdf = _gdf.to_crs(epsg=4326)")
                # BBox 过滤
                filter_lines.append(f"        _gdf = _gdf.cx[{ln_min}:{ln_max}, {lt_min}:{lt_max}]")
                filter_lines.append(f"        data_context['{v}'] = _gdf")

                # 收集 ID 用于级联
                if id_c:
                    filter_lines.append(f"        if '{id_c}' in _gdf.columns:")
                    filter_lines.append(f"            _valid_ids.update(_gdf['{id_c}'].dropna().unique().tolist())")
                    filter_lines.append(f"        elif _gdf.index.name == '{id_c}':")
                    filter_lines.append(f"            _valid_ids.update(_gdf.index.tolist())")

            # B. 再过滤非地理表 (业务表)，使用 ID 匹配
            for s in summaries:
                v = s['variable_name']
                # 跳过已经处理过的地理表
                if any(g['name'] == v for g in geo_vars): continue

                # 寻找该表中的关联 ID 列
                cols = s.get('column_stats', {}).keys()
                # 这里的逻辑是：如果这个表里有一个列名，和我们在地理表中找到的 ID 列名一样（比如都叫 LocationID），那就过滤它
                match_col = next((c for c in cols if c in valid_id_cols), None)

                # 模糊匹配：如果没完全匹配，尝试找由 'location', 'zone' 组成的列
                if not match_col:
                    match_col = next(
                        (c for c in cols if any(k in c.lower() for k in ['locationid', 'zone', 'pulocation'])), None)

                if match_col:
                    filter_lines.append(f"    if '{v}' in data_context and _valid_ids:")
                    filter_lines.append(f"        _df_biz = data_context['{v}'].copy()")
                    # 确保类型一致 (转字符串对比最安全)
                    filter_lines.append(f"        if '{match_col}' in _df_biz.columns:")
                    filter_lines.append(f"            # Cascade Filter on {match_col}")
                    filter_lines.append(
                        f"            data_context['{v}'] = _df_biz[_df_biz['{match_col}'].isin(_valid_ids)]")
                    filter_lines.append(
                        f"            print(f'[CASCADE] {v} filtered by IDs from {{len(_df_biz)}} to {{len(data_context[\"{v}\"])}}')")

        if not filter_lines: return code

        # 3. 注入代码 (函数头)
        filter_block = "\n    # [FAST_FILTER_START]\n" + "\n".join(filter_lines) + "\n    # [FAST_FILTER_END]\n"
        code = re.sub(r"(def get_dashboard_data\(data_context\):)", r"\1" + filter_block, code)

        # 4. 注入对焦补丁
        autofocus_logic = """
    # [AUTOFOCUS_START]
    for _id, _obj in _final_results.items():
        if hasattr(_obj, 'layout') and 'mapbox' in _obj.layout:
            _obj.layout.mapbox.center = None
            _obj.layout.mapbox.zoom = None
            _obj.update_layout(mapbox_style="carto-darkmatter")
    return _final_results
    # [AUTOFOCUS_END]
        """

        if "return " in code:
            parts = code.rsplit("return ", 1)
            code = parts[0] + "_final_results = " + parts[1].strip() + autofocus_logic

        return code

    # edit_dashboard_code 等方法保持不变...
    async def edit_dashboard_code(self, original_code: str, payload: Any, summaries: List[Dict[str, Any]],
                                  links: List[Any] = None) -> str:
        clean_code = self._clean_previous_injections(original_code)
        if payload.trigger_type == InteractionTriggerType.UI_ACTION and not payload.force_new:
            return self._inject_v2_logic(clean_code, payload, summaries, links)

        system_prompt = self._get_editor_prompt(clean_code, summaries)
        user_prompt = f"=== 交互描述 ===\n触发源: {payload.trigger_type}\n指令: {payload.query}\n\n只输出 Python 代码。"

        try:
            raw_res = await self.llm.chat_async(
                [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}])
            return self._clean_markdown(raw_res)
        except Exception as e:
            logger.error(f"LLM Edit Failed: {e}")
            return original_code

    def _clean_markdown(self, text: str) -> str:
        if not text: return ""
        text = text.strip()
        text = re.sub(r"^```(python)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        return text.strip()

    def _get_editor_prompt(self, original_code: str, summaries: List[Dict[str, Any]]) -> str:
        return "You are a Data Engineer. Modify code based on interaction."