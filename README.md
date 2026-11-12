# Adaptive UDP Network with SDN Failure Recovery

This project repairs the supplied archive, which contained only a two-host
Mininet topology and a copied virtual environment. It adds a working UDP
application, a Ryu OpenFlow 1.3 controller, a second client, automatic link
failure injection, and a static-versus-dynamic experiment. No measured
results are included because they must be produced on a Linux Mininet host.

## Architecture

```text
h1 (10.0.0.1) -- s1 -- s2 -- s4 -- h2 (10.0.0.2:9000)
                  |           |
h3 (10.0.0.3) -- s1 -- s3 -- s4
                       backup
```

The default route is `s1-s2-s4`. The Ryu controller watches OpenFlow port
status notifications and polls port descriptions every 0.5 seconds. When the
`s2-s4` link goes down, dynamic mode installs bidirectional IPv4 flows along
`s1-s3-s4`. On repair it returns to the primary path. Static mode keeps the
original route for a comparison. Each client sends numbered UDP datagrams;
the server ACKs every valid datagram, including retries. Clients retry timed
out datagrams, so an application message can survive a brief routing gap.

The controller uses a **known physical topology** with fixed OpenFlow ports.
It detects *link status*, not arbitrary newly added links. Mininet's
`staticArp()` installs host neighbor entries so ARP broadcasts do not enter a
switch with no broadcast rule. Both UDP directions and ping between each
client and the server have explicit IPv4 forwarding rules. Other IPv4 pairs
and broadcasts are intentionally outside this demo.

## Files

- `topology.py`: three hosts, four switches, two independent paths, fixed ports.
- `routing.py`: physical port map and primary/alternate path calculation.
- `controller.py`: OpenFlow 1.3 flow installation, link monitoring, rerouting.
- `udp_app.py`: concurrent UDP client processes, server, ACKs and retries.
- `experiment.py`: launches controller and Mininet, checks reachability, tests
  UDP delivery, injects failure, repairs link, saves measurements.
- `compare.py`: prints static and dynamic measurements side by side.
- `tests/`: local path-selection and UDP loopback tests.

## Requirements and setup

Run inside a **Linux Mininet VM or native Ubuntu host**, not Windows PowerShell.
The Mininet project [recommends its VM](https://mininet.org/download/) and
documents the [package and source installation options](https://mininet.org/download/).
Use Python 3.10 on Ubuntu 22.04 or a compatible Mininet VM. Open vSwitch and
Mininet must be installed and working. Ryu runs in its own virtual environment;
the experiment launcher uses the system Python with Mininet's Python package.

From the project directory in the Linux terminal:

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3 python3-venv python3-pip git
sudo service openvswitch-switch start
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip wheel
.venv/bin/python -m pip install 'setuptools<58' pbr
.venv/bin/python -m pip install --no-build-isolation 'git+https://github.com/faucetsdn/ryu.git'
.venv/bin/ryu-manager --version
sudo mn -c
```

Ryu's original PyPI 4.34 release has known installation and Eventlet
compatibility problems with newer Python packages; the [maintained Ryu
source](https://github.com/faucetsdn/ryu) includes fixes. If you already
have a working `ryu-manager`, pass its path to `--ryu-manager` and skip the
Ryu installation commands. The checked-out source revision should be pinned
in a final GitHub submission after the exact lab environment is verified.

## Run the demonstration

Run both scenarios in the **same** project directory. The launcher starts and
stops Ryu and Mininet itself; no separate controller terminal is needed.
Both runs send from h1 and h3 to h2. At 5 seconds the `s2-s4` link goes down;
at 11 seconds it comes back.

```bash
python3 -m unittest discover -s tests -v
sudo python3 experiment.py --mode static --ryu-manager "$PWD/.venv/bin/ryu-manager" --output results/static
sudo python3 experiment.py --mode dynamic --ryu-manager "$PWD/.venv/bin/ryu-manager" --output results/dynamic
python3 compare.py
```

If the first run is interrupted, clean residual Mininet switches before
retrying:

```bash
sudo mn -c
```

The first gate is an IPv4 ping from each client to h2. The second gate is a
real UDP datagram/ACK exchange; it prints `Smoke test passed`. If either
fails, the experiment stops with the paths to `controller.log` and
`server.log`. This directly diagnoses the original all-packets-dropped issue.

### Observe forwarding and failover

While an experiment is running, a second terminal can show controller flow
rules and port status:

```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
sudo ovs-ofctl -O OpenFlow13 dump-flows s3
sudo ovs-ofctl -O OpenFlow13 dump-ports-desc s2
```

For dynamic mode, `results/dynamic/controller.log` should show `active path:
s1-s2-s4`, then `active path: s1-s3-s4` on failure, and the primary path again
after repair. The server log should show packets from **both** clients.

## Measurements and interpretation

Each client creates `h1.csv` or `h3.csv` with one row per original datagram.
`summary.json` combines both clients. `first_sent_ns`, `acked_ns` and
`server_recv_ns` are monotonic nanoseconds from processes on the **same
Mininet kernel**. The experiment records the failure and repair timestamps
with the same clock.

- **Recovery time**: time from failure injection to the first ACK for a
  datagram initially sent after the failure.
- **Unrecovered packet loss**: original datagrams still unacknowledged after
  retries and the one-second post-traffic grace interval.
- **Initial-attempt timeout rate**: fraction of original datagrams that
  required at least one retry. This estimates disrupted delivery but can
  include lost or delayed ACKs; it is not wire-level packet loss.
- **Delivery latency**: first send to ACK, including any retries.
- **Last-attempt RTT**: last send to ACK, useful for path latency without
  retransmission delay.
- **Delivered before repair**: datagrams sent during the outage and ACKed
  while the primary link was still down. This is the clearest proof of
  alternate-path operation. Static mode should normally show zero.

Client scheduling, host CPU and Open vSwitch timing affect measurements.
Repeat the two runs several times on the same VM before drawing performance
conclusions. Do not describe the local unit tests as a Mininet integration
test; the integration test is the two `experiment.py` runs above.

## Test cases for the report

1. Normal path: smoke test passes and both clients receive ACKs.
2. Primary link failure: controller logs the backup path in dynamic mode.
3. Traffic during failure: `delivered_before_restore` is positive in dynamic
   mode and normally zero in static mode.
4. Repair: controller logs the primary path again.
5. Complete route failure: if both `s2-s4` and `s3-s4` are down, the
   controller logs `active path: NONE`; application retries until a path
   returns or its retry budget expires. This can be tried in an interactive
   Mininet session or by extending the failure schedule in `experiment.py`.

## GitHub final submission

The project is ready to put in a repository. Keep generated `results/` out
of Git unless you intentionally publish verified experiment output. Add
screenshots or a short recording of the controller path changes, the smoke
test and `compare.py` output after running on Mininet. Include the VM/Ubuntu,
Python, Mininet, OVS and Ryu versions in the final report.
