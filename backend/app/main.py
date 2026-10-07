"""FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import close_pool, init_db, init_pool
from .routers import batches, jobs, rules, wafers
from .scheduler import JobScheduler, scheduler


def create_app(scheduler_override: JobScheduler | None = None) -> FastAPI:
    job_scheduler = scheduler_override or scheduler

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_pool()
        init_db()
        yield
        if scheduler_override is not None:
            scheduler_override.shutdown()
        close_pool()

    app = FastAPI(title="二极管参数提取系统", version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 允许测试注入独立调度器；默认使用模块级单例
    app.state.scheduler = job_scheduler
    jobs.scheduler = job_scheduler

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(batches.router)
    app.include_router(wafers.router)
    app.include_router(jobs.router)
    app.include_router(rules.router)
    return app


app = create_app()
