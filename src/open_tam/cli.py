from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer

from open_tam.faults import FAULT_MODES, FaultState
from open_tam.orchestrator.tools import (
    InlineBackend,
    McpStdioBackend,
)

app = typer.Typer(help="open-tam SRE Agent", no_args_is_help=True)
metrics_app = typer.Typer(help="指标查询")
logs_app = typer.Typer(help="日志查询")
fault_app = typer.Typer(help="故障注入")
app.add_typer(metrics_app, name="metrics")
app.add_typer(logs_app, name="logs")
app.add_typer(fault_app, name="fault")


@metrics_app.command("query")
def metrics_query(
    metric: str = typer.Option(...),
    service: str = typer.Option("demo-app"),
    start: str = typer.Option(...),
    end: str = typer.Option(...),
    transport: str = typer.Option("inline", help="inline 或 mcp"),
) -> None:
    datetime.fromisoformat(start)
    datetime.fromisoformat(end)
    backend = InlineBackend() if transport == "inline" else McpStdioBackend()
    typer.echo(f"# {metric} @ {service} ({transport})")
    typer.echo(backend.execute("query_metrics", {
        "metric": metric, "service": service, "start": start, "end": end,
    }))


@logs_app.command("query")
def logs_query(
    service: str = typer.Option("demo-app"),
    start: str = typer.Option(...),
    end: str = typer.Option(...),
    level: str = typer.Option(None),
    keyword: str = typer.Option(None),
    transport: str = typer.Option("inline", help="inline 或 mcp"),
) -> None:
    datetime.fromisoformat(start)
    datetime.fromisoformat(end)
    backend = InlineBackend() if transport == "inline" else McpStdioBackend()
    typer.echo(f"# logs @ {service} ({transport})")
    typer.echo(backend.execute("query_logs", {
        "service": service, "start": start, "end": end, "level": level, "keyword": keyword,
    }))


@fault_app.command("inject")
def fault_inject(name: str, duration: int = typer.Option(30)) -> None:
    FaultState().activate(name, duration_minutes=duration)
    typer.echo(f"fault {name} activated for {duration}min")


@fault_app.command("clear")
def fault_clear(name: str) -> None:
    FaultState().clear(name)
    typer.echo(f"fault {name} cleared")


@fault_app.command("list")
def fault_list() -> None:
    for mode in FAULT_MODES.values():
        typer.echo(f"{mode.name}: {mode.anomaly_desc}")


