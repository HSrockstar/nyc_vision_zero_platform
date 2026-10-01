from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.health import readiness
from app.auth import router
from app.data_api import router as data_router
from app.spatial_api import router as spatial_router
from app.risk_api import router as risk_router
from app.governance_api import router as governance_router
from app.upload_limit import UploadLimit

app = FastAPI(title="Vision Zero 数据导入与查询", version="0.2.0")
app.include_router(router)
app.include_router(data_router)
app.include_router(spatial_router)
app.include_router(risk_router)
app.include_router(governance_router)
app.add_middleware(UploadLimit)


@app.middleware("http")
async def request_identifier(request: Request, call_next):
    try:
        request.state.request_id = UUID(request.headers.get("X-Request-ID", ""))
    except ValueError:
        request.state.request_id = uuid4()
    result = await call_next(request)
    result.headers["X-Request-ID"] = str(request.state.request_id)
    if request.url.path.startswith("/api/"):
        result.headers["Cache-Control"] = "no-store"
    return result


def error_response(request, status, code, message, headers=None):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message},
                        "meta": {"request_id": str(request.state.request_id)}}, headers=headers)


@app.exception_handler(HTTPException)
async def http_error(request, exception):
    detail = exception.detail if isinstance(exception.detail, dict) else {"code": "HTTP_ERROR", "message": "请求无法完成。"}
    return error_response(request, exception.status_code, detail["code"], detail["message"], exception.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exception):
    # 不返回异常中的input，避免把提交的密码回显到响应或日志。
    return error_response(request, 422, "INVALID_INPUT", "参数格式或长度不符合要求。")


@app.exception_handler(IntegrityError)
async def integrity_error(request, exception):
    return error_response(request, 409, "DATA_CONFLICT", "数据约束或并发状态冲突，请刷新后重试。")


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exception):
    return error_response(request, 503, "DATABASE_UNAVAILABLE", "数据库暂时不可用。")


@app.get("/health/live")
def live() -> dict:
    return {"status": "alive"}


@app.get("/health/ready")
def ready() -> JSONResponse:
    body, status = readiness()
    return JSONResponse(body, status_code=status)
