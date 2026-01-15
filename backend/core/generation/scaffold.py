from typing import List, Dict, Any


class STChartScaffold:
    """
    Spatio-Temporal Chart Scaffold
    管理时空可视化的 Prompt 模板、专家规则和代码食谱 (Recipes)。
    """

    def __init__(self):
        # 通用 GIS 处理指令 (经过强化和去重)
        self.common_gis_instructions = """
        [CRITICAL RULES - READ CAREFULLY]
        1. **NO DISK I/O**: `data_context` ALREADY contains loaded DataFrame/GeoDataFrame OBJECTS. 
           - NEVER write `pd.read_csv(...)` or `gpd.read_file(...)`.
           - CORRECT USAGE: `df = data_context['df_variable_name']`.

        2. **CASE SENSITIVITY**: Pandas is case-sensitive! 
           - NYC Data usually uses capitalized names: 'Zone', 'Borough', 'LocationID'.
           - ERROR: 'zone' -> CORRECT: 'Zone'.
           - Check the 'AVAILABLE DATASETS' list for exact column names.

        3. **GEOMETRY SOURCE**: 
           - To plot a map, you MUST use the GeoDataFrame (loaded from Shapefile), NOT the lookup CSV.
           - The lookup CSV (e.g., taxi_zone_lookup) has NO geometry column.
           - Logic: Aggregate data -> Merge into GeoDataFrame -> Plot GeoDataFrame.

        4. **NO MOCK DATA / NO EXTRA CODE**: 
           - DO NOT include `data_context = ...` or example usage at the bottom of the script.
           - ONLY define the `def plot(data_context):` function.
           - The system will call the function automatically.

        5. **Coordinate System**: Plotly Mapbox REQUIRES WGS84 (EPSG:4326). 
           - EXECUTE: `gdf = gdf.to_crs(epsg=4326)` BEFORE plotting.

        6. **Map Matching**: 
           - When using `px.choropleth_mapbox`, Plotly matches `locations` against the GeoJSON feature IDs.
           - CRITICAL STEP: Set the matching column as index: `gdf = gdf.set_index('LocationID')`.
           - Then use: `locations=gdf.index`.

        7. **Map Style**: ALWAYS set `mapbox_style="carto-positron"` (no token needed).

        8. **ANIMATION SORTING (CRITICAL)**: 
           - Sampling (`df.sample()`) shuffles data!
           - You MUST sort the dataframe by the animation column (`sort_values()`) AFTER sampling and IMMEDIATELY BEFORE plotting.
           - Otherwise, the timeline will be chaotic.
        """

    def get_template(self, library: str = "plotly") -> str:
        """返回 Python 代码的骨架 (Skeleton)"""
        if library == "plotly":
            return """
import plotly.express as px
import pandas as pd
import geopandas as gpd

def plot(data_context: dict):
    # 1. Extract DataFrames (Use exact keys from Available Datasets)
    # Example: df_trips = data_context['df_trips']

    # <stub> 
    # (Write your data processing and plotting code here)

    return fig
"""
        return ""

    def get_system_prompt(self, summaries: List[Dict[str, Any]]) -> str:
        """构建包含“食谱”的系统提示词"""

        # 1. 构建数据上下文描述
        context_descriptions = []
        for summary in summaries:
            var_name = summary.get('variable_name', 'df')
            file_name = summary.get('file_info', {}).get('name', 'unknown')

            # 提取列信息
            cols = []
            stats = summary.get("basic_stats", {}).get("column_stats", {})
            tags = summary.get("semantic_analysis", {}).get("semantic_tags", {})
            for col, info in stats.items():
                tag = tags.get(col, "UNKNOWN")
                cols.append(f"  - {col} ({info.get('dtype')}, {tag})")

            desc = f"DataFrame `{var_name}` (Source: {file_name}):\n" + "\n".join(cols)
            context_descriptions.append(desc)

        full_context = "\n\n".join(context_descriptions)

        # 2. 构建 Prompt
        prompt = f"""
        You are an expert Python GIS Data Analyst. 
        Your task is to complete the `plot(data_context)` function to visualize data using `plotly.express`.

        === AVAILABLE DATASETS (in `data_context`) ===
        {full_context}

        {self.common_gis_instructions}

        === RECIPES (Reference Patterns) ===

        [Recipe A: Choropleth Map / Region Heatmap]
        Target: "Show total value per zone"
        Strategy: GroupBy -> Merge with Shapefile -> to_crs(4326) -> set_index -> Choropleth
        Code:
        ```python
        def plot(data_context):
            # 1. Extract (Use keys from Available Datasets)
            df_trips = data_context['df_trips']
            df_zones = data_context['df_zones'] # Expecting GeoDataFrame

            # 2. Aggregate
            # Note: Using LocationID for grouping is safer than names
            df_agg = df_trips.groupby('PULocationID')['fare_amount'].sum().reset_index()

            # 3. Merge (Left merge on GeoDataFrame to keep geometry)
            # Ensure columns match (e.g. LocationID vs PULocationID)
            df_map = df_zones.merge(df_agg, left_on='LocationID', right_on='PULocationID', how='left')

            # 4. Transform CRS (CRITICAL!)
            df_map = df_map.to_crs(epsg=4326)

            # 5. Set Index for Map Matching (CRITICAL!)
            # Plotly uses the index to match geojson features
            df_map = df_map.set_index('LocationID')

            # 6. Plot
            fig = px.choropleth_mapbox(
                df_map, 
                geojson=df_map.geometry, 
                locations=df_map.index, # Use index
                color='fare_amount', 
                mapbox_style="carto-positron", 
                center={{"lat": 40.7, "lon": -74.0}},
                zoom=10,
                opacity=0.6,
                title="Total Fare by Zone"
            )
            return fig
        ```

        [Recipe B: Density Heatmap / Hotspots]
        Target: "Where are the pickups concentrated?"
        Strategy: Use density_mapbox on Lat/Lon columns
        Code:
        ```python
        def plot(data_context):
            df = data_context['df_trips']
            # No sampling needed for density map usually
            fig = px.density_mapbox(
                df, lat='pickup_latitude', lon='pickup_longitude',
                radius=15, mapbox_style="carto-positron", zoom=10
            )
            return fig
        ```

        [Recipe C: Point Scatter / Bubble Map]
        Target: "Show pickups colored by time"
        Strategy: Sample -> scatter_mapbox
        Code:
        ```python
        def plot(data_context):
            df = data_context['df_trips']
            # CRITICAL: Sample to avoid browser crash
            if len(df) > 20000: df = df.sample(20000)

            fig = px.scatter_mapbox(
                df, lat='pickup_latitude', lon='pickup_longitude',
                color='tpep_pickup_datetime', size='fare_amount',
                mapbox_style="carto-positron"
            )
            return fig
        ```

        === INSTRUCTIONS ===
        1. Access dataframes via `data_context['var_name']`.
        2. Merge dataframes if needed.
        3. Return ONLY the python code inside the markdown block.
        """
        return prompt