@app.command("investigate")
def investigate(
    alert_file: str = typer.Option(..., help="告警 JSON 文件路径"),
    fake: bool = typer.Option(False, help="使用内置 FakeChatModel（无 Key 演示）"),
    transport: str = typer.Option("inline", help="inline 或 mcp"),
) -> None:
    """读取告警 JSON，orchestrator 委托双子 Agent 排查并生成结构化根因报告与 trace。"""
    from open_tam.config import Settings
    from open_tam.orchestrator.investigate import run_investigation
    from open_tam.receiver.alert_receiver import normalize_alert
    from open_tam.tracing.trace import TraceRecorder

    settings = Settings.load()
    raw = json.loads(Path(alert_file).read_text(encoding="utf-8"))
    alert = normalize_alert(raw)
    trace = TraceRecorder(alert_id=alert.alert_id, traces_dir=settings.traces_dir)
    metric_trace = TraceRecorder(alert_id=alert.alert_id, traces_dir=settings.traces_dir, agent="metric")
    log_trace = TraceRecorder(alert_id=alert.alert_id, traces_dir=settings.traces_dir, agent="log")
    try:
        result, path = run_investigation(
            alert, settings, fake=fake, transport=transport,
            trace=trace, metric_trace=metric_trace, log_trace=log_trace,
        )
    except RuntimeError as exc:
        typer.echo(f"错误：{exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"report saved: {path}")
    typer.echo(f"trace saved: {trace.path}")
    typer.echo(result.root_cause or "未定位根因")


action_app = typer.Typer(help="运维动作（白名单 + dry-run + 确认 + 审计）")
audit_app = typer.Typer(help="审计日志查看")
app.add_typer(action_app, name="action")
app.add_typer(audit_app, name="audit")


@action_app.command("list")
def action_list() -> None:
    from open_tam.actions import ACTION_REGISTRY

    for spec in ACTION_REGISTRY.values():
        params = ", ".join(spec.params) or "无"
        typer.echo(f"{spec.name} [{spec.sensitivity}] {spec.description} 参数: {params}")


@action_app.command("run")
def action_run(
    action: str = typer.Argument(..., help="动作名，见 open-tam action list"),
    args: list[str] = typer.Option(None, "--arg", help="动作参数，格式 k=v，可多次"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅预览，不执行"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过敏感操作人工确认"),
) -> None:
    from open_tam.actions import ACTION_REGISTRY
    from open_tam.config import Settings
    from open_tam.guardrails import (
        AuditLogger,
        AutoApprove,
        Guardrails,
        InteractiveConfirmer,
    )

    settings = Settings.load()
    arguments: dict[str, str] = {}
    for pair in args or []:
        if "=" not in pair:
            typer.echo(f"无效参数（需 k=v）: {pair}", err=True)
            raise typer.Exit(1)
        key, value = pair.split("=", 1)
        arguments[key] = value
    confirmer = AutoApprove() if yes else InteractiveConfirmer()
    guard = Guardrails(ACTION_REGISTRY, AuditLogger(settings.state_dir), confirmer=confirmer)
    typer.echo(guard.run(action, arguments, actor="cli", dry_run=dry_run, confirmed=yes))


@audit_app.command("show")
def audit_show(limit: int = typer.Option(20, help="显示最近 N 条")) -> None:
    from open_tam.config import Settings
    from open_tam.guardrails import AuditLogger

    settings = Settings.load()
    entries = AuditLogger(settings.state_dir).entries()
    for entry in entries[-limit:]:
        typer.echo(json.dumps(entry, ensure_ascii=False))


patrol_app = typer.Typer(help="定时巡检")
app.add_typer(patrol_app, name="patrol")


@patrol_app.command("run")
def patrol_run(transport: str = typer.Option("inline", help="inline 或 mcp")) -> None:
    from open_tam.config import Settings
    from open_tam.patrol import run_patrol

    settings = Settings.load()
    backend = InlineBackend() if transport == "inline" else McpStdioBackend()
    path = run_patrol(settings.reports_dir, backend=backend)
    typer.echo(f"patrol report: {path}")


@patrol_app.command("watch")
def patrol_watch(
    every_min: int = typer.Option(5, help="巡检间隔（分钟）"),
    max_runs: int = typer.Option(0, help="最大巡检次数，0 表示不限（Ctrl-C 退出）"),
) -> None:
    import time

    from open_tam.config import Settings
    from open_tam.patrol import run_patrol

    settings = Settings.load()
    runs = 0
    while max_runs <= 0 or runs < max_runs:
        path = run_patrol(settings.reports_dir)
        typer.echo(f"patrol report: {path}")
        runs += 1
        if max_runs > 0 and runs >= max_runs:
            break
        time.sleep(every_min * 60)


trace_app = typer.Typer(help="trace 回放")
app.add_typer(trace_app, name="trace")


@trace_app.command("show")
def trace_show(alert_id: str = typer.Argument(...)) -> None:
    """回放某次排查的 trace JSONL。"""
    from open_tam.config import Settings
    from open_tam.tracing.trace import load_trace

    settings = Settings.load()
    path = settings.traces_dir / f"{alert_id}.jsonl"
    if not path.exists():
        typer.echo(f"trace not found: {path}", err=True)
        raise typer.Exit(1)
    for record in load_trace(path):
        typer.echo(json.dumps(record, ensure_ascii=False))


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", help="监听地址"),
    port: int = typer.Option(8000, help="监听端口"),
) -> None:
    """启动 Web UI（FastAPI + 单页聊天界面 + SSE 流式排查过程）。"""
    import uvicorn

    from open_tam.web.app import create_app

    typer.echo(f"open-tam web ui: http://{host}:{port}")
    uvicorn.run(create_app(), host=host, port=port)


