"""判级规则版本路由：创建/发布、列表、激活、重判级、版本对比。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from psycopg.types.json import Jsonb

from ..db import get_conn
from ..grading import RuleValidationError, validate_rules
from ..queries import grade_diff, regrade
from ..schemas import GradeDiffOut, RuleVersionCreate, RuleVersionOut

router = APIRouter(tags=["rules"])


@router.post("/rule-versions", response_model=RuleVersionOut, status_code=201)
def create_rule_version(body: RuleVersionCreate) -> RuleVersionOut:
    """创建（并可直接发布激活）一个规则版本。

    版本号自增、不可变；新激活版本自动对所有已有结果重判级，
    只改 grade 与绑定版本，不重新拟合。
    """
    try:
        rules = validate_rules([r.model_dump() for r in body.rules])
    except RuleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO rule_versions(version, is_active, rules, note, published_at)
                    SELECT coalesce(max(version), 0) + 1, %s, %s, %s,
                           CASE WHEN %s THEN now() ELSE NULL END
                    FROM rule_versions
                    RETURNING id, version, is_active, rules, note, created_at, published_at
                    """,
                    (body.activate, Jsonb(rules), body.note, body.activate),
                )
                row = cur.fetchone()
                new_id = row["id"]
                if body.activate:
                    # 新版本生效：旧版本失活，已有结果只重判级、不重新拟合
                    cur.execute(
                        "UPDATE rule_versions SET is_active=FALSE WHERE id <> %s",
                        (new_id,),
                    )
                    cur.execute("SELECT id FROM wafers")
                    for w in cur.fetchall():
                        regrade(conn, int(w["id"]), rules, new_id)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RuleVersionOut(**row)


@router.get("/rule-versions", response_model=list[RuleVersionOut])
def list_rule_versions() -> list[RuleVersionOut]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, version, is_active, rules, note, created_at, published_at
                FROM rule_versions ORDER BY version DESC
                """
            )
            rows = cur.fetchall()
    return [RuleVersionOut(**r) for r in rows]


@router.post("/rule-versions/{version_id}/activate", response_model=RuleVersionOut)
def activate_rule_version(version_id: int) -> RuleVersionOut:
    """激活指定版本：置为当前生效版本，并对所有已有结果重判级。"""
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, rules FROM rule_versions WHERE id=%s FOR UPDATE",
                    (version_id,),
                )
                target = cur.fetchone()
                if target is None:
                    raise HTTPException(status_code=404, detail="规则版本不存在")
                rules = validate_rules(target["rules"])

                cur.execute("SELECT id FROM wafers")
                wafer_ids = [r["id"] for r in cur.fetchall()]
                for wid in wafer_ids:
                    regrade(conn, wid, rules, version_id)

                cur.execute("UPDATE rule_versions SET is_active=FALSE")
                cur.execute(
                    """
                    UPDATE rule_versions SET is_active=TRUE, published_at=coalesce(published_at, now())
                    WHERE id=%s
                    RETURNING id, version, is_active, rules, note, created_at, published_at
                    """,
                    (version_id,),
                )
                row = cur.fetchone()
            conn.commit()
        except HTTPException:
            conn.rollback()
            raise
        except (RuleValidationError, Exception) as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RuleVersionOut(**row)


@router.get(
    "/wafers/{wafer_id}/rule-diff/{from_id}/{to_id}",
    response_model=GradeDiffOut,
)
def compare_rule_versions(wafer_id: int, from_id: int, to_id: int) -> GradeDiffOut:
    """对比两个规则版本下该晶圆的等级变化（参数不变）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, rules FROM rule_versions WHERE id IN (%s,%s) ORDER BY id",
                (from_id, to_id),
            )
            rows = cur.fetchall()
        if len(rows) != 2:
            raise HTTPException(status_code=404, detail="规则版本不存在")
        try:
            diff = grade_diff(
                conn, wafer_id, from_id, to_id,
                validate_rules(rows[0]["rules"]),
                validate_rules(rows[1]["rules"]),
            )
        except RuleValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GradeDiffOut(
        rule_from=from_id, rule_to=to_id,
        changed=diff["changed"],
        summary_from=diff["summary_from"],
        summary_to=diff["summary_to"],
    )
