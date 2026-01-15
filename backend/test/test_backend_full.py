import asyncio
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import json

# 导入你的核心模块
from core.llm.AI_client import AIClient
from core.services.workflow import AnalysisWorkflow
from core.schemas.interaction import InteractionPayload


async def test_workflow():
    print("🚀 开始后端集成测试...")

    # 1. 准备模拟数据 (Mock Data Context)
    # 创建一个简单的出租车订单数据集
    data = {
        'trip_id': [1, 2, 3, 4, 5],
        'pickup_time': ['2023-10-01 08:00', '2023-10-01 09:00', '2023-10-01 10:00', '2023-10-01 11:00',
                        '2023-10-01 12:00'],
        'lat': [31.23, 31.24, 31.22, 31.25, 31.23],
        'lon': [121.47, 121.48, 121.46, 121.49, 121.47],
        'fare': [50.0, 45.5, 60.0, 30.0, 55.0],
        'district': ['Jingan', 'Huangpu', 'Jingan', 'Pudong', 'Huangpu']
    }
    df_taxi = pd.DataFrame(data)
    df_taxi['pickup_time'] = pd.to_datetime(df_taxi['pickup_time'])

    # 转换为 GeoDataFrame
    gdf_taxi = gpd.GeoDataFrame(
        df_taxi,
        geometry=gpd.points_from_xy(df_taxi.lon, df_taxi.lat),
        crs="EPSG:4326"
    )

    data_context = {"df_taxi": gdf_taxi}
    print("✅ 模拟数据上下文已准备 (变量名: df_taxi)")

    # 2. 模拟语义摘要 (Mock Summaries)
    # 这是 SemanticAnalyzer 应该输出的内容
    mock_summaries = [{
        "variable_name": "df_taxi",
        "file_info": {"name": "mock_taxi_data.csv", "path": "mock/path"},
        "semantic_analysis": {
            "dataset_type": "TRAJECTORY",
            "description": "模拟的城市出租车订单数据",
            "semantic_tags": {
                "trip_id": "ID_KEY",
                "pickup_time": "ST_TIME",
                "lat": "ST_LAT",
                "lon": "ST_LON",
                "fare": "BIZ_PRICE",
                "district": "BIZ_CAT",
                "geometry": "ST_GEO"
            }
        }
    }]
    print("✅ 模拟语义摘要已准备")

    # 3. 初始化工作流
    # 请确保你的环境变量中已设置了 API Key
    client = AIClient(model_name="deepseek-chat")
    workflow = AnalysisWorkflow(client)
    print("✅ AnalysisWorkflow 初始化成功")

    # 4. 模拟用户提问 (InteractionPayload)
    payload = InteractionPayload(
        session_id="test_session_001",
        query="分析不同区域的打车费分布情况，并在地图上展示",
        force_new=True
    )

    # 5. 运行工作流
    try:
        print("\n🤖 AI 正在处理请求 (这可能需要几秒钟)...")
        dashboard = await workflow.execute_step(payload, mock_summaries, data_context)

        print("\n" + "=" * 50)
        print("🎉 测试成功！后端返回了 DashboardSchema")
        print("=" * 50)

        # 验证结果
        print(f"看板标题: {dashboard.title}")
        print(f"组件数量: {len(dashboard.components)}")

        for comp in dashboard.components:
            print(f"\n[组件 ID: {comp.id}]")
            print(f"- 类型: {comp.type}")
            print(f"- 标题: {comp.title}")
            print(f"- 布局: {comp.layout}")

            if comp.type == "insight" and comp.insight_config:
                print(f"- 🤖 AI 洞察摘要: {comp.insight_config.summary}")
                print(f"- 🤖 AI 详细解释: {comp.insight_config.detail}")

        # 检查生成的代码（在 metadata 中）
        if "last_code" in dashboard.metadata:
            print("\n" + "-" * 30)
            print("📝 AI 生成的执行代码片段:")
            print(dashboard.metadata["last_code"][:300] + "...")

    except Exception as e:
        print(f"\n❌ 测试过程中出现异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_workflow())