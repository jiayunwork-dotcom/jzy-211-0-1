"""作业调度：每片晶圆的后台处理作业。

实现为进程内线程池（单 uvicorn worker 下足够；多 worker 部署时可换
外部队列，作业状态全部在 PostgreSQL 里）。

取消语义
--------
* 取消标志置位后，计算循环在下一颗管芯处停止；
* 已完成的纯计算结果一律不落库——只有整颗晶圆跑完才在**单事务**里
  提交（先删后插 ``die_results``），因此取消绝不留下半截结果；
* 作业标记为 ``cancelled``。
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .config import settings
from .db import get_conn
from .grading import validate_rules
from .ingestion import fetch_latest_scans
from .processing import JobHandle, compute_wafer, persist_results


class JobNotFound(KeyError):
    pass


class JobScheduler:
    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="wafer-job"
        )
        self._handles: dict[int, JobHandle] = {}
        self._lock = threading.Lock()
        self._last_progress_ts: dict[int, float] = {}

    # ---- 对外接口 ------------------------------------------------------

    def submit_wafer(self, wafer_id: int, rule_version_id: int | None = None) -> int:
        """创建作业并提交后台执行，返回 job_id。

        同一晶圆已有 running/pending 作业时直接返回该作业 id（不重复排队）。
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM jobs
                    WHERE wafer_id = %s AND state IN ('pending','running')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (wafer_id,),
                )
                row = cur.fetchone()
                if row is not None:
                    return int(row["id"])

                if rule_version_id is None:
                    cur.execute(
                        "SELECT id FROM rule_versions WHERE is_active ORDER BY version DESC LIMIT 1"
                    )
                    active = cur.fetchone()
                    if active is None:
                        raise RuntimeError("尚无已发布的判级规则版本")
                    rule_version_id = int(active["id"])

                cur.execute(
                    """
                    INSERT INTO jobs (wafer_id, state, rule_version_id)
                    VALUES (%s, 'pending', %s) RETURNING id
                    """,
                    (wafer_id, rule_version_id),
                )
                job_id = int(cur.fetchone()["id"])
            conn.commit()

        handle = JobHandle(job_id=job_id, wafer_id=wafer_id,
                           cancel_event=threading.Event())
        with self._lock:
            self._handles[job_id] = handle
        self._pool.submit(self._run, job_id, wafer_id, rule_version_id, handle)
        return job_id

    def cancel(self, job_id: int) -> bool:
        """请求取消。返回是否找到活动作业。"""
        with self._lock:
            handle = self._handles.get(job_id)
        if handle is None:
            return False
        handle.cancel_event.set()
        return True

    def shutdown(self) -> None:
        with self._lock:
            for h in self._handles.values():
                h.cancel_event.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ---- 后台执行 ------------------------------------------------------

    def _progress_cb(self, processed: int, total: int, handle: JobHandle) -> None:
        now = time.monotonic()
        last = self._last_progress_ts.get(handle.job_id, 0.0)
        if now - last < settings.progress_interval and processed < total:
            return
        self._last_progress_ts[handle.job_id] = now
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE jobs SET processed=%s, total=%s WHERE id=%s",
                    (processed, total, handle.job_id),
                )
            conn.commit()

    def _run(
        self, job_id: int, wafer_id: int, rule_version_id: int, handle: JobHandle
    ) -> None:
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE jobs SET state='running', started_at=now() WHERE id=%s",
                        (job_id,),
                    )
                    cur.execute("SELECT rules FROM rule_versions WHERE id=%s",
                                (rule_version_id,))
                    rrow = cur.fetchone()
                    if rrow is None:
                        raise RuntimeError(f"规则版本 {rule_version_id} 不存在")
                    rules = validate_rules(rrow["rules"])
                    scans = fetch_latest_scans(conn, wafer_id)
                conn.commit()

            # 纯计算阶段（随时可取消；不产生任何部分写入）
            computed = compute_wafer(
                scans, rules, progress_cb=self._progress_cb, handle=handle
            )

            if computed is None or handle.cancel_event.is_set():
                handle.state = "cancelled"
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE jobs SET state='cancelled', finished_at=now(),
                                   processed=total
                            WHERE id=%s
                            """,
                            (job_id,),
                        )
                    conn.commit()
                return

            # 唯一的写入点：单事务整片替换
            with get_conn() as conn:
                try:
                    persist_results(
                        conn,
                        wafer_id=wafer_id,
                        job_id=job_id,
                        rule_version_id=rule_version_id,
                        computed=computed,
                    )
                    s = computed["summary"]
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE jobs SET state='done', finished_at=now(),
                                   total=%s, processed=%s, n_failed=%s
                            WHERE id=%s
                            """,
                            (s["n_dies"], s["n_dies"], s["n_fit_failed"], job_id),
                        )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
            handle.state = "done"

        except Exception as exc:
            handle.state = "failed"
            handle.error = str(exc)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE jobs SET state='failed', finished_at=now(), error=%s WHERE id=%s",
                        (str(exc), job_id),
                    )
                conn.commit()
        finally:
            with self._lock:
                self._handles.pop(job_id, None)
            self._last_progress_ts.pop(job_id, None)


scheduler = JobScheduler()