@app.command("eval")
def eval_cmd(
    fake: bool = typer.Option(
        False, help="使用故障感知的脚本模型（仅验证评测链路，不代表模型质量）"),
    faults: str = typer.Option(None, help="逗号分隔的故障名，默认全部，见 open-tam fault list"),
    runs: int = typer.Option(1, min=1, help="每种故障运行次数"),
    min_hit_rate: float = typer.Option(None, help="最低命中率阈值（0-1），低于时退出码 1（CI 集成）"),
) -> None:
    """遍历故障模式跑排查闭环，产出根因定位率/关键词命中率/平均步数评测报告。"""
    from open_tam.config import Settings
    from open_tam.eval import run_eval, write_eval_report

    settings = Settings.load()
    names = [n.strip() for n in faults.split(",") if n.strip()] if faults else list(FAULT_MODES)
    unknown = [n for n in names if n not in FAULT_MODES]
    if unknown:
        typer.echo(
            f"未知故障模式: {', '.join(unknown)}（可选: {', '.join(FAULT_MODES)}）", err=True)
        raise typer.Exit(1)
    report = run_eval(names, settings=settings, runs=runs, fake=fake)
    path = write_eval_report(report, settings.reports_dir)
    typer.echo(f"model: {report.model_label}")
    typer.echo(
        f"根因定位率 {report.located_rate:.0%} | 关键词命中率 {report.hit_rate:.0%}"
        f" | 证据充分性 {report.avg_evidence_sufficiency:.2f}"
        f" | 平均步数 {report.avg_steps:.1f} | 平均耗时 {report.avg_elapsed_s:.1f}s")
    typer.echo(f"eval report: {path}")
    try:
        from open_tam.eval import persist_eval_report
        from open_tam.persistence.database import get_database

        db = get_database(settings.database_url.replace("sqlite:///", ""))
        run_id = persist_eval_report(db, report, path)
        typer.echo(f"eval run saved: {run_id}")
    except Exception as exc:
        typer.echo(f"评测结果落库失败（不影响报告文件）: {exc}", err=True)

    if min_hit_rate is not None and not report.check_min_hit_rate(min_hit_rate):
        typer.echo(
            f"FAIL: 命中率 {report.hit_rate:.0%} < 阈值 {min_hit_rate:.0%}", err=True)
        raise typer.Exit(1)


@app.command("eval-compare")
def eval_compare_cmd(
    models: str = typer.Option(..., help="逗号分隔的模型名，如 qwen-plus,qwen-max"),
    faults: str = typer.Option(None, help="逗号分隔的故障名，默认全部"),
    runs: int = typer.Option(1, min=1, help="每种故障运行次数"),
    fake: bool = typer.Option(True, help="使用脚本模型（默认 true）"),
) -> None:
    """A/B 模型对比评测。"""
    from open_tam.config import Settings
    from open_tam.eval_compare import run_compare, write_compare_report

    settings = Settings.load()
    model_labels = [m.strip() for m in models.split(",") if m.strip()]
    names = [n.strip() for n in faults.split(",") if n.strip()] if faults else list(FAULT_MODES)
    report = run_compare(names, model_labels, settings=settings, runs=runs, fake=fake)
    path = write_compare_report(report, settings.reports_dir)
    for r in report.results:
        typer.echo(f"  {r.model_label}: 命中率 {r.report.hit_rate:.0%} | 步数 {r.report.avg_steps:.1f}")
    typer.echo(f"compare report: {path}")
    try:
        from open_tam.eval import persist_eval_report
        from open_tam.persistence.database import get_database

        db = get_database(settings.database_url.replace("sqlite:///", ""))
        for r in report.results:
            run_id = persist_eval_report(db, r.report, path)
            typer.echo(f"eval run saved: {run_id} ({r.model_label})")
    except Exception as exc:
        typer.echo(f"评测结果落库失败（不影响报告文件）: {exc}", err=True)


