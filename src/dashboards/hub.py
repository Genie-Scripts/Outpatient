"""ハブページ (docs/index.html) 生成。

docs/ 配下の既存HTMLを走査して、各ダッシュボードへの
リンク集を構築する。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

_MONTH_FILE_RE = re.compile(r"^(\d{4})-(\d{2})\.html$")


def _collect_monthly_links(docs_dir: Path) -> list[dict[str, str]]:
    monthly_dir = docs_dir / "monthly"
    if not monthly_dir.exists():
        return []
    items: list[tuple[str, str]] = []
    for f in monthly_dir.iterdir():
        m = _MONTH_FILE_RE.match(f.name)
        if m:
            items.append((f"{m.group(1)}-{m.group(2)}", f"monthly/{f.name}"))
    items.sort(reverse=True)
    return [{"label": f"{label} 月次", "href": href} for label, href in items]


def _collect_dept_links(docs_dir: Path) -> list[dict[str, str]]:
    dept_dir = docs_dir / "dept"
    if not dept_dir.exists():
        return []
    items: list[tuple[str, str, str]] = []
    for month_dir in sorted(dept_dir.iterdir(), reverse=True):
        if not month_dir.is_dir():
            continue
        for f in sorted(month_dir.glob("*.html")):
            items.append((month_dir.name, f.stem, f"dept/{month_dir.name}/{f.name}"))
    return [
        {"label": f"{month} / {dept}", "href": href}
        for month, dept, href in items
    ]


def build_hub_page(
    docs_dir: Path,
    templates_dir: Path,
    theme_css: str,
) -> Path:
    """docs/index.html を生成する。

    Args:
        docs_dir: docs/ のパス
        templates_dir: templates/ のパス
        theme_css: インライン化する共通CSSの中身

    Returns:
        書き出した index.html の Path
    """
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )

    monthly_links = _collect_monthly_links(docs_dir)
    dept_links = _collect_dept_links(docs_dir)

    slot_html = docs_dir / "slot_redesign.html"
    doctor_html = docs_dir / "doctor_analysis.html"

    body = env.get_template("index.html").render(
        monthly_links=monthly_links,
        dept_links=dept_links,
        slot_redesign_href="slot_redesign.html" if slot_html.exists() else "",
        doctor_analysis_href="doctor_analysis.html" if doctor_html.exists() else "",
    )

    html = env.get_template("base.html").render(
        title="外来効率化ダッシュボード",
        site_title="外来効率化ダッシュボード",
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        theme_css=theme_css,
        content=body,
        scripts="",
    )

    output = docs_dir / "index.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    logger.info("ハブページ出力: %s", output)
    return output
