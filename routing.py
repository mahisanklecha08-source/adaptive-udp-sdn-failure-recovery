"""Fixed lab wiring and pure path-selection helpers.

The numeric ports are deliberately pinned in topology.py.  Never infer a
switch port from creation order when programming OpenFlow rules.
"""

SWITCH_PORTS = {
    (1, 2): 2, (2, 1): 1,
    (2, 4): 2, (4, 2): 1,
    (1, 3): 3, (3, 1): 1,
    (3, 4): 2, (4, 3): 2,
}
LINKS = ((1, 2), (2, 4), (1, 3), (3, 4))
CLIENTS = {
    "10.0.0.1": 1,  # h1 -> s1 port 1
    "10.0.0.3": 4,  # h3 -> s1 port 4
}
SERVER_IP = "10.0.0.2"
SERVER_PORT = 3  # h2 -> s4 port 3


def edge(a, b):
    return tuple(sorted((a, b)))


def choose_path(down_links=(), active_switches=(1, 2, 3, 4)):
    """Choose the primary diamond branch, or the alternate if unavailable."""
    down = {edge(*link) for link in down_links}
    active = set(active_switches)
    for candidate in ((1, 2, 4), (1, 3, 4)):
        if all(node in active for node in candidate) and all(
            edge(a, b) not in down for a, b in zip(candidate, candidate[1:])
        ):
            return candidate
    return None


def forwarding_ports(path, client_port):
    """Return per-switch output ports for client->server and server->client."""
    forward = {}
    reverse = {}
    for index, switch in enumerate(path):
        forward[switch] = (SWITCH_PORTS[(switch, path[index + 1])]
                           if index + 1 < len(path) else SERVER_PORT)
        reverse[switch] = (SWITCH_PORTS[(switch, path[index - 1])]
                           if index else client_port)
    return forward, reverse
