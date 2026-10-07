FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# 先装依赖（利用层缓存）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 再拷应用代码
COPY app ./app

EXPOSE 8000

# 单 uvicorn 进程；进程内作业调度器即在此 worker 内运行。
# 如需多 worker，应把作业队列外置（本项目的作业状态全部在 PostgreSQL 中）。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
