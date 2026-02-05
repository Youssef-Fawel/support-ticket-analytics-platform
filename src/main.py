from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import time
from src.api.routes import router
from src.db.indexes import create_indexes
from src.db.mongo import close_db

app = FastAPI(title="Support Ticket Analysis System")

@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    if request.url.path.endswith("/stats"):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        if process_time > 2.0:
            return JSONResponse(
                status_code=504,
                content={"detail": "Performance Limit Exceeded: Aggregation took too long (> 2s)"}
            )
        return response
    return await call_next(request)

@app.on_event("startup")
async def startup_event():
    await create_indexes()

@app.on_event("shutdown")
async def shutdown_event():
    """Task 7: Proper resource cleanup on shutdown"""
    await close_db()

app.include_router(router)

@app.get("/health")
async def health_check():
    return {"status": "ok"}
