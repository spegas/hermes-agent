"""Export session conversations to Markdown for Obsidian / project notes."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hermes_state import SessionDB


def _safe_filename(s: str) -> str:
    """문자열을 파일명으로 안전하게 변환."""
    s = re.sub(r'[^\w\s\-]', '', s).strip()
    s = re.sub(r'\s+', '_', s)
    return s[:60] or "session"


def export_session(
    db: "SessionDB",
    session_id: str,
    project_name: str,
    base_dir: str | None = None,
    obsidian_vault: str | None = None,
) -> str:
    """
    세션 대화를 Markdown으로 저장한다.

    저장 경로:
      {base_dir}/Projects/{project_name}/YYYY-MM-DD/{session_id}_{title}.md

    obsidian_vault가 설정된 경우 해당 경로에도 동일 파일을 복사한다.

    Returns:
        저장된 파일의 절대 경로
    """
    if base_dir is None:
        base_dir = str(Path.home() / ".hermes")

    # ── 세션 메타 로드 ───────────────────────────────────────────────────────
    session = db.get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")

    title = (session.get("title") or "").strip()
    started_at = session.get("started_at") or time.time()
    date_str = time.strftime("%Y-%m-%d", time.localtime(started_at))

    # ── 메시지 로드 ───────────────────────────────────────────────────────────
    messages = db.get_messages(session_id)

    # ── 저장 경로 결정 ────────────────────────────────────────────────────────
    project_dir = Path(base_dir) / "Projects" / project_name / date_str
    project_dir.mkdir(parents=True, exist_ok=True)

    fname_parts = [session_id]
    if title:
        fname_parts.append(_safe_filename(title))
    elif session.get("message_count"):
        fname_parts.append(f"msg{session['message_count']}")
    filename = "_".join(fname_parts) + ".md"
    dest_path = project_dir / filename

    # ── Markdown 생성 ─────────────────────────────────────────────────────────
    md_lines: list[str] = []

    # Frontmatter
    md_lines.append(f"---")
    md_lines.append(f"title: \"{title}\"")
    md_lines.append(f"date: {date_str}")
    md_lines.append(f"session_id: \"{session_id}\"")
    md_lines.append(f"project: \"{project_name}\"")
    md_lines.append(f"---")
    md_lines.append("")

    # Banner (optionally render title again as heading)
    if title:
        md_lines.append(f"# {title}")
    else:
        md_lines.append(f"# Session {session_id}")
    md_lines.append("")
    md_lines.append(f"> Project: **{project_name}**  |  Date: {date_str}")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")

    # 대화 본문
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content") or ""

        if role == "user":
            md_lines.append(f"**🧑 User:**")
        elif role == "assistant":
            md_lines.append(f"**🤖 Assistant:**")
        elif role == "tool":
            tool_name = msg.get("tool_name") or "tool"
            md_lines.append(f"**🔧 Tool ({tool_name}):**")
        else:
            md_lines.append(f"**{role}:**")

        if content:
            md_lines.append("")
            md_lines.append(content)
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    md_text = "\n".join(md_lines)

    # ── 저장 ─────────────────────────────────────────────────────────────────
    dest_path.write_text(md_text, encoding="utf-8")

    # Obsidian vault 복사 (설정된 경우)
    if obsidian_vault:
        vault_dir = Path(obsidian_vault).expanduser() / "Hermes" / project_name / date_str
        vault_dir.mkdir(parents=True, exist_ok=True)
        (vault_dir / filename).write_text(md_text, encoding="utf-8")

    return str(dest_path)
