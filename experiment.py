"""Reproducible Mininet run: smoke test, two UDP clients, link outage, metrics."""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController

from topology import AdaptiveTopo


BASE = Path(__file__).resolve().parent


def rows_at(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def summarize(rows, failure_ns, restore_ns):
    sent = len(rows)
    acknowledged = [r for r in rows if r["acked_ns"]]
    timed_out = [r for r in rows if int(r["initial_attempt_timed_out"])]
    sent_during_outage = [r for r in rows if failure_ns <= int(r["first_sent_ns"]) < restore_ns]
    delivered_during_outage = [r for r in sent_during_outage if r["acked_ns"] and int(r["acked_ns"]) < restore_ns]
    after_failure = [int(r["acked_ns"]) for r in rows if r["acked_ns"] and int(r["first_sent_ns"]) >= failure_ns]
    latency = [float(r["delivery_latency_ms"]) for r in acknowledged]
    return {
        "sent_unique": sent,
        "acknowledged": len(acknowledged),
        "unrecovered": sent - len(acknowledged),
        "initial_attempt_timeouts": len(timed_out),
        "initial_attempt_timeout_pct": round(100 * len(timed_out) / sent, 2) if sent else 0,
        "sent_during_outage": len(sent_during_outage),
        "delivered_before_restore": len(delivered_during_outage),
        "recovery_time_ms": round((min(after_failure) - failure_ns) / 1e6, 3) if after_failure else None,
        "mean_delivery_latency_ms": round(sum(latency) / len(latency), 3) if latency else None,
        "max_delivery_latency_ms": round(max(latency), 3) if latency else None,
    }


def ensure_controller_alive(proc, logfile):
    if proc.poll() is not None:
        raise RuntimeError("Ryu controller exited. Read %s" % logfile)


def run(args):
    if args.fail_after <= 0 or args.outage <= 0 or args.duration <= args.fail_after + args.outage + 1:
        raise ValueError("duration must exceed fail-after + outage + 1 second")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manager = shutil.which(args.ryu_manager) if os.path.sep not in args.ryu_manager else args.ryu_manager
    if not manager or not Path(manager).exists():
        raise RuntimeError("ryu-manager not found: %s" % args.ryu_manager)
    env = os.environ.copy()
    env["ADAPTIVE_MODE"] = args.mode
    env["PYTHONPATH"] = str(BASE) + os.pathsep + env.get("PYTHONPATH", "")
    controller_log_path = output / "controller.log"
    controller_log = controller_log_path.open("w", encoding="utf-8")
    controller = subprocess.Popen(
        [str(manager), "--ofp-tcp-listen-port", str(args.controller_port), str(BASE / "controller.py")],
        cwd=BASE, env=env, stdout=controller_log, stderr=subprocess.STDOUT)
    net = None
    server = None
    server_log = None
    client_logs = []
    clients = []
    try:
        time.sleep(1)
        ensure_controller_alive(controller, controller_log_path)
        net = Mininet(topo=AdaptiveTopo(), controller=None, switch=OVSSwitch, autoSetMacs=False)
        net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=args.controller_port)
        net.start()
        net.staticArp()  # The controller installs IPv4 flows; hosts must know peer MACs.
        h1, h2, h3 = (net.get(name) for name in ("h1", "h2", "h3"))
        for host in (h1, h3):
            for _ in range(12):
                ensure_controller_alive(controller, controller_log_path)
                if "EXIT:0" in host.cmd("ping -n -c 1 -W 1 10.0.0.2; echo EXIT:$?"):
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("No IPv4 route from %s to h2. Read %s and inspect ovs-ofctl dump-flows s1." % (host.name, controller_log_path))
        server_log = (output / "server.log").open("w", encoding="utf-8")
        server = h2.popen([sys.executable, str(BASE / "udp_app.py"), "server"], stdout=server_log, stderr=subprocess.STDOUT)
        time.sleep(0.25)
        if server.poll() is not None:
            raise RuntimeError("UDP server exited. Read %s" % (output / "server.log"))
        smoke_prefix = output / "smoke"
        smoke = h1.popen([sys.executable, str(BASE / "udp_app.py"), "client", "--bind-ip", "10.0.0.1",
                          "--duration", "0.4", "--rate", "5", "--grace", "0.5",
                          "--output", str(smoke_prefix)])
        if smoke.wait(timeout=10) != 0 or json.loads(smoke_prefix.with_suffix(".json").read_text())["acknowledged"] == 0:
            raise RuntimeError("UDP smoke test got no ACKs; read controller.log and server.log")
        print("Smoke test passed: h1 UDP packets reached h2 and ACKs returned.", flush=True)
        for host, ip in ((h1, "10.0.0.1"), (h3, "10.0.0.3")):
            log = (output / (host.name + ".log")).open("w", encoding="utf-8")
            client_logs.append(log)
            process = host.popen([sys.executable, str(BASE / "udp_app.py"), "client", "--bind-ip", ip,
                                  "--duration", str(args.duration), "--rate", str(args.rate),
                                  "--output", str(output / host.name)], stdout=log, stderr=subprocess.STDOUT)
            clients.append(process)
        time.sleep(args.fail_after)
        failure_ns = time.monotonic_ns()
        net.configLinkStatus("s2", "s4", "down")
        print("Primary link s2-s4 DOWN", flush=True)
        time.sleep(args.outage)
        restore_ns = time.monotonic_ns()
        net.configLinkStatus("s2", "s4", "up")
        print("Primary link s2-s4 UP", flush=True)
        for process in clients:
            if process.wait(timeout=args.duration + 10) != 0:
                raise RuntimeError("UDP client failed; read h1.log or h3.log")
        rows = rows_at(output / "h1.csv") + rows_at(output / "h3.csv")
        summary = summarize(rows, failure_ns, restore_ns)
        summary.update({"mode": args.mode, "failure_ns": failure_ns, "restore_ns": restore_ns,
                        "outage_seconds": args.outage, "rate_per_client_pps": args.rate})
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)
    finally:
        for process in clients:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
        if server and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill()
        if net:
            net.stop()
        if controller.poll() is None:
            controller.terminate()
            try:
                controller.wait(timeout=3)
            except subprocess.TimeoutExpired:
                controller.kill()
        for handle in client_logs:
            handle.close()
        if server_log:
            server_log.close()
        controller_log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dynamic", "static"), default="dynamic")
    parser.add_argument("--output", default="results/dynamic")
    parser.add_argument("--ryu-manager", default="ryu-manager")
    parser.add_argument("--controller-port", type=int, default=6653)
    parser.add_argument("--duration", type=float, default=15)
    parser.add_argument("--fail-after", type=float, default=5)
    parser.add_argument("--outage", type=float, default=6)
    parser.add_argument("--rate", type=float, default=20)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
