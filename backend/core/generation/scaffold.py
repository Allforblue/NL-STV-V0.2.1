from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union
from enum import Enum

from typing import List, Dict, Any
import json


class STChartScaffold:
    """
    Spatio-Temporal Chart Scaffold (V4.5 - Strict Animation Control)

    整合特性：
    1. 基础 GIS/绘图防崩溃规则。
    2. 对数色阶处理 (Log Scale) 优化长尾数据可视化。
    3. 强制去标题 (No Internal Titles)，实现 UI 统一渲染。
    4. 时间序列专家准则：支持自动重采样、时段分析与趋势绘图。
    5. [新增] 全局视觉主题：统一 Plotly 配色方案与模版样式。
    6. [修复] 动态地图播放卡死问题：强制 [时间, ID] 双重排序与 ID 类型物理对齐。
    7. [强制] UI 同步：彻底隐藏 Plotly 内建播放控件。
    """

    def __init__(self):
        # 通用指令集 (严格保留并增强)
        self.common_gis_instructions = """
        [CRITICAL RULES - READ CAREFULLY]
        1. **NO DISK I/O**: `data_context` ALREADY contains loaded objects. 
           - ✅ Correct: `df = data_context['df_variable_name']`
           - ❌ Wrong: `gdf = gpd.read_file(...)`

        2. **VARIABLE NAMES**: 
           - USE EXACTLY the variable names provided in the Metadata Context.
           - DO NOT assume variable names (e.g., do not change `df_zones` to `gdf_zones`).
           - Always check `data_context.keys()` logic if unsure.

        3. **IMPORTS**: You MUST explicitly import ALL libraries: `import pandas as pd`, `import geopandas as gpd`, `import plotly.express as px`, `import numpy as np`, `import json`.

        4. **DATA CLEANING (Anti-Crash)**:
           - **Isolation**: Always use `.copy()` when fetching from `data_context` to prevent cross-component data pollution.
           - Before plotting, DROP NaNs: `df = df.dropna(subset=['col_x', 'col_y'])`.
           - For Bar/Line/Pie: FILTER out <=0 values if log scale or ratio is used.

        5. **MAP GEOMETRY (Choropleth & Scatter)**: 
           - Mapbox only supports WGS84. Ensure `gdf = gdf.to_crs(epsg=4326)`.
           - For Choropleth: `Ensure gdf.reset_index(drop=True)` after any join or filter.

        6. **BAR CHART LAYOUT**: 
           - For horizontal bars, construct a UNIQUE label to avoid stacking.
           - Layout: `fig.update_layout(margin=dict(l=150), yaxis=dict(automargin=True))`

        7. **RETURN FORMAT**: 
           - Function: `def get_dashboard_data(data_context):`.
           - Return a `dict` where keys are Component IDs and values are Figures/DataFrames.

        8. **INSIGHT DATA**: 
           - For 'insight' components, NEVER return a raw DataFrame. You must return a dict with the structure: {'summary': 'short_text', 'detail': 'long_text', 'evidence': df.to_dict()}.

        9. **MAP TOOLTIPS**:
           - Always set `hover_name` to the descriptive name of the area (e.g., 'Zone', 'Borough') to show real info. No "index=..." or raw "ID=..." in tooltips.

       10. **LARGE SCALE DATA (Performance & Memory Guard)**:
            - For Mapbox Scatter, if `len(df) > 50000`, you MUST use `df = df.sample(50000)`.
            - **CRITICAL (MemoryError Fix)**: For animations, NEVER include the 'geometry' column in the DataFrame passed to `animation_frame`. Pass a separate static GeoJSON dict instead.

        11. **NO INTERNAL CONTROLS (UI HYGIENE)**:
            - ❌ NEVER set `title=...` inside Plotly functions. UI handles titles externally.
            - ❌ For ANY animated component, you MUST hide internal Plotly controls: `fig.update_layout(updatemenus=[dict(visible=False)], sliders=[dict(visible=False)])`. This ensures the UI timeline player is the sole controller.

        12. **TIME SERIES HANDLING**:
            - **Conversion**: Always use `df['time_col'] = pd.to_datetime(df['time_col'], errors='coerce')`.
            - **Aggregation**: Use `df.set_index('time_col').resample(time_bucket).size()` for trends. 
            - **Filling Gaps**: Use `.fillna(0)` to ensure lines connect properly in charts.
            - **Cyclic Patterns**: Use `df['time_col'].dt.hour` or `.dt.dayofweek` for periodic analysis.

        13. **VISUAL STYLE & THEME (NEW)**:
            - **Template**: Always use `template='plotly_white'` for a clean, modern look.
            - **Continuous Scale**: For maps and heatmaps, use `color_continuous_scale='Viridis'`.
            - **Discrete Sequence**: For categorical charts (Pie/Bar), use `color_discrete_sequence=px.colors.qualitative.Prism`.

        14. **INTERACTION ANCHORS (IMPORTANT)**:
            - You MUST include the comment `# [INTERACTION_HOOK]` at the very beginning of the logic block for each component.

        15. **PLOTLY API COMPATIBILITY**: 
            - NEVER use `titleside` in `colorbar`. Use `title={'text': '...', 'side': 'top'}` instead.
            - DO NOT use `margin_t`, use `margin=dict(t=...)`.

        16. **JOIN TYPE ALIGNMENT**:
            - When merging tables, verify that the join keys are of the same data type. Convert to string using .astype(str) before merging.

        17. **DYNAMIC ANIMATION & STABILITY (STRICT GUIDELINES)**:
            - **ID Type Sync (MANDATORY)**: Before creating GeoJSON, you MUST cast the ID column in the GDF to string: `gdf['ID'] = gdf['ID'].astype(str)`. Then `json.loads(gdf.to_json())`. This prevents mismatch between data(str) and geometry(int).
            - **Zero-Padding**: Ensure all IDs exist in every time frame (use a Cartesian product) and fill missing values with 0.
            - **Attribute Backfilling**: Merge descriptive names (e.g., 'Zone') back to the padded DataFrame for tooltips.
            - **Dual Sorting (MANDATORY)**: ALWAYS sort the final DataFrame by `[time_frame, id_col]`. If you only sort by time, the Plotly WebGL engine will freeze or glitch.
        
        18. **NO HARDCODED FILTERING (CRITICAL)**:
            - ❌ NEVER filter the dataframe to a specific hardcoded date like `df[df['date'] == '2025-01-01']` unless the user explicitly asks for exactly one single day. 
            - For dynamic animations, process the ENTIRE dataset provided in `data_context`. The timeline slider will naturally handle the temporal progression.
        
        19. **HOVER DATA PERSISTENCE (CRITICAL)**:
            - In animated maps, Plotly often drops hover information in subsequent frames. 
            - ❌ You MUST explicitly include the animation frame column (e.g., 'hour_frame') in the `hover_data` parameter of the `px` function to ensure the tooltip updates during playback.
            - Example: `hover_data={'hour_frame': True, 'count': True, ...}`
        """

    def get_system_prompt(self, context_str: str) -> str:
        """
        构建系统提示词。
        """

        prompt = f"""
        You are an Expert Python Spatio-Temporal Data Scientist.
        Your task is to complete the `get_dashboard_data(data_context)` function using `plotly.express`.
        
        === MODE SELECTION RULE ===
        - By default, use **Recipe A** for maps and **Recipe B/C/D/E/F** for charts (STATIC).
        - ONLY use **Recipe G** if the component is explicitly marked as [ANIMATED] in the user prompt. 
        - DO NOT hallucinate animation frames for static queries.

        === DATA METADATA (Context) ===
        {context_str}

        === EXPERT INSTRUCTIONS ===
        {self.common_gis_instructions}

        === RECIPES (The "Best Practice" Patterns) ===

        [Recipe A: Choropleth Map with Log Scaling]
        Target: "Spatial distribution with concentration"
        Code:
        ```python
        # [INTERACTION_HOOK]
        gdf_map = data_context['df_taxi_zones'].copy().to_crs(epsg=4326)
        df_stats = data_context['df_counts'].copy()

        # Step 0: Ensure ID is string for both mapping and GeoJSON
        gdf_map['LocationID'] = gdf_map['LocationID'].astype(str)
        df_stats['LocationID'] = df_stats['LocationID'].astype(str)

        gdf_map = gdf_map.merge(df_stats, on='LocationID', how='left')
        gdf_map['actual_count'] = gdf_map['order_count'].fillna(0)
        gdf_map['color_score'] = np.log1p(gdf_map['actual_count'])

        fig = px.choropleth_mapbox(
            gdf_map, geojson=json.loads(gdf_map.to_json()), locations='LocationID',
            featureidkey="properties.LocationID",
            color='color_score', hover_name='Zone', # Show Zone name in hover
            mapbox_style="carto-darkmatter", color_continuous_scale="Viridis", 
            template="plotly_dark", zoom=10, opacity=0.7
        )
        ```

        [Recipe B: Scatter Mapbox]
        Code:
        ```python
        # [INTERACTION_HOOK]
        df = data_context['df_variable_name'].copy()
        if len(df) > 50000: 
            df = df.sample(50000, random_state=42)
        df = df.dropna(subset=['lat', 'lon'])

        fig = px.scatter_mapbox(
            df, lat='lat', lon='lon', color='val', size='val', 
            color_continuous_scale="Plasma", template="plotly_dark",
            mapbox_style="carto-darkmatter", size_max=15
        )
        ```

        [Recipe C: Bar Chart Rankings]
        Code:
        ```python
        # [INTERACTION_HOOK]
        df = data_context['df_variable_name'].copy()
        df_agg = df.groupby('Category')['val'].sum().reset_index().sort_values('val', ascending=True).tail(10)

        fig = px.bar(
            df_agg, x='val', y='Category', orientation='h',
            color='Category', color_discrete_sequence=px.colors.qualitative.Prism,
            template="plotly_dark"
        )
        ```

        [Recipe D: Smart Pie Chart]
        Code:
        ```python
        # [INTERACTION_HOOK]
        df = data_context['df_variable_name'].copy()
        df_pie = df['Borough'].value_counts().reset_index().head(8)

        fig = px.pie(
            df_pie, names='index', values='Borough', hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Prism,
            template="plotly_dark"
        )
        ```

        [Recipe E: Time-Series Trend Line Chart]
        Target: "Analyze trends over time"
        Code:
        ```python
        # [INTERACTION_HOOK]
        df = data_context['df_variable_name'].copy()
        df['time'] = pd.to_datetime(df['pickup_datetime'], errors='coerce')
        df = df.dropna(subset=['time'])

        df_trend = df.set_index('time').resample('1H').size().reset_index(name='count')
        df_trend = df_trend.fillna(0)

        fig = px.line(
            df_trend, x='time', y='count', template="plotly_dark"
        )
        fig.update_traces(mode='lines+markers', line=dict(width=3))
        ```

        [Recipe F: Periodicity Analysis (Hour/Day Heatmap)]
        Code:
        ```python
        # [INTERACTION_HOOK]
        df = data_context['df_variable_name'].copy()
        df['hour'] = pd.to_datetime(df['time'], errors='coerce').dt.hour
        df_hour = df.groupby('hour').size().reset_index(name='count')
        fig = px.bar(
            df_hour, x='hour', y='count', template="plotly_dark"
        ) 
        ```

        [Recipe G: Dynamic/Animated Evolution Map (Strict Stability)]
        Target: "Smooth animation, forced string IDs, and dual sorting"
        Code:
        ```python
        # [INTERACTION_HOOK]
        gdf_zones = data_context['df_zones'].copy().to_crs(epsg=4326)
        df_trips = data_context['df_trips'].copy()

        # 1. MANDATORY: Cast ID to STR BEFORE to_json (Ensures matching)
        gdf_zones['LocationID'] = gdf_zones['LocationID'].astype(str)
        geo_json = json.loads(gdf_zones.to_json())

        # 2. Extract Name Mapping (Backfilling)
        name_map = gdf_zones[['LocationID', 'Zone']].drop_duplicates()

        # 3. Time Grid & Zero-Padding
        df_trips['time_frame'] = pd.to_datetime(df_trips['time']).dt.strftime('%H:00')
        times = sorted(df_trips['time_frame'].unique())
        ids = gdf_zones['LocationID'].unique()

        grid = pd.MultiIndex.from_product([ids, times], names=['LocationID', 'time_frame']).to_frame(index=False)
        grid['LocationID'] = grid['LocationID'].astype(str)

        # 4. Aggregation & Backfilling
        df_agg = df_trips.groupby(['LocationID', 'time_frame']).size().reset_index(name='count')
        df_agg['LocationID'] = df_agg['LocationID'].astype(str)

        df_anim = pd.merge(grid, df_agg, on=['LocationID', 'time_frame'], how='left').fillna(0)
        df_anim = pd.merge(df_anim, name_map, on='LocationID', how='left') # Backfill 'Zone' column

        # 5. MANDATORY DUAL SORT: Essential for Plotly Animation Engine
        df_anim = df_anim.sort_values(['time_frame', 'LocationID'])

        # 6. Plot (Notice: Internal controls hidden via update_layout)
        fig = px.choropleth_mapbox(
            df_anim, geojson=geo_json, locations='LocationID', featureidkey="properties.LocationID",
            color='count', animation_frame='time_frame', animation_group='LocationID',
            hover_name='Zone', # Informative tooltips
            mapbox_style="carto-darkmatter", zoom=10, opacity=0.7, template="plotly_dark"
        )

        # 7. MANDATORY UI SYNC: Hide internal controls
        fig.update_layout(updatemenus=[dict(visible=False)], sliders=[dict(visible=False)])
        ```

        === FINAL TASK ===
        1. Analyze User Query and components.
        2. Choose Recipe (Recipe G for spatio-temporal animations).
        3. STRICTLY NO internal `title=...`.
        4. For animations (Recipe G): 
           - MUST cast ID to string in GeoDataFrame BEFORE creating GeoJSON.
           - DUAL SORT by [time_frame, ID] to prevent animation freezing.
           - HIDE internal controls (updatemenus/sliders) to avoid UI conflicts.
        5. Always backfill descriptive names (like 'Zone') for animations to ensure clean tooltips.
        6. Return {{ 'comp_id': fig/df, ... }}.
        """
        return prompt