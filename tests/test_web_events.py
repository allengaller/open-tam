import asyncio

from open_tam.models import AlertEvent
from open_tam.web.events import InvestigationHub


def _alert() -> AlertEvent:
    return AlertEvent(alert_name="CPU使用率过高", service="demo-app",
                      metric="cpu_usage", threshold=80, current_value=92.5)


def test_hub_create_and_broadcast():
    hub = InvestigationHub()
    inv = hub.create(_alert(), fake=True, transport="inline")
    assert inv.status == "pending"
    assert hub.get(inv.id) is inv

    loop = asyncio.new_event_loop()
    queue = asyncio.Queue()
    sub = hub.subscribe(inv.id, queue=queue, loop=loop)
    assert sub.snapshot == []

    sink = hub.sink_for(inv.id)
    sink({"kind": "tool_call", "tool": "ask_metric_agent"})
    sink({"kind": "final", "content": "done"})

    assert [e["kind"] for e in inv.events] == ["tool_call", "final"]
    assert [e["seq"] for e in inv.events] == [0, 1]
    e1 = loop.run_until_complete(asyncio.wait_for(queue.get(), timeout=1))
    e2 = loop.run_until_complete(asyncio.wait_for(queue.get(), timeout=1))
    assert (e1["kind"], e2["kind"]) == ("tool_call", "final")
    loop.close()


def test_hub_subscribe_replays_snapshot():
    hub = InvestigationHub()
    inv = hub.create(_alert(), fake=True, transport="inline")
    sink = hub.sink_for(inv.id)
    sink({"kind": "alert_received"})

    loop = asyncio.new_event_loop()
    sub = hub.subscribe(inv.id, queue=asyncio.Queue(), loop=loop)
    assert [e["kind"] for e in sub.snapshot] == ["alert_received"]
    sink({"kind": "final", "content": "x"})
    assert len(sub.snapshot) == 1
    e = loop.run_until_complete(asyncio.wait_for(sub.queue.get(), timeout=1))
    assert e["kind"] == "final" and e["seq"] == 1
    loop.close()


def test_hub_finish_marks_done_and_broadcasts_terminal():
    hub = InvestigationHub()
    inv = hub.create(_alert(), fake=True, transport="inline")
    loop = asyncio.new_event_loop()
    sub = hub.subscribe(inv.id, queue=asyncio.Queue(), loop=loop)

    hub.finish(inv.id, report_path="reports/x.md", root_cause="正则回溯",
               confidence="high", evidence=["e1"], actions=["a1"])
    assert inv.status == "done"
    e = loop.run_until_complete(asyncio.wait_for(sub.queue.get(), timeout=1))
    assert e["kind"] == "done" and e["report_path"] == "reports/x.md"
    loop.close()


def test_hub_fail_marks_error():
    hub = InvestigationHub()
    inv = hub.create(_alert(), fake=True, transport="inline")
    loop = asyncio.new_event_loop()
    sub = hub.subscribe(inv.id, queue=asyncio.Queue(), loop=loop)

    hub.fail(inv.id, "boom")
    assert inv.status == "error"
    e = loop.run_until_complete(asyncio.wait_for(sub.queue.get(), timeout=1))
    assert e["kind"] == "error" and e["error"] == "boom"
    loop.close()


def test_hub_unknown_id_raises():
    hub = InvestigationHub()
    try:
        hub.sink_for("nope")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")