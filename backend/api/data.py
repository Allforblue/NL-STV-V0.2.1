import os
import shutil
from fastapi import APIRouter, UploadFile, File, Request, HTTPException
from typing import List
from core.services.session_service import session_service

router = APIRouter()


@router.post("/upload")
async def upload_data(
        request: Request,
        files: List[UploadFile] = File(...),
        session_id: str = "default"
):
    """
    1. 保存上传文件到 data_sandbox 下的 session 专属目录 (实现多用户隔离)
    2. 自动清洗文件名，确保生成的变量名在 Python 中合法
    3. 筛选出主数据文件传给 SessionManager
    """
    # [修改] 建立 session 专属沙箱路径，防止多用户并发冲突
    sandbox_root = "core/data_sandbox"
    session_sandbox = os.path.join(sandbox_root, session_id)
    os.makedirs(session_sandbox, exist_ok=True)

    ALLOWED_EXTENSIONS = ('.csv', '.parquet', '.json', '.geojson', '.shp', '.shx', '.dbf', '.prj')
    LOADABLE_EXTENSIONS = ('.csv', '.parquet', '.shp', '.geojson', '.json')

    saved_paths = []
    load_targets = []

    try:
        for file in files:
            # [关键修复] 清洗文件名：转小写、替换中划线和空格为下划线
            # 确保文件名转变量名后（如 df_taxi_data）符合 Python 语法
            clean_filename = file.filename.lower().replace("-", "_").replace(" ", "_")

            if not clean_filename.endswith(ALLOWED_EXTENSIONS): continue

            file_path = os.path.join(session_sandbox, clean_filename)
            with open(file_path, "wb") as buffer:
                await file.seek(0)
                shutil.copyfileobj(file.file, buffer)

            saved_paths.append(file_path)

            # 筛选主文件用于加载
            if clean_filename.endswith(LOADABLE_EXTENSIONS):
                load_targets.append(file_path)

        if not load_targets:
            raise HTTPException(status_code=400, detail="未找到有效的主数据文件")

        # 初始化 Session (此时会生成包含时间维度的基础画像)
        session_state = session_service.create_session(session_id, load_targets)

        return {
            "status": "success",
            "session_id": session_id,
            "datasets": [s["variable_name"] for s in session_state["summaries"]],
            "ready": True
        }

    except Exception as e:
        # 异常时记录日志并抛出错误
        import logging
        logging.getLogger(__name__).error(f"Session {session_id} 数据上传失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))