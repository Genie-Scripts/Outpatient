"""外来データ集計モジュール。

匿名化済みCSV（data/raw/anonymized/raw_data_YYYY-MM.csv）を読み、
12種類の集計CSVを data/aggregated/YYYY-MM/ 配下に出力する。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DOCTOR_ID_COLUMN = "予約担当者匿名ID"


@dataclass
class AggregationResult:
    """集計実行結果のサマリ。"""

    input_path: Path
    output_dir: Path
    month: str
    total_rows: int
    generated_files: list[str]


def _classify_exam_time(t: float) -> str:
    """診察時間を階級分け。"""
    if pd.isna(t) or t < 0:
        return "不明"
    if t < 5:
        return "0-4分"
    if t < 10:
        return "5-9分"
    if t < 15:
        return "10-14分"
    if t < 30:
        return "15-29分"
    return "30分以上"


def _classify_wait_time(t: float) -> str:
    """診察待時間を階級分け。"""
    if pd.isna(t) or t < 0:
        return "不明"
    if t < 30:
        return "0-29分"
    if t < 60:
        return "30-59分"
    if t < 90:
        return "60-89分"
    if t < 120:
        return "90-119分"
    return "120分以上"


def _time_zone(h: float) -> str:
    """受付時刻（時）を時間帯ゾーンに分類。"""
    if pd.isna(h):
        return "不明"
    if h < 12:
        return "午前(〜12時)"
    if h < 15:
        return "午後前半(12-15時)"
    if h < 17:
        return "午後後半(15-17時)"
    return "夕方以降(17時〜)"


def _read_csv_auto_encoding(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp932")


def _preprocess(df: pd.DataFrame) -> pd.DataFrame:
    """日付・時刻の前処理と階級分け。"""
    df = df.copy()
    df["予約日"] = pd.to_datetime(df["予約日"], errors="coerce")
    df["曜日"] = df["予約日"].dt.dayofweek
    df["月"] = df["予約日"].dt.to_period("M").astype(str)

    uketsuke = pd.to_datetime(df["受付時刻"], format="%H:%M:%S", errors="coerce")
    df["受付h"] = uketsuke.dt.hour
    df["受付_30min"] = uketsuke.dt.floor("30min").dt.strftime("%H:%M")

    df["診察時間_階級"] = df["診察時間"].apply(_classify_exam_time)
    df["診察待時間_階級"] = df["診察待時間"].apply(_classify_wait_time)
    df["時間帯ゾーン"] = df["受付h"].apply(_time_zone)
    return df


def _write(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _agg_summary(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{
        "総件数": len(df),
        "期間_開始": df["予約日"].min().strftime("%Y-%m-%d") if df["予約日"].notna().any() else "",
        "期間_終了": df["予約日"].max().strftime("%Y-%m-%d") if df["予約日"].notna().any() else "",
        "診療科数": df["診療科名"].nunique(),
        "医師数": df[DOCTOR_ID_COLUMN].nunique(),
        "部屋数": df["部屋番号"].nunique(),
        "予約名称_種類数": df["予約名称"].nunique(),
        "初診件数": (df["初再診区分"] == "初診").sum(),
        "再診件数": (df["初再診区分"] == "再診").sum(),
        "紹介状あり": (df["紹介状有無"] == "紹介状あり").sum(),
        "併科受診_有": (df["併科受診フラグ"] == "有").sum(),
        "未来院件数": (df["診療受付区分"] == "未来院").sum(),
    }])


def _agg_time_stats(df: pd.DataFrame) -> pd.DataFrame:
    def stats(x: pd.DataFrame) -> pd.Series:
        return pd.Series({
            "件数": len(x),
            "待_中央値": x["診察待時間"].median(),
            "待_平均": x["診察待時間"].mean(),
            "待_Q1": x["診察待時間"].quantile(0.25),
            "待_Q3": x["診察待時間"].quantile(0.75),
            "診察_中央値": x["診察時間"].median(),
            "診察_平均": x["診察時間"].mean(),
            "診察_Q3": x["診察時間"].quantile(0.75),
            "会計_中央値": x["会計待時間"].median(),
            "会計_平均": x["会計待時間"].mean(),
        })

    return (
        df.groupby(["診療科名", "曜日", "受付h"]).apply(stats).reset_index().round(1)
    )


def _agg_referral_kpi(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (dept, month), g in df.groupby(["診療科名", "月"]):
        total = len(g)
        sho = (g["初再診区分"] == "初診").sum()
        sai = (g["初再診区分"] == "再診").sum()
        shokai_sho = ((g["初再診区分"] == "初診") & (g["紹介状有無"] == "紹介状あり")).sum()
        shokai_all = (g["紹介状有無"] == "紹介状あり").sum()
        mirain = (g["診療受付区分"] == "未来院").sum()
        rows.append({
            "診療科名": dept,
            "月": month,
            "総件数": total,
            "初診件数": int(sho),
            "再診件数": int(sai),
            "紹介状あり初診": int(shokai_sho),
            "紹介状あり全件": int(shokai_all),
            "未来院件数": int(mirain),
            "初診率": round(sho / total * 100, 2) if total else 0,
            "紹介率": round(shokai_sho / sho * 100, 2) if sho else 0,
            "紹介状率_全体": round(shokai_all / total * 100, 2) if total else 0,
            "未来院率": round(mirain / total * 100, 2) if total else 0,
        })
    return pd.DataFrame(rows)


def aggregate_monthly_data(
    input_path: Path,
    output_dir: Path,
    month: str,
) -> AggregationResult:
    """匿名化済み月次データを12種の集計CSVに変換する。

    Args:
        input_path: 匿名化済みCSV（data/raw/anonymized/raw_data_YYYY-MM.csv）
        output_dir: 出力ベースディレクトリ（data/aggregated/）
        month: 対象月（"YYYY-MM" 形式）

    Returns:
        AggregationResult: 集計サマリ。
    """
    logger.info("集計開始: %s (月=%s)", input_path, month)
    df = _read_csv_auto_encoding(input_path)
    df = _preprocess(df)

    out = output_dir / month
    out.mkdir(parents=True, exist_ok=True)

    generated: list[str] = []

    _write(_agg_summary(df), out / "00_summary.csv")
    generated.append("00_summary.csv")

    agg01 = (
        df.groupby(["診療科名", "曜日", "受付h", "初再診区分", "紹介状有無"], dropna=False)
        .size().reset_index(name="件数")
    )
    _write(agg01, out / "01_dept_weekday_hour.csv")
    generated.append("01_dept_weekday_hour.csv")

    agg02 = (
        df.groupby(["診療科名", "月", "初再診区分", "紹介状有無"], dropna=False)
        .size().reset_index(name="件数")
    )
    _write(agg02, out / "02_dept_monthly.csv")
    generated.append("02_dept_monthly.csv")

    _write(_agg_time_stats(df), out / "03_dept_time_stats.csv")
    generated.append("03_dept_time_stats.csv")

    agg04 = (
        df.groupby(
            ["診療科名", DOCTOR_ID_COLUMN, "曜日", "初再診区分", "紹介状有無"], dropna=False
        )
        .size().reset_index(name="件数")
    )
    _write(agg04, out / "04_doctor_summary.csv")
    generated.append("04_doctor_summary.csv")

    agg05 = (
        df.groupby(["診療科名", "診療受付区分", "予約フラグ", "曜日"], dropna=False)
        .size().reset_index(name="件数")
    )
    _write(agg05, out / "05_dept_reception.csv")
    generated.append("05_dept_reception.csv")

    agg06 = (
        df[df["受付_30min"].notna()]
        .groupby(
            ["部屋番号", "曜日", "受付_30min", "診療科名", "初再診区分"], dropna=False
        )
        .size().reset_index(name="件数")
    )
    _write(agg06, out / "06_room_30min.csv")
    generated.append("06_room_30min.csv")

    agg07 = (
        df.groupby(
            [
                "診療科名", DOCTOR_ID_COLUMN, "予約名称", "初再診区分",
                "紹介状有無", "月",
            ],
            dropna=False,
        )
        .size().reset_index(name="件数")
    )
    _write(agg07, out / "07_slot_analysis.csv")
    generated.append("07_slot_analysis.csv")

    agg08 = (
        df.groupby(
            [
                "診療科名", "月", "診療区分", "診察時間_階級",
                "併科受診フラグ", "紹介状有無", "初再診区分",
                "予約フラグ", "診察前検査フラグ",
            ],
            dropna=False,
        )
        .size().reset_index(name="件数")
    )
    _write(agg08, out / "08_reverse_referral.csv")
    generated.append("08_reverse_referral.csv")

    df_heika = df[df["併科受診フラグ"] == "有"]
    agg09 = (
        df_heika.groupby(
            ["診療科名", "併科診療科略称名1", "曜日", "初再診区分"], dropna=False
        )
        .size().reset_index(name="件数")
    )
    _write(agg09, out / "09_concurrent_pairs.csv")
    generated.append("09_concurrent_pairs.csv")

    _write(_agg_referral_kpi(df), out / "10_referral_kpi.csv")
    generated.append("10_referral_kpi.csv")

    agg11 = (
        df.groupby(["診療科名", "曜日", "時間帯ゾーン", "初再診区分"], dropna=False)
        .size().reset_index(name="件数")
    )
    _write(agg11, out / "11_dept_timezone.csv")
    generated.append("11_dept_timezone.csv")

    logger.info("集計完了: %d行 → %d ファイル (%s)", len(df), len(generated), out)
    return AggregationResult(
        input_path=input_path,
        output_dir=out,
        month=month,
        total_rows=len(df),
        generated_files=generated,
    )
