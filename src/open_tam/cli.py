from __future__ import annotations

from datetime import datetime

import typer

from open_tam.faults import FAULT_MODES, FaultState
from open_tam.orchestrator.tools import InlineBackend, McpStdioBackend

app = typer.Typer(help="open-tam SRE Agent", no_args_is_help=True)
metrics_app = typer.Typer(help="指标查询")
fault_app = typer.Typer(help="故障注入")
app.add_typer(metrics_app, name="metrics")
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
