"""src/dashboards/doctor_heatmap.py の生成ロジック単体テスト。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.dashboards.doctor_heatmap import (
    _build_dataset,
    _build_dept_series,
    build_doctor_heatmap,
)
from src.core.classify import DeptClassifier

REPO_ROOT = Path(__file__).resolve().parent.parent


def _hourly_rows() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "診療科名": "泌尿器科",
            "予約担当者匿名ID": "DR_U001",
            "曜日": 0,
            "bin_idx": 2,
            "bin_label": "09:00",
            "出勤日数": 4,
            "該当日数": 4,
            "出勤頻度率": 1.0,
            "件数合計": 12,
        },
        {
            "診療科名": "泌尿器科",
            "予約担当者匿名ID": "DR_U002",
            "曜日": 0,
            "bin_idx": 3,
            "bin_label": "09:30",
            "出勤日数": 2,
            "該当日数": 4,
            "出勤頻度率": 0.5,
            "件数合計": 3,
        },
        {
            "診療科名": "眼科",
            "予約担当者匿名ID": "DR_E001",
            "曜日": 2,
            "bin_idx": 4,
            "bin_label": "10:00",
            "出勤日数": 3,
            "該当日数": 4,
            "出勤頻度率": 0.75,
            "件数合計": 8,
        },
    ])


def test_build_dept_series_orders_by_total_desc() -> None:
    df = _hourly_rows()
    rows = _build_dept_series(df[df["診療科名"] == "泌尿器科"])
    assert [r["id"] for r in rows] == ["DR_U001", "DR_U002"]
    assert rows[0]["total"] == 12
    assert rows[0]["frequency"][0][2] == 1.0
    assert rows[1]["frequency"][0][3] == 0.5
    assert rows[1]["count"][0][3] == 3.0


def test_build_dataset_keys_and_weekday_day_count() -> None:
    df = _hourly_rows()
    classifier = DeptClassifier(REPO_ROOT / "config" / "dept_classification.csv")
    ds = _build_dataset(df, classifier)
    assert "DEPT_U" in ds
    assert "DEPT_E" in ds
    assert ds["DEPT_U"]["label"] == "泌尿器科"
    assert ds["DEPT_U"]["weekday_day_count"][0] == 4
    assert len(ds["DEPT_U"]["doctors"]) == 2


def test_build_doctor_heatmap_renders_html(tmp_path: Path) -> None:
    month = "2026-03"
    agg_root = tmp_path / "aggregated"
    (agg_root / month).mkdir(parents=True)
    _hourly_rows().to_csv(
        agg_root / month / "14_doctor_hourly.csv", index=False, encoding="utf-8-sig"
    )
    output = tmp_path / "doctor_heatmap.html"
    build_doctor_heatmap(
        months=[month],
        aggregated_root=agg_root,
        templates_dir=REPO_ROOT / "templates",
        output_path=output,
        classification_path=REPO_ROOT / "config" / "dept_classification.csv",
        theme_css="",
        common_js="",
    )
    html = output.read_text(encoding="utf-8")
    assert "医師×時間帯ヒートマップ" in html
    assert '"DR_U001"' in html  # JSON化された医師IDが含まれる
    assert '"DEPT_U"' in html
    assert '"泌尿器科"' in html
    assert "{{ dataset_json" not in html  # プレースホルダが残っていない
