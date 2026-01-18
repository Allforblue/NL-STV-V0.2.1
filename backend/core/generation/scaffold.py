from typing import List, Dict, Any
import json


class STChartScaffold:
    """
    Spatio-Temporal Chart Scaffold (V2 - Dashboard Ready)
    管理时空可视化的 Prompt 模板、专家规则和代码食谱 (Recipes)。
    """

    def __init__(self):
        # 1. 通用 GIS 与 绘图指令 (融合了之前的稳定规则和新的修复逻辑)
        self.common_gis_instructions = """
        [CRITICAL RULES - READ CAREFULLY]
        1. **NO DISK I/O**: `data_context` ALREADY contains loaded objects. 
           - ❌ `pd.read_csv(...)` 
           - ✅ `df = data_context['df_variable_name']`

        2. **IMPORTS**: You MUST explicitly import ALL libraries used.
           - `import pandas as pd`, `import geopandas as gpd`
           - `import plotly.express as px`, `import numpy as np`
           - `import json`, `import random`
           - `from shapely.geometry import Point, Polygon`

        3. **DATA CLEANING (Anti-Crash)**:
           - Before plotting, DROP NaNs: `df = df.dropna(subset=['col_x', 'col_y'])`.
           - For Bar/Line/Pie: FILTER out <=0 values if log scale or ratio is used: `df = df[df['value'] > 0]`.
           - This prevents frontend "Infinity" errors.

        4. **MAP GEOMETRY (Choropleth)**: 
           - Use `px.choropleth_mapbox`.
           - **CRITICAL**: Ensure data alignment!
             ```python
             gdf = gdf.to_crs(epsg=4326) # Must be WGS84
             gdf = gdf.reset_index(drop=True) # Reset index to 0,1,2...
             fig = px.choropleth_mapbox(
                 gdf, geojson=gdf.geometry, 
                 locations=gdf.index, # Match by index
                 ...
             )
             ```

        5. **BAR CHART LAYOUT**: 
           - For horizontal bars (`orientation='h'`), construct a UNIQUE y-axis label to avoid stacking.
           - Example: `df['label'] = df['Zone'] + " (" + df['ID'].astype(str) + ")"`
           - Layout: `fig.update_layout(margin=dict(l=150), yaxis=dict(automargin=True))`

        6. **RETURN FORMAT**: 
           - Function must be `def get_dashboard_data(data_context):`.
           - Return a `dict` where keys are Component IDs (e.g., 'map_1') and values are Figures/DataFrames.
           
        7. **INSIGHT DATA (CRITICAL)**: 
           - For the component with `type='insight'`, you MUST return a small `pd.DataFrame` containing the key metrics derived from your analysis.
           - DO NOT return a string/text. Return the DATA so the backend can generate the text.
           - Example:
             ```python
             df_insight = pd.DataFrame({
                 "Metric": ["Top Zone", "Total Orders"],
                 "Value": ["JFK", 15000]
             })
             return { "map_1": fig, "insight_1": df_insight }
             ```
        
        8. **MAP TOOLTIPS**:
           - Always set `hover_name='Zone'` (or the name column).
           - Always set `hover_data=['Borough', 'value_column']`.
           - Do not let the map show "index=..." in the tooltip.
        """

    def get_system_prompt(self, context_str: str) -> str:
        """构建包含“食谱”的系统提示词"""

        prompt = f"""
        You are an expert Python GIS Data Analyst. 
        Your task is to complete the `get_dashboard_data(data_context)` function to visualize data using `plotly.express`.

        === DATA ENVIRONMENT ===
        {context_str}

        {self.common_gis_instructions}

        === RECIPES (Reference Patterns) ===

        [Recipe A: Choropleth Map / Region Heatmap]
        Target: "Show value per zone on map"
        Strategy: GroupBy -> Merge with GeoDataFrame -> Reset Index -> Plot
        Code:
        ```python
        # ... (Merge logic) ...
        # Ensure 'Zone' and 'Borough' columns exist in gdf_map for tooltip
        gdf_map = gdf_zones.merge(df_agg, on='LocationID', how='left')
        gdf_map = gdf_map.to_crs(epsg=4326)
        gdf_map = gdf_map.reset_index(drop=True) 
        
        fig = px.choropleth_mapbox(
            gdf_map, 
            geojson=gdf_map.geometry, 
            locations=gdf_map.index,
            color='value_col', 
            # [CRITICAL] Set hover info to show real names, not index
            hover_name='Zone', 
            hover_data=['Borough', 'value_col'],
            mapbox_style="carto-positron", 
            zoom=10, 
            opacity=0.6
        )
        ```

        [Recipe B: Scatter Mapbox]
        Target: "Show points (pickups/dropoffs)"
        Strategy: Sample (if large) -> Plot
        Code:
        ```python
        if len(df) > 10000: df = df.sample(10000)
        fig = px.scatter_mapbox(df, lat='lat', lon='lon', color='val', size='val', mapbox_style="carto-positron")
        ```

        [Recipe C: Bar Chart (Rankings)]
        Target: "Top 10 Zones by Orders"
        Strategy: GroupBy -> Sort -> Head(10) -> Unique Label -> Plot
        Code:
        ```python
        df_agg = df.groupby('Zone')['count'].sum().reset_index().sort_values('count', ascending=True).tail(10)
        fig = px.bar(df_agg, x='count', y='Zone', orientation='h')
        fig.update_yaxes(type='category') # Prevent hiding labels
        fig.update_layout(margin=dict(l=150))
        ```

        [Recipe D: Pie Chart (Composition)]
        Target: "Distribution of Payment Types" or "Share of Boroughs"
        Strategy: GroupBy -> Sort -> Head(Limit Slices) -> Pie
        Code:
        ```python
        # Limit to top 8 slices, group others to 'Other' (optional logic, but simple top n is safer)
        df_pie = df['Borough'].value_counts().reset_index().head(8)
        df_pie.columns = ['label', 'value']

        fig = px.pie(
            df_pie, 
            names='label', 
            values='value', 
            title='Distribution of Boroughs',
            hole=0.4 # Donut chart looks better
        )
        fig.update_traces(textposition='inside', textinfo='percent+label')
        ```

        === INSTRUCTIONS ===
        1. Analyze the `component_plans` in the User Prompt.
        2. Select the best Recipe for each component type (Map->A/B, Chart->C/D).
        3. Write the COMPLETE code.
        """
        return prompt