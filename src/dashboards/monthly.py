"""月次管理ダッシュボード生成。

集計CSV（data/aggregated/YYYY-MM/）を読み、12ヶ月分のトレンドを構築して
templates/monthly.html にデータ埋込みで出力する。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.classify import DeptClassifier
from src.core.data_loader import load_aggregated_data
from src.core.highlights import extract_highlights
from src.llm_client import LLMClient

logger = logging.getLogger(__name__)


def _load_targets(targets_path: Path) -> dict[str, dict[str, float]]:
    """dept_targets.csv を読み込む。存在しなければ空。"""
    if not targets_path.exists():
        logger.warning("目標ファイル未検出: %s（自動算出のみ）", targets_path)
        return {}
    df = pd.read_csv(targets_path, encoding="utf-8-sig")
    targets: dict[str, dict[str, float]] = {}
    for _, row in df.iterrows():
        targets[str(row["診療科名"])] = {
            "sho_target": int(row.get("初診目標_月", 0) or 0),
            "kus_target": int(row.get("薬のみ再診_目標", 0) or 0),
            "sps_target": float(row.get("再診初診比率_目標", 0) or 0),
        }
    return targets


def _build_dashboard_data(
    aggregated_root: Path,
    month: str,
    classifier: DeptClassifier,
    user_targets: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """対象月を最終月として、過去分も含めた12ヶ月のトレンドデータを構築。"""
    data = load_aggregated_data(aggregated_root, month)
    kpi = data.referral_kpi
    rr = data.reverse_referral

    months = sorted(kpi["月"].astype(str).unique().tolist())
    if not months:
        raise ValueError("集計CSVに月データがありません")

    month_labels = [m.split("-")[1].lstrip("0") + "月" for m in months]

    rr_best = rr[
        (rr["初再診区分"] == "再診")
        & (rr["紹介状有無"] == "紹介状無し")
        & (rr["併科受診フラグ"] == "無")
        & (rr["診察時間_階級"].isin(["0-4分", "5-9分"]))
        & (rr["診察前検査フラグ"] == "なし")
    ]
    kusuri = rr[(rr["診療区分"] == "薬のみ") & (rr["初再診区分"] == "再診")]

    depts_data: list[dict[str, Any]] = []
    for dept_name in kpi["診療科名"].unique():
        if not classifier.is_evaluation_target(dept_name):
            continue
        k = kpi[kpi["診療科名"] == dept_name].set_index("月").reindex(months).fillna(0)
        total = k["総件数"].astype(int).tolist()
        sho = k["初診件数"].astype(int).tolist()
        sai = k["再診件数"].astype(int).tolist()

        kus_m = (
            kusuri[kusuri["診療科名"] == dept_name]
            .groupby("月")["件数"].sum()
            .reindex(months).fillna(0).astype(int).tolist()
        )
        cand_m = (
            rr_best[rr_best["診療科名"] == dept_name]
            .groupby("月")["件数"].sum()
            .reindex(months).fillna(0).astype(int).tolist()
        )

        avg_monthly = sum(total) // max(len(months), 1)
        if avg_monthly < 30:
            continue

        sps_m = [round(s / h, 1) if h > 0 else None for s, h in zip(sai, sho)]

        n = len(months)
        avg_sho = sum(sho) / n
        avg_kus = sum(kus_m) / n
        avg_sai = sum(sai) / n
        sps_avg = round(avg_sai / avg_sho, 1) if avg_sho > 0 else 0

        ut = user_targets.get(dept_name, {})
        sho_target = (
            int(ut["sho_target"]) if ut.get("sho_target")
            else (int(avg_sho * 1.10) if avg_sho > 0 else 0)
        )
        kus_target = (
            int(ut["kus_target"]) if ut.get("kus_target")
            else (int(avg_kus * 0.85) if avg_kus > 0 else 0)
        )
        sps_target = (
            float(ut["sps_target"]) if ut.get("sps_target")
            else (round(sps_avg * 0.9, 1) if sps_avg > 0 else 0)
        )

        dept_type = classifier.get_type(dept_name)
        type_key = {"外科系": "geka", "内科系": "naika"}.get(dept_type, "other")

        depts_data.append({
            "name": dept_name,
            "type": type_key,
            "avg_monthly": avg_monthly,
            "sho_m": sho,
            "sai_m": sai,
            "kus_m": kus_m,
            "cand_m": cand_m,
            "total_m": total,
            "sps_m": sps_m,
            "sho_target": sho_target,
            "kus_target": kus_target,
            "sps_target": sps_target,
        })

    depts_data.sort(key=lambda x: x["avg_monthly"], reverse=True)

    total_sho_monthly = [sum(d["sho_m"][i] for d in depts_data) for i in range(len(months))]
    total_sai_monthly = [sum(d["sai_m"][i] for d in depts_data) for i in range(len(months))]
    total_kus_monthly = [sum(d["kus_m"][i] for d in depts_data) for i in range(len(months))]
    total_cand_monthly = [sum(d["cand_m"][i] for d in depts_data) for i in range(len(months))]
    total_monthly = [sum(d["total_m"][i] for d in depts_data) for i in range(len(months))]

    return {
        "months": months,
        "monthLabels": month_labels,
        "depts": depts_data,
        "total_sho_monthly": total_sho_monthly,
        "total_sai_monthly": total_sai_monthly,
        "total_kus_monthly": total_kus_monthly,
        "total_cand_monthly": total_cand_monthly,
        "total_monthly": total_monthly,
        "global_sho_target": sum(d["sho_target"] for d in depts_data),
        "global_kus_target": sum(d["kus_target"] for d in depts_data),
        "generated_at": datetime.now().isoformat(),
    }


def _render(
    template_path: Path,
    output_path: Path,
    data: dict[str, Any],
    highlights: dict[str, Any],
) -> None:
    """テンプレートのプレースホルダに data/highlights/メタ情報を埋め込む。"""
    html = template_path.read_text(encoding="utf-8")
    html = html.replace(
        "{{DASHBOARD_DATA_JSON}}",
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
    )
    html = html.replace(
        "{{HIGHLIGHTS_JSON}}",
        json.dumps(highlights, ensure_ascii=False, separators=(",", ":")),
    )
    html = html.replace(
        "{{GENERATED_AT}}",
        datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    html = html.replace("{{CURRENT_MONTH}}", data["monthLabels"][-1])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("HTML出力: %s (%d chars)", output_path, len(html))


def build_monthly_dashboard(
    month: str,
    output_path: Path,
    aggregated_root: Path,
    template_path: Path,
    classification_path: Path,
    targets_path: Path,
    llm_config_path: Path,
    use_llm: bool = True,
) -> None:
    """月次ダッシュボードを生成する。

    Args:
        month: "YYYY-MM" 形式
        output_path: 出力HTMLパス
        aggregated_root: data/aggregated/ のパス
        template_path: templates/monthly.html のパス
        classification_path: config/dept_classification.csv
        targets_path: config/dept_targets.csv
        llm_config_path: config/llm_config.yaml
        use_llm: FalseならLLMを呼ばず定型文で生成
    """
    classifier = DeptClassifier(classification_path)
    user_targets = _load_targets(targets_path)

    data = _build_dashboard_data(aggregated_root, month, classifier, user_targets)
    candidates = extract_highlights(data["depts"])

    llm = LLMClient(llm_config_path, enabled=use_llm)
    highlights = llm.generate_highlights(candidates)

    _render(template_path, output_path, data, highlights)
