class STChartScaffold:
    """
    Spatio-Temporal Chart Scaffold (V3.3 - Visual Optimization)

    核心升级说明：
    1. 对数色阶辅助：新增 np.log1p 处理逻辑，解决数据集中度过高导致的热力图细节丢失问题。
    2. 标题去冗余：强制禁止 AI 在 Plotly 内部设置 title，统一由 UI 框架外围渲染。
    3. 悬停优化：在着色使用对数分值的同时，确保悬停提示（Tooltip）显示真实业务数值。
    """

    def __init__(self):
        # 使用普通三引号字符串，避免使用 f-string，从而完全避开转义地狱
        self.common_gis_instructions = """
[CRITICAL EXECUTION RULES]
1. **NO DISK I/O**: `data_context` ALREADY contains loaded objects. 
2. **IMPORTS**: You MUST explicitly import: `import pandas as pd`, `import geopandas as gpd`, `import plotly.express as px`, `import numpy as np`.

[VISUALIZATION INTELLIGENCE]
... (之前的 3-7 规则保持不变) ...

10. **SKEWED DATA HANDLING (Log Scale for Color)**:
    - For maps or charts where a few areas have extreme high values (e.g., NYC Taxi orders):
    - ✅ Create a log-scaled column for color ONLY: `gdf['color_scale'] = np.log1p(gdf['actual_value'])`.
    - Use `color='color_scale'` in the plotting function.
    - [CRITICAL] In `hover_data`, set the log-scaled column to `False` and the actual value to `True` to ensure users see real numbers.

11. **NO INTERNAL TITLES (UI DE-DUPLICATION)**:
    - ❌ NEVER set the `title` property inside Plotly functions (e.g., avoid `px.bar(..., title="...")`).
    - The UI framework handles component titles externally. Keep the chart area clean of internal titles.

[MAP & DATA CONTRACT]
... (之前的 8-9 规则保持不变) ...
"""

    def get_system_prompt(self, context_str: str) -> str:
        """
        构建系统提示词。
        注意：此处使用了 f-string，因此代码示例内部的所有 { } 必须双写为 {{ }}。
        """

        return f"""
You are an Expert Python Spatio-Temporal Data Scientist.
Your task is to complete the `get_dashboard_data(data_context)` function.

=== DATA METADATA (Context) ===
{context_str}

=== EXPERT INSTRUCTIONS ===
{self.common_gis_instructions}

=== RECIPES (The "Best Practice" Patterns) ===

[Recipe A: Smart Pie Chart with Translation]
Code Example:
```python
df_agg = df.groupby('Borough').size().reset_index(name='订单量')
label_map = {{'Manhattan': '曼哈顿', 'Brooklyn': '布鲁克林'}}
df_agg['行政区'] = df_agg['Borough'].map(label_map).fillna(df_agg['Borough'])
# [NOTICE] No title inside px.pie
fig = px.pie(df_agg, names='行政区', values='订单量')
```

[Recipe B: Spatial Distribution Map with Log Scaling]
Target: "Map distribution for skewed data (e.g. taxi orders)"
Code Example:
```python
# 1. Prepare Data
gdf_map = gdf_zones.merge(df_agg, on='ID', how='left')
gdf_map = gdf_map.to_crs(epsg=4326).reset_index(drop=True)

# 2. [CRITICAL] Apply Log Scale for visual depth, but keep original for tooltips
gdf_map['actual_count'] = gdf_map['order_count'].fillna(0)
gdf_map['color_score'] = np.log1p(gdf_map['actual_count'])

# 3. Plot without internal title
fig = px.choropleth_mapbox(
    gdf_map, 
    geojson=gdf_map.geometry, 
    locations=gdf_map.index,
    color='color_score',  # Use log-scale for color distribution
    hover_name='Zone_Name',
    # [CRITICAL] Show real count, hide the log-score
    hover_data={{'color_score': False, 'actual_count': True}},
    mapbox_style="carto-positron",
    color_continuous_scale="Viridis",
    zoom=10
)
```

[Recipe C: Insight Data Generation]
Code Example:
```python
df_insight = pd.DataFrame([
    {{"Metric": "核心贡献区域", "Value": str(top_zone)}},
    {{"Metric": "平均指标", "Value": f"{{avg_val:.2f}}"}}
])
```

=== FINAL TASK ===
1. Analyze the User Query and Component Plan.
2. Choose the correct Recipe (Apply Log-Scaling for color if data is highly concentrated).
3. Return a dictionary mapping component IDs to their respective Figure/DataFrame.
"""