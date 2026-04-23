"""外来ダッシュボード CLI 統合エントリポイント。

使い方:
    python -m src.cli anonymize --month 2026-04
    python -m src.cli aggregate --month 2026-04
    python -m src.cli build monthly --month 2026-04
    python -m src.cli run-all --month 2026-04 [--no-llm]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.aggregate import aggregate_monthly_data
from src.anonymize import anonymize_monthly_data
from src.dashboards.monthly import build_monthly_dashboard

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PATHS = {
    "raw_dir": REPO_ROOT / "data" / "raw",
    "anon_dir": REPO_ROOT / "data" / "raw" / "anonymized",
    "agg_root": REPO_ROOT / "data" / "aggregated",
    "docs_monthly": REPO_ROOT / "docs" / "monthly",
    "template_monthly": REPO_ROOT / "templates" / "monthly.html",
    "master_key": REPO_ROOT / "config" / "master_key.csv",
    "dept_classification": REPO_ROOT / "config" / "dept_classification.csv",
    "dept_targets": REPO_ROOT / "config" / "dept_targets.csv",
    "llm_config": REPO_ROOT / "config" / "llm_config.yaml",
}


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _cmd_anonymize(month: str) -> None:
    input_path = DEFAULT_PATHS["raw_dir"] / f"raw_data_{month}.csv"
    output_path = DEFAULT_PATHS["anon_dir"] / f"raw_data_{month}.csv"
    result = anonymize_monthly_data(
        input_path=input_path,
        output_path=output_path,
        master_key_path=DEFAULT_PATHS["master_key"],
        dept_classification_path=DEFAULT_PATHS["dept_classification"],
    )
    print(f"✓ 匿名化完了: {result.output_path}")
    print(f"  総行数: {result.total_rows:,}  /  ユニーク医師: {result.unique_names_total}")
    if result.newly_registered:
        print(f"  新規登録: {len(result.newly_registered)}名")
        for name, anon_id, dept in result.newly_registered:
            print(f"    {name} → {anon_id} ({dept})")


def _cmd_aggregate(month: str) -> None:
    input_path = DEFAULT_PATHS["anon_dir"] / f"raw_data_{month}.csv"
    result = aggregate_monthly_data(
        input_path=input_path,
        output_dir=DEFAULT_PATHS["agg_root"],
        month=month,
    )
    print(f"✓ 集計完了: {result.output_dir}")
    print(f"  総行数: {result.total_rows:,}  /  生成ファイル: {len(result.generated_files)}")


def _cmd_build_monthly(month: str, use_llm: bool) -> None:
    output_path = DEFAULT_PATHS["docs_monthly"] / f"{month}.html"
    build_monthly_dashboard(
        month=month,
        output_path=output_path,
        aggregated_root=DEFAULT_PATHS["agg_root"],
        template_path=DEFAULT_PATHS["template_monthly"],
        classification_path=DEFAULT_PATHS["dept_classification"],
        targets_path=DEFAULT_PATHS["dept_targets"],
        llm_config_path=DEFAULT_PATHS["llm_config"],
        use_llm=use_llm,
    )
    print(f"✓ 月次ダッシュボード生成: {output_path}")


def _cmd_run_all(month: str, use_llm: bool) -> None:
    print(f"=== run-all: {month} ===")
    _cmd_anonymize(month)
    _cmd_aggregate(month)
    _cmd_build_monthly(month, use_llm)
    print("=== 全処理完了 ===")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outpatient-dashboard",
        description="外来効率化ダッシュボード CLI",
    )
    parser.add_argument("--verbose", action="store_true", help="詳細ログ")
    sub = parser.add_subparsers(dest="command", required=True)

    p_anon = sub.add_parser("anonymize", help="医師名を匿名IDに変換")
    p_anon.add_argument("--month", required=True, help="YYYY-MM")

    p_agg = sub.add_parser("aggregate", help="匿名化済みCSV → 集計CSV")
    p_agg.add_argument("--month", required=True, help="YYYY-MM")

    p_build = sub.add_parser("build", help="ダッシュボード生成")
    build_sub = p_build.add_subparsers(dest="target", required=True)
    p_monthly = build_sub.add_parser("monthly", help="月次管理ダッシュボード")
    p_monthly.add_argument("--month", required=True, help="YYYY-MM")
    p_monthly.add_argument("--no-llm", action="store_true", help="LLM未使用")

    p_all = sub.add_parser("run-all", help="匿名化→集計→月次生成を一括")
    p_all.add_argument("--month", required=True, help="YYYY-MM")
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
        elif args.command == "build" and args.target == "monthly":
            _cmd_build_monthly(args.month, use_llm=not args.no_llm)
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
