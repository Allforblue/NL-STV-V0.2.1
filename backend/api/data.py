import os
import shutil
from fastapi import APIRouter, UploadFile, File, Request, HTTPException
from typing import List

# 引入 session_service 单例
from core.services.session_service import session_service

router = APIRouter()


@router.post("/upload")
async def upload_data(
        request: Request,
        files: List[UploadFile] = File(...),
        session_id: str = "default"
):
    """
    1. 保存上传文件到 data_sandbox (包括 .shp, .dbf, .shx 等所有伴生文件)
    2. 筛选出主数据文件 (.shp, .csv, .parquet) 传给 SessionManager
    """
    sandbox_path = "core/data_sandbox"
    os.makedirs(sandbox_path, exist_ok=True)

    # 1. 定义允许保存的所有扩展名 (包含 GIS 伴生文件)
    ALLOWED_EXTENSIONS = (
        '.csv', '.parquet', '.json', '.geojson',
        # Shapefile 家族
        '.shp', '.shx', '.dbf', '.prj', '.sbn', '.sbx', '.xml', '.cpg'
    )

    # 2. 定义触发加载的主文件扩展名
    LOADABLE_EXTENSIONS = ('.csv', '.parquet', '.shp', '.geojson', '.json')

    saved_paths = []  # 实际保存到磁盘的所有文件
    load_targets = []  # 需要让 SessionManager 加载的主文件

    try:
        for file in files:
            filename = file.filename.lower()

            # [关键修复 1] 允许保存伴生文件 (.dbf, .shx 等)
            if not filename.endswith(ALLOWED_EXTENSIONS):
                continue

            file_path = os.path.join(sandbox_path, file.filename)

            # 保存文件
            with open(file_path, "wb") as buffer:
                # 必须重置指针，防止读取空内容
                await file.seek(0)
                shutil.copyfileobj(file.file, buffer)

            saved_paths.append(file_path)

            # [关键修复 2] 筛选主文件用于加载
            # 我们只告诉 SessionManager 去读 .shp，它会自动寻找同目录下的 .dbf/.shx
            if filename.endswith(LOADABLE_EXTENSIONS):
                load_targets.append(file_path)

        if not load_targets:
            # 如果用户只传了 .dbf 没传 .shp，或者没传任何有效文件
            raise HTTPException(status_code=400,
                                detail=f"未找到可加载的主数据文件。已保存: {[os.path.basename(p) for p in saved_paths]}")

        # 调用 SessionManager (只传入主文件路径)
        session_state = session_service.create_session(session_id, load_targets)

        return {
            "status": "success",
            "message": f"成功保存 {len(saved_paths)} 个文件，加载 {len(load_targets)} 个数据集",
            "summaries": session_state["summaries"]
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"文件上传处理失败: {str(e)}")