"""医師実名→匿名ID（DR_<診療科コード><3桁連番>）変換モジュール。

入力: data/raw/raw_data_YYYY-MM.csv
出力: data/raw/anonymized/raw_data_YYYY-MM.csv

処理:
    1. 対象列「予約担当者名」を読み、config/master_key.csv を参照
    2. 未登録の名前は診療科コードに基づいて新規に払い出す
    3. master_key.csv に追記（実名は平文。リポジトリには絶対にコミットしない）
    4. 匿名化済みCSVを出力（列名は「予約担当者匿名ID」にリネーム）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

SOURCE_COLUMN = "予約担当者名"
TARGET_COLUMN = "予約担当者匿名ID"
DEPT_COLUMN = "診療科名"

MASTER_KEY_COLUMNS = ["実名", "匿名ID", "診療科名", "初回登録日", "備考"]
DEFAULT_DEPT_CODE = "XX"


@dataclass
class AnonymizationResult:
    """匿名化実行結果のサマリ。"""

    input_path: Path
    output_path: Path
    total_rows: int
    unique_names_total: int
    newly_registered: list[tuple[str, str, str]] = field(default_factory=list)
    """(実名, 匿名ID, 診療科名) の新規登録ログ。"""


def _read_csv_auto_encoding(path: Path) -> pd.DataFrame:
    """UTF-8-SIG / CP932 を自動判別して読み込む。"""
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp932")


def _load_dept_code_map(dept_classification_path: Path) -> dict[str, str]:
    """診療科名→診療科コード辞書を返す。"""
    df = pd.read_csv(dept_classification_path, encoding="utf-8-sig")
    return dict(zip(df["診療科名"].astype(str), df["診療科コード"].astype(str)))


def _load_master_key(master_key_path: Path) -> pd.DataFrame:
    """master_key.csv を読み込む。存在しなければヘッダのみのDataFrameを返す。"""
    if not master_key_path.exists():
        return pd.DataFrame(columns=MASTER_KEY_COLUMNS)

    df = pd.read_csv(master_key_path, encoding="utf-8-sig")
    for col in MASTER_KEY_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[MASTER_KEY_COLUMNS]


def _next_serial(master_df: pd.DataFrame, dept_code: str) -> int:
    """診療科コードに対応する次の連番を返す。"""
    prefix = f"DR_{dept_code}"
    used: list[int] = []
    for anon_id in master_df["匿名ID"].dropna().astype(str):
        if anon_id.startswith(prefix):
            suffix = anon_id[len(prefix):]
            if suffix.isdigit():
                used.append(int(suffix))
    return max(used, default=0) + 1


def _assign_new_id(
    master_df: pd.DataFrame,
    real_name: str,
    dept_name: str,
    dept_code_map: dict[str, str],
    today: str,
) -> tuple[pd.DataFrame, str]:
    """未登録の実名に匿名IDを払い出し、master_dfに追記して返す。"""
    dept_code = dept_code_map.get(dept_name, DEFAULT_DEPT_CODE)
    serial = _next_serial(master_df, dept_code)
    anon_id = f"DR_{dept_code}{serial:03d}"
    new_row = pd.DataFrame(
        [{
            "実名": real_name,
            "匿名ID": anon_id,
            "診療科名": dept_name,
            "初回登録日": today,
            "備考": "",
        }],
        columns=MASTER_KEY_COLUMNS,
    )
    master_df = pd.concat([master_df, new_row], ignore_index=True)
    return master_df, anon_id


def anonymize_monthly_data(
    input_path: Path,
    output_path: Path,
    master_key_path: Path,
    dept_classification_path: Path,
    today: str | None = None,
) -> AnonymizationResult:
    """月次生データを読み、医師実名を匿名IDに変換して出力する。

    Args:
        input_path: 生データCSV（data/raw/raw_data_YYYY-MM.csv）
        output_path: 匿名化済み出力先（data/raw/anonymized/raw_data_YYYY-MM.csv）
        master_key_path: 対応表（config/master_key.csv）
        dept_classification_path: 診療科分類（config/dept_classification.csv）
        today: 初回登録日として使う日付（YYYY-MM-DD）。Noneなら実行日。

    Returns:
        AnonymizationResult: 集計サマリ。
    """
    today = today or date.today().isoformat()

    logger.info("匿名化開始: %s", input_path)
    df = _read_csv_auto_encoding(input_path)

    if SOURCE_COLUMN not in df.columns:
        raise ValueError(f"入力CSVに列 '{SOURCE_COLUMN}' がありません: {input_path}")
    if DEPT_COLUMN not in df.columns:
        raise ValueError(f"入力CSVに列 '{DEPT_COLUMN}' がありません: {input_path}")

    dept_code_map = _load_dept_code_map(dept_classification_path)
    master_df = _load_master_key(master_key_path)

    existing_map = dict(zip(master_df["実名"].astype(str), master_df["匿名ID"].astype(str)))

    unique_pairs = (
        df[[SOURCE_COLUMN, DEPT_COLUMN]].dropna(subset=[SOURCE_COLUMN]).drop_duplicates()
    )

    newly_registered: list[tuple[str, str, str]] = []
    name_to_id: dict[str, str] = dict(existing_map)

    for real_name, dept_name in unique_pairs.itertuples(index=False):
        real_name = str(real_name)
        dept_name = str(dept_name) if pd.notna(dept_name) else ""
        if real_name in name_to_id:
            continue
        master_df, anon_id = _assign_new_id(
            master_df, real_name, dept_name, dept_code_map, today
        )
        name_to_id[real_name] = anon_id
        newly_registered.append((real_name, anon_id, dept_name))
        logger.info("新規登録: %s → %s (%s)", real_name, anon_id, dept_name)

    df[TARGET_COLUMN] = df[SOURCE_COLUMN].map(name_to_id)
    df = df.drop(columns=[SOURCE_COLUMN])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")

    master_key_path.parent.mkdir(parents=True, exist_ok=True)
    master_df.to_csv(master_key_path, index=False, encoding="utf-8-sig")

    result = AnonymizationResult(
        input_path=input_path,
        output_path=output_path,
        total_rows=len(df),
        unique_names_total=len(name_to_id),
        newly_registered=newly_registered,
    )
    logger.info(
        "匿名化完了: %d行 / ユニーク医師 %d名 / 新規 %d名",
        result.total_rows,
        result.unique_names_total,
        len(newly_registered),
    )
    return result
