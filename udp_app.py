"""Small reliable UDP probe: sequence numbers, ACKs, deduplication, retry.

The server ACKs every valid datagram, including duplicates.  Both processes
use the same monotonic clock when launched inside one Mininet machine.
"""
import argparse
import csv
import json
import select
import socket
import struct
import time
from pathlib import Path


DATA = struct.Struct("!4sIQ")
ACK = struct.Struct("!4sIQQ")
DATA_MAGIC = b"ADN1"
ACK_MAGIC = b"ACK1"


def run_server(args):
    seen = set()
    received = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((args.bind_ip, args.port))
        sock.settimeout(0.5)
        print("UDP server listening on %s:%s" % (args.bind_ip, args.port), flush=True)
        while True:
            try:
                packet, address = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except KeyboardInterrupt:
                break
            if len(packet) != DATA.size:
                continue
            magic, seq, sent_ns = DATA.unpack(packet)
            if magic != DATA_MAGIC:
                continue
            received_ns = time.monotonic_ns()
            key = (address, seq)
            if key not in seen:
                seen.add(key)
                received += 1
                if received <= 3 or received % 50 == 0:
                    print("received seq=%s from %s total_unique=%s" %
                          (seq, address[0], received), flush=True)
            try:
                sock.sendto(ACK.pack(ACK_MAGIC, seq, sent_ns, received_ns), address)
            except OSError:
                # The client will resend if the ACK could not leave this host.
                continue


def _write_results(records, out_prefix):
    prefix = Path(out_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for seq in sorted(records):
        record = records[seq]
        acked_ns = record.get("acked_ns")
        rows.append({
            "seq": seq,
            "first_sent_ns": record["first_sent_ns"],
            "last_sent_ns": record["last_sent_ns"],
            "acked_ns": acked_ns or "",
            "server_recv_ns": record.get("server_recv_ns", ""),
            "attempts": record["attempts"],
            "initial_attempt_timed_out": int(record["attempts"] > 1),
            "delivery_latency_ms": round((acked_ns - record["first_sent_ns"]) / 1e6, 3) if acked_ns else "",
            "last_attempt_rtt_ms": round((acked_ns - record["last_sent_ns"]) / 1e6, 3) if acked_ns else "",
        })
    fields = list(rows[0]) if rows else [
        "seq", "first_sent_ns", "last_sent_ns", "acked_ns", "server_recv_ns",
        "attempts", "initial_attempt_timed_out", "delivery_latency_ms", "last_attempt_rtt_ms"]
    with prefix.with_suffix(".csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fields)
        writer.writeheader()
        writer.writerows(rows)
    acknowledged = [row for row in rows if row["acked_ns"]]
    summary = {
        "sent_unique": len(rows),
        "acknowledged": len(acknowledged),
        "unrecovered": len(rows) - len(acknowledged),
        "initial_attempt_timeouts": sum(row["initial_attempt_timed_out"] for row in rows),
        "delivery_rate_pct": round(100 * len(acknowledged) / len(rows), 2) if rows else 0,
        "mean_delivery_latency_ms": round(sum(row["delivery_latency_ms"] for row in acknowledged) / len(acknowledged), 3) if acknowledged else None,
        "mean_last_attempt_rtt_ms": round(sum(row["last_attempt_rtt_ms"] for row in acknowledged) / len(acknowledged), 3) if acknowledged else None,
    }
    prefix.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary), flush=True)


def run_client(args):
    interval = 1.0 / args.rate
    retry_ns = int(args.retry_ms * 1e6)
    records = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((args.bind_ip, 0))
        sock.setblocking(False)
        destination = (args.server_ip, args.port)
        start = time.monotonic()
        stop_sending = start + args.duration
        end = stop_sending + args.grace
        next_send = start
        seq = 0
        while time.monotonic() < end:
            now = time.monotonic()
            if now < stop_sending and now >= next_send:
                stamp = time.monotonic_ns()
                try:
                    sock.sendto(DATA.pack(DATA_MAGIC, seq, stamp), destination)
                except OSError:
                    pass  # Keep the sequence outstanding for application retry.
                records[seq] = {"first_sent_ns": stamp, "last_sent_ns": stamp, "attempts": 1}
                seq += 1
                next_send += interval
            current_ns = time.monotonic_ns()
            for item_seq, record in records.items():
                if "acked_ns" not in record and record["attempts"] < args.max_attempts and current_ns - record["last_sent_ns"] >= retry_ns:
                    stamp = time.monotonic_ns()
                    try:
                        sock.sendto(DATA.pack(DATA_MAGIC, item_seq, stamp), destination)
                    except OSError:
                        pass
                    record["last_sent_ns"] = stamp
                    record["attempts"] += 1
            readable, _, _ = select.select([sock], [], [], 0.01)
            if readable:
                try:
                    packet, address = sock.recvfrom(2048)
                except BlockingIOError:
                    continue
                if address[0] != args.server_ip or address[1] != args.port or len(packet) != ACK.size:
                    continue
                magic, ack_seq, echoed_ns, received_ns = ACK.unpack(packet)
                record = records.get(ack_seq)
                if magic == ACK_MAGIC and record and "acked_ns" not in record and echoed_ns == record["last_sent_ns"]:
                    record["acked_ns"] = time.monotonic_ns()
                    record["server_recv_ns"] = received_ns
        _write_results(records, args.output)


def main():
    parser = argparse.ArgumentParser(description="UDP traffic with ACK and retry")
    sub = parser.add_subparsers(dest="role", required=True)
    server = sub.add_parser("server")
    server.add_argument("--bind-ip", default="10.0.0.2")
    server.add_argument("--port", type=int, default=9000)
    client = sub.add_parser("client")
    client.add_argument("--bind-ip", required=True)
    client.add_argument("--server-ip", default="10.0.0.2")
    client.add_argument("--port", type=int, default=9000)
    client.add_argument("--duration", type=float, default=12)
    client.add_argument("--rate", type=float, default=20)
    client.add_argument("--retry-ms", type=float, default=250)
    client.add_argument("--max-attempts", type=int, default=30)
    client.add_argument("--grace", type=float, default=1)
    client.add_argument("--output", default="results/client")
    args = parser.parse_args()
    if args.role == "client" and (args.rate <= 0 or args.duration <= 0 or args.retry_ms <= 0 or args.max_attempts < 1 or args.grace < 0):
        parser.error("client numeric options must be positive (grace may be zero)")
    if args.role == "server":
        run_server(args)
    else:
        run_client(args)


if __name__ == "__main__":
    main()
