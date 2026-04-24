"""外来ダッシュボード CLI 統合エントリポイント。

使い方（--month 省略時は data/raw/ を自動スキャン）:
    python -m src.cli anonymize                      # data/raw/ の全CSVを処理
    python -m src.cli anonymize --month 2026-04      # 指定月のみ（単一ファイル）
    python -m src.cli aggregate
    python -m src.cli build monthly
    python -m src.cli build dept
    python -m src.cli build slot
    python -m src.cli build doctor
    python -m src.cli build hub
    python -m src.cli run-all [--no-llm]
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from src.aggregate import aggregate_all_months, aggregate_monthly_data
from src.anonymize import anonymize_directory, anonymize_monthly_data
from src.dashboards.dept_drilldown import build_dept_drilldown
from src.dashboards.doctor_analysis import build_doctor_analysis
from src.dashboards.hub import build_hub_page
from src.dashboards.monthly import build_monthly_dashboard
from src.dashboards.slot_redesign import build_slot_redesign

_ANON_FILE_RE = re.compile(r"^raw_data_(\d{4}-\d{2})\.csv$")

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PATHS = {
    "raw_dir": REPO_ROOT / "data" / "raw",
    "anon_dir": REPO_ROOT / "data" / "raw" / "anonymized",
    "agg_root": REPO_ROOT / "data" / "aggregated",
    "docs_dir": REPO_ROOT / "docs",
    "docs_monthly": REPO_ROOT / "docs" / "monthly",
    "docs_dept": REPO_ROOT / "docs" / "dept",
    "templates_dir": REPO_ROOT / "templates",
    "template_monthly": REPO_ROOT / "templates" / "monthly.html",
    "theme_css": REPO_ROOT / "static" / "css" / "theme.css",
    "common_js": REPO_ROOT / "static" / "js" / "common.js",
    "master_key": REPO_ROOT / "config" / "master_key.csv",
    "slot_key": REPO_ROOT / "config" / "slot_key.csv",
    "dept_classification": REPO_ROOT / "config" / "dept_classification.csv",
    "dept_targets": REPO_ROOT / "config" / "dept_targets.csv",
    "llm_config": REPO_ROOT / "config" / "llm_config.yaml",
}


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _read_static(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _detect_months(anon_dir: Path) -> list[str]:
    """匿名化済みディレクトリから月リストを返す。"""
    months = sorted(
        m.group(1)
        for f in anon_dir.glob("*.csv")
        if (m := _ANON_FILE_RE.match(f.name))
    )
    if not months:
        raise FileNotFoundError(f"匿名化済みCSVが見つかりません: {anon_dir}")
    return months


def _cmd_anonymize(month: str | None) -> list[str]:
    """匿名化して処理済み月リストを返す。"""
    if month:
        input_path = DEFAULT_PATHS["raw_dir"] / f"raw_data_{month}.csv"
        output_path = DEFAULT_PATHS["anon_dir"] / f"raw_data_{month}.csv"
        result = anonymize_monthly_data(
            input_path=input_path,
            output_path=output_path,
            master_key_path=DEFAULT_PATHS["master_key"],
            dept_classification_path=DEFAULT_PATHS["dept_classification"],
            slot_key_path=DEFAULT_PATHS["slot_key"],
        )
        print(f"✓ 匿名化完了: {result.output_path}")
        print(f"  総行数: {result.total_rows:,}  /  ユニーク医師: {result.unique_names_total}")
        if result.newly_registered:
            print(f"  新規登録: {len(result.newly_registered)}名")
            for name, anon_id, dept in result.newly_registered:
                print(f"    {name} → {anon_id} ({dept})")
        return [month]
    else:
        result = anonymize_directory(
            raw_dir=DEFAULT_PATHS["raw_dir"],
            output_dir=DEFAULT_PATHS["anon_dir"],
            master_key_path=DEFAULT_PATHS["master_key"],
            dept_classification_path=DEFAULT_PATHS["dept_classification"],
            slot_key_path=DEFAULT_PATHS["slot_key"],
        )
        print(f"✓ 匿名化完了: {len(result.input_files)} ファイル → {len(result.months)} 月分")
        print(f"  総行数: {result.total_rows:,}  /  月: {', '.join(result.months)}")
        if result.newly_registered:
            print(f"  新規登録: {len(result.newly_registered)}名")
            for name, anon_id, dept in result.newly_registered:
                print(f"    {name} → {anon_id} ({dept})")
        return result.months


def _cmd_aggregate(month: str | None) -> list[str]:
    """集計して処理済み月リストを返す。"""
    if month:
        input_path = DEFAULT_PATHS["anon_dir"] / f"raw_data_{month}.csv"
        result = aggregate_monthly_data(
            input_path=input_path,
            output_dir=DEFAULT_PATHS["agg_root"],
            month=month,
        )
        print(f"✓ 集計完了: {result.output_dir}")
        print(f"  総行数: {result.total_rows:,}  /  生成ファイル: {len(result.generated_files)}")
        return [month]
    else:
        results = aggregate_all_months(
            anon_dir=DEFAULT_PATHS["anon_dir"],
            output_dir=DEFAULT_PATHS["agg_root"],
        )
        months = [r.month for r in results]
        total = sum(r.total_rows for r in results)
        print(f"✓ 集計完了: {len(results)} 月分 / 総行数: {total:,}")
        for r in results:
            print(f"  {r.month}: {r.total_rows:,} 行 → {r.output_dir}")
        return months


def _cmd_build_monthly(month: str | None, use_llm: bool) -> None:
    months = [month] if month else _detect_months(DEFAULT_PATHS["anon_dir"])
    for m in months:
        output_path = DEFAULT_PATHS["docs_monthly"] / f"{m}.html"
        build_monthly_dashboard(
            month=m,
            output_path=output_path,
            aggregated_root=DEFAULT_PATHS["agg_root"],
            template_path=DEFAULT_PATHS["template_monthly"],
            classification_path=DEFAULT_PATHS["dept_classification"],
            targets_path=DEFAULT_PATHS["dept_targets"],
            llm_config_path=DEFAULT_PATHS["llm_config"],
            use_llm=use_llm,
        )
        print(f"✓ 月次ダッシュボード生成: {output_path}")


def _cmd_build_dept(month: str | None) -> None:
    months = [month] if month else _detect_months(DEFAULT_PATHS["anon_dir"])
    theme = _read_static(DEFAULT_PATHS["theme_css"])
    js = _read_static(DEFAULT_PATHS["common_js"])
    for m in months:
        out_dir = DEFAULT_PATHS["docs_dept"] / m
        generated = build_dept_drilldown(
            month=m,
            aggregated_root=DEFAULT_PATHS["agg_root"],
            templates_dir=DEFAULT_PATHS["templates_dir"],
            output_dir=out_dir,
            classification_path=DEFAULT_PATHS["dept_classification"],
            targets_path=DEFAULT_PATHS["dept_targets"],
            theme_css=theme,
            common_js=js,
        )
        print(f"✓ 診療科深掘り生成: {len(generated)} 件 → {out_dir}")


def _cmd_build_slot(month: str | None) -> None:
    months = [month] if month else _detect_months(DEFAULT_PATHS["anon_dir"])
    latest = months[-1]
    output_path = DEFAULT_PATHS["docs_dir"] / "slot_redesign.html"
    build_slot_redesign(
        month=latest,
        aggregated_root=DEFAULT_PATHS["agg_root"],
        templates_dir=DEFAULT_PATHS["templates_dir"],
        output_path=output_path,
        classification_path=DEFAULT_PATHS["dept_classification"],
        theme_css=_read_static(DEFAULT_PATHS["theme_css"]),
        common_js=_read_static(DEFAULT_PATHS["common_js"]),
    )
    print(f"✓ 予約枠再設計生成 ({latest}): {output_path}")


def _cmd_build_doctor(month: str | None) -> None:
    months = [month] if month else _detect_months(DEFAULT_PATHS["anon_dir"])
    latest = months[-1]
    output_path = DEFAULT_PATHS["docs_dir"] / "doctor_analysis.html"
    build_doctor_analysis(
        month=latest,
        aggregated_root=DEFAULT_PATHS["agg_root"],
        templates_dir=DEFAULT_PATHS["templates_dir"],
        output_path=output_path,
        classification_path=DEFAULT_PATHS["dept_classification"],
        theme_css=_read_static(DEFAULT_PATHS["theme_css"]),
        common_js=_read_static(DEFAULT_PATHS["common_js"]),
    )
    print(f"✓ 医師別分析生成 ({latest}): {output_path}")


def _cmd_build_hub() -> None:
    output = build_hub_page(
        docs_dir=DEFAULT_PATHS["docs_dir"],
        templates_dir=DEFAULT_PATHS["templates_dir"],
        aggregated_root=DEFAULT_PATHS["agg_root"],
        classification_path=DEFAULT_PATHS["dept_classification"],
        theme_css=_read_static(DEFAULT_PATHS["theme_css"]),
    )
    print(f"✓ ハブページ生成: {output}")


def _cmd_run_all(month: str | None, use_llm: bool) -> None:
    label = month or "（自動検出）"
    print(f"=== run-all: {label} ===")
    _cmd_anonymize(month)
    _cmd_aggregate(month)
    _cmd_build_monthly(month, use_llm)
    _cmd_build_dept(month)
    _cmd_build_slot(month)
    _cmd_build_doctor(month)
    _cmd_build_hub()
    print("=== 全処理完了 ===")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outpatient-dashboard",
        description="外来効率化ダッシュボード CLI",
    )
    parser.add_argument("--verbose", action="store_true", help="詳細ログ")
    sub = parser.add_subparsers(dest="command", required=True)

    p_anon = sub.add_parser("anonymize", help="医師名を匿名IDに変換")
    p_anon.add_argument("--month", default=None, help="YYYY-MM（省略時は data/raw/ を自動スキャン）")

    p_agg = sub.add_parser("aggregate", help="匿名化済みCSV → 集計CSV")
    p_agg.add_argument("--month", default=None, help="YYYY-MM（省略時は全月）")

    p_build = sub.add_parser("build", help="ダッシュボード生成")
    build_sub = p_build.add_subparsers(dest="target", required=True)

    p_monthly = build_sub.add_parser("monthly", help="月次管理ダッシュボード")
    p_monthly.add_argument("--month", default=None, help="YYYY-MM（省略時は全月）")
    p_monthly.add_argument("--no-llm", action="store_true", help="LLM未使用")

    p_dept = build_sub.add_parser("dept", help="診療科深掘り（44科一括）")
    p_dept.add_argument("--month", default=None, help="YYYY-MM（省略時は全月）")

    p_slot = build_sub.add_parser("slot", help="予約枠再設計（最新月）")
    p_slot.add_argument("--month", default=None, help="YYYY-MM（省略時は最新月）")

    p_doc = build_sub.add_parser("doctor", help="医師別分析（最新月）")
    p_doc.add_argument("--month", default=None, help="YYYY-MM（省略時は最新月）")

    build_sub.add_parser("hub", help="ハブページ（docs/index.html）再生成")

    p_all = sub.add_parser("run-all", help="匿名化→集計→各ダッシュボード→ハブを一括")
    p_all.add_argument("--month", default=None, help="YYYY-MM（省略時は data/raw/ を自動スキャン）")
    p_all.add_argument("--no-llm", action="store_true", help="LLM未使用")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        if args.command == "anonymize":
            _cmd_anonymize(args.month)
        elif args.command == "aggregate":
            _cmd_aggregate(args.month)
        elif args.command == "build":
            if args.target == "monthly":
                _cmd_build_monthly(args.month, use_llm=not args.no_llm)
            elif args.target == "dept":
                _cmd_build_dept(args.month)
            elif args.target == "slot":
                _cmd_build_slot(args.month)
            elif args.target == "doctor":
                _cmd_build_doctor(args.month)
            elif args.target == "hub":
                _cmd_build_hub()
            else:
                parser.print_help()
                return 2
        elif args.command == "run-all":
            _cmd_run_all(args.month, use_llm=not args.no_llm)
        else:
            parser.print_help()
            return 2
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    except Exception as e:
        logging.exception("実行時エラー")
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
