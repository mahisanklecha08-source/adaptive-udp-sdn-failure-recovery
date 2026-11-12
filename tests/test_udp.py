import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from udp_app import ACK, ACK_MAGIC, DATA, DATA_MAGIC


APP = Path(__file__).resolve().parents[1] / "udp_app.py"


class UdpTests(unittest.TestCase):
    def test_packet_wire_format(self):
        self.assertEqual(DATA.unpack(DATA.pack(DATA_MAGIC, 7, 123)), (DATA_MAGIC, 7, 123))
        self.assertEqual(ACK.unpack(ACK.pack(ACK_MAGIC, 7, 123, 456)),
                         (ACK_MAGIC, 7, 123, 456))

    def test_localhost_acknowledgement(self):
        # Some CI sandboxes allow bind/sendto but suppress local UDP delivery.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as loopback:
            loopback.bind(("127.0.0.1", 0))
            loopback.settimeout(0.2)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                sender.sendto(b"probe", loopback.getsockname())
                try:
                    loopback.recvfrom(32)
                except socket.timeout:
                    self.skipTest("local UDP delivery is blocked by this sandbox")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with tempfile.TemporaryDirectory(dir=APP.parent) as temp:
            prefix = Path(temp) / "probe"
            server = subprocess.Popen([sys.executable, str(APP), "server", "--bind-ip", "127.0.0.1", "--port", str(port)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                time.sleep(0.2)
                client = subprocess.run([sys.executable, str(APP), "client", "--bind-ip", "127.0.0.1",
                                "--server-ip", "127.0.0.1", "--port", str(port),
                                "--duration", "0.4", "--rate", "10", "--grace", "0.3",
                                "--output", str(prefix)], capture_output=True, text=True, timeout=10)
                self.assertEqual(client.returncode, 0, client.stderr)
                result = json.loads(prefix.with_suffix(".json").read_text())
                self.assertGreaterEqual(result["acknowledged"], 3)
                self.assertEqual(result["unrecovered"], 0)
            finally:
                server.terminate()
                server.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
