// API 类型定义（与后端 Pydantic 模型对应）
export interface Batch {
  id: number;
  name: string;
  created_at: string;
  n_wafers: number;
}

export interface Wafer {
  id: number;
  batch_id: number;
  name: string;
  die_cols: number;
  die_rows: number;
}

export interface RuleItem {
  param: "is" | "n" | "rs";
  lower: number;
  upper: number;
  fail_is_bad: boolean;
}

export interface RuleVersion {
  id: number;
  version: number;
  is_active: boolean;
  rules: RuleItem[];
  note: string | null;
  created_at: string;
  published_at: string | null;
}

export interface DieResult {
  die_x: number;
  die_y: number;
  is_value: number | null;
  n_value: number | null;
  rs_value: number | null;
  residual: number | null;
  rs_reliable: boolean;
  fit_ok: boolean;
  fail_reason: string | null;
  n_points: number;
  n_used: number;
  grade: "pass" | "fail" | "ungraded";
  tested_at: string;
}

export interface ParamStats {
  median: number | null;
  p05: number | null;
  p95: number | null;
  count: number;
}

export interface WaferSummary {
  n_dies: number;
  n_fit_failed: number;
  n_pass: number;
  n_fail: number;
  n_ungraded: number;
  yield: number | null;
  params: { is: ParamStats; n: ParamStats; rs: ParamStats };
}

export interface WaferMap {
  wafer: Wafer;
  rule_version_id: number | null;
  summary: WaferSummary | Record<string, never>;
  dies: DieResult[];
  rejected: { die_x: number; die_y: number; reason: string }[];
}

export interface DieDetail extends DieResult {
  // 以下字段在外层
}

export interface DieDetailResponse {
  die: DieResult;
  voltage: number[];
  current: number[];
  used_mask: boolean[];
  fit_voltage: number[];
  fit_current: number[];
  point_residual: number[];
  temp_k: number;
  tested_at: string;
  reject_reason: string | null;
}

export interface Job {
  id: number;
  wafer_id: number;
  state: "pending" | "running" | "cancelled" | "done" | "failed";
  total: number;
  processed: number;
  n_failed: number;
  error: string | null;
  rule_version_id: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface GradeChange {
  die_x: number;
  die_y: number;
  grade_from: string;
  grade_to: string;
}

export interface GradeDiff {
  rule_from: number;
  rule_to: number;
  changed: GradeChange[];
  summary_from: WaferSummary;
  summary_to: WaferSummary;
}