@app.command("version")
def version() -> None:
    from open_tam import __version__

    typer.echo(f"open-tam {__version__}")


def main() -> None:
    app()


skill_app = typer.Typer(help="Skill 知识库管理（排查模板提取/查看/删除）")
app.add_typer(skill_app, name="skill")


@skill_app.command("list")
def skill_list() -> None:
    """列出所有 Skill。"""
    from open_tam.config import Settings
    from open_tam.skills.loader import SkillLoader

    settings = Settings.load()
    loader = SkillLoader(settings.skills_dir)
    skills = loader.load_all()
    if not skills:
        typer.echo("（无 Skill）")
        return
    for s in skills:
        typer.echo(f"  {s.id}  {s.name:<30s}  pattern={s.alert_pattern:<20s}  confidence={s.confidence:.2f}")


@skill_app.command("show")
def skill_show(skill_id: str) -> None:
    """查看 Skill 详情。"""
    from open_tam.config import Settings
    from open_tam.skills.loader import SkillLoader

    settings = Settings.load()
    loader = SkillLoader(settings.skills_dir)
    skill = loader.get(skill_id)
    if not skill:
        typer.echo(f"Skill not found: {skill_id}", err=True)
        raise typer.Exit(1)
    typer.echo(skill.to_prompt_section())


@skill_app.command("learn")
def skill_learn(
    traces: str = typer.Option("traces", help="trace 文件目录"),
    output: str = typer.Option(None, help="输出目录（默认 skills_dir）"),
) -> None:
    """从 trace 目录批量提取排查模板为 Skill。"""
    from pathlib import Path

    from open_tam.config import Settings
    from open_tam.skills.extractor import extract_skills_from_dir
    from open_tam.skills.loader import SkillLoader

    settings = Settings.load()
    out_dir = Path(output) if output else settings.skills_dir
    skills = extract_skills_from_dir(traces)
    if not skills:
        typer.echo("未从 trace 中提取到 Skill")
        return
    loader = SkillLoader(out_dir)
    for skill in skills:
        path = loader.save(skill)
        typer.echo(f"  saved: {path} ({skill.name}, confidence={skill.confidence:.2f})")
    typer.echo(f"共提取 {len(skills)} 个 Skill")


