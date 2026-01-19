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
    sandbox_path = "core/data_sandbox"
    os.makedirs(sandbox_path, exist_ok=True)

    ALLOWED_EXTENSIONS = ('.csv', '.parquet', '.json', '.geojson', '.shp', '.shx', '.dbf', '.prj')
    LOADABLE_EXTENSIONS = ('.csv', '.parquet', '.shp', '.geojson', '.json')

    saved_paths = []
    load_targets = []

    try:
        for file in files:
            filename = file.filename.lower()
            if not filename.endswith(ALLOWED_EXTENSIONS): continue

            file_path = os.path.join(sandbox_path, file.filename)
            with open(file_path, "wb") as buffer:
                await file.seek(0)
                shutil.copyfileobj(file.file, buffer)

            saved_paths.append(file_path)
            if filename.endswith(LOADABLE_EXTENSIONS):
                load_targets.append(file_path)

        if not load_targets:
            raise HTTPException(status_code=400, detail="未找到有效的主数据文件")

        # 初始化 Session (此时会生成基础画像)
        session_state = session_service.create_session(session_id, load_targets)

        return {
            "status": "success",
            "session_id": session_id,
            "datasets": [s["variable_name"] for s in session_state["summaries"]],
            # 提示前端：数据已就绪，可以开始发起第一次对话（规划看板）
            "ready": True
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))