@skill_app.command("delete")
def skill_delete(skill_id: str) -> None:
    """删除 Skill。"""
    from open_tam.config import Settings
    from open_tam.skills.loader import SkillLoader

    settings = Settings.load()
    loader = SkillLoader(settings.skills_dir)
    if loader.delete(skill_id):
        typer.echo(f"deleted: {skill_id}")
    else:
        typer.echo(f"not found: {skill_id}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    main()


user_app = typer.Typer(help="用户管理（创建/列出/删除）")
app.add_typer(user_app, name="user")


@user_app.command("create")
def user_create(
    username: str = typer.Argument(...),
    role: str = typer.Option("viewer", help="角色: admin/operator/viewer"),
) -> None:
    """创建用户并输出 API Key。"""
    import uuid
    from datetime import datetime

    from open_tam.auth.apikey import generate_api_key, hash_api_key
    from open_tam.config import Settings
    from open_tam.persistence.database import get_database
    from open_tam.persistence.repositories import UserRecord, UserRepository

    settings = Settings.load()
    db_path = settings.database_url.replace("sqlite:///", "")
    db = get_database(db_path)
    user_repo = UserRepository(db)

    if user_repo.get_by_username(username):
        typer.echo(f"用户已存在: {username}", err=True)
        raise typer.Exit(1)

    api_key = generate_api_key()
    user = UserRecord(
        id=str(uuid.uuid4()),
        username=username,
        api_key_hash=hash_api_key(api_key),
        role=role,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
    )
    user_repo.create(user)
    typer.echo(f"用户创建成功: {username} (role={role})")
    typer.echo(f"API Key: {api_key}")
    typer.echo("请妥善保存 API Key，无法再次查看。")


@user_app.command("list")
def user_list() -> None:
    """列出所有用户。"""
    from open_tam.config import Settings
    from open_tam.persistence.database import get_database
    from open_tam.persistence.repositories import UserRepository

    settings = Settings.load()
    db_path = settings.database_url.replace("sqlite:///", "")
    db = get_database(db_path)
    user_repo = UserRepository(db)
    users = user_repo.list_all()
    if not users:
        typer.echo("（无用户）")
        return
    for u in users:
        typer.echo(f"  {u.id[:8]}...  {u.username:<20s}  role={u.role}")


@user_app.command("delete")
def user_delete(user_id: str) -> None:
    """删除用户。"""
    from open_tam.config import Settings
    from open_tam.persistence.database import get_database
    from open_tam.persistence.repositories import UserRepository

    settings = Settings.load()
    db_path = settings.database_url.replace("sqlite:///", "")
    db = get_database(db_path)
    user_repo = UserRepository(db)
    if user_repo.delete(user_id):
        typer.echo(f"deleted: {user_id}")
    else:
        typer.echo(f"not found: {user_id}", err=True)
        raise typer.Exit(1)


db_app = typer.Typer(help="数据库管理")
app.add_typer(db_app, name="db")


@db_app.command("migrate")
def db_migrate() -> None:
    """创建/升级 SQLite 数据库。"""
    from open_tam.config import Settings
    from open_tam.persistence.database import get_database

    settings = Settings.load()
    db_path = settings.database_url.replace("sqlite:///", "")
    get_database(db_path)
    typer.echo(f"数据库已就绪: {db_path}")


history_app = typer.Typer(help="排查历史查看")
app.add_typer(history_app, name="history")


@history_app.command("list")
def history_list(limit: int = typer.Option(20, help="显示最近 N 条")) -> None:
    """列出排查历史。"""
    from open_tam.config import Settings
    from open_tam.persistence.database import get_database
    from open_tam.persistence.repositories import InvestigationRepository

    settings = Settings.load()
    db_path = settings.database_url.replace("sqlite:///", "")
    db = get_database(db_path)
    inv_repo = InvestigationRepository(db)
    investigations = inv_repo.list_all(limit=limit)
    if not investigations:
        typer.echo("（无排查记录）")
        return
    for inv in investigations:
        status = inv.status
        cause = (inv.root_cause or "未定位")[:40]
        typer.echo(f"  {inv.id[:8]}...  {inv.created_at[:16]}  {status:<10s}  {cause}")


@history_app.command("show")
def history_show(inv_id: str) -> None:
    """查看排查详情。"""
    from open_tam.config import Settings
    from open_tam.persistence.database import get_database
    from open_tam.persistence.repositories import InvestigationRepository

    settings = Settings.load()
    db_path = settings.database_url.replace("sqlite:///", "")
    db = get_database(db_path)
    inv_repo = InvestigationRepository(db)
    inv = inv_repo.get_by_id(inv_id)
    if not inv:
        typer.echo(f"not found: {inv_id}", err=True)
        raise typer.Exit(1)
    typer.echo(f"ID: {inv.id}")
    typer.echo(f"Alert ID: {inv.alert_id}")
    typer.echo(f"Status: {inv.status}")
    typer.echo(f"Root Cause: {inv.root_cause or '未定位'}")
    typer.echo(f"Confidence: {inv.confidence or '-'}")
    typer.echo(f"Report: {inv.report_path or '-'}")
    typer.echo(f"Trace: {inv.trace_path or '-'}")
    typer.echo(f"Created: {inv.created_at}")
