"""firewall.sh / uninstall.sh: open the panel's ports to local networks, and remove exactly those rules.

Runs the real scripts with fake sudo, ufw, ip and systemctl first on PATH and a temporary HOME, so
nothing on this PC is changed."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]

IP_JSON = json.dumps([
    {"ifname": "lo", "flags": ["LOOPBACK", "UP"], "addr_info": [{"local": "127.0.0.1", "prefixlen": 8}]},
    {"ifname": "eno1", "flags": ["BROADCAST", "UP"], "addr_info": [{"local": "192.168.1.80", "prefixlen": 24}]},
    {"ifname": "wlx9cefd5fa3634", "flags": ["BROADCAST", "UP"], "addr_info": [{"local": "192.168.86.151", "prefixlen": 24}]},
    {"ifname": "docker0", "flags": ["BROADCAST", "UP"], "addr_info": [{"local": "172.17.0.1", "prefixlen": 16}]},
    {"ifname": "enp9s0", "flags": ["BROADCAST"], "addr_info": [{"local": "10.9.0.2", "prefixlen": 24}]},  # down
    {"ifname": "eno2", "flags": ["UP"], "addr_info": [{"local": "203.0.113.5", "prefixlen": 24}]},  # public
])

STATUS = textwrap.dedent("""\
    Status: active

    To                         Action      From
    --                         ------      ----
    Anywhere on eno1           ALLOW       192.168.1.0/24             # Trusted local network
    9943/udp                   ALLOW       192.168.86.0/24            # Intel XR ALVR control
    8083,8483/tcp              ALLOW       192.168.86.0/24            # XR Control Panel (LAN)
    8083,8483/tcp              ALLOW       192.168.1.0/24             # XR Control Panel (LAN)
    8083/tcp                   ALLOW       10.0.0.0/8                 # XR Control Panel (LAN) old copy
    8083,8483/tcp              ALLOW       Anywhere                   # XR Control Panel (LAN)
    22/tcp                     ALLOW       192.168.86.0/24            # XR Control Panel (LAN)x
    8083,8483/tcp (v6)         ALLOW       fd00::/64                  # XR Control Panel (LAN)
    """)


class FirewallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.bin, self.home, self.log = d / "bin", d / "home", d / "calls.log"
        self.bin.mkdir()
        self.home.mkdir()
        (d / "status.txt").write_text(STATUS)
        (d / "ip.json").write_text(IP_JSON)
        self.fake("sudo", f'''
            if [ "$1" = "-n" ]; then [ -f "{d}/no-sudo" ] && exit 1; shift; fi
            exec "$@"''')
        self.fake("ufw", f'''
            echo "ufw $*" >> "{self.log}"
            if [ "$1" = "status" ]; then cat "{d}/status.txt"; else echo "Rule added"; fi''')
        self.fake("ip", f'cat "{d}/ip.json"')
        self.fake("systemctl", f'echo "systemctl $*" >> "{self.log}"')
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", HOME=str(self.home))
        self.config = d / "config.json"
        self.config.write_text(json.dumps({"port": 8083, "https_port": 8483, "lan_access": True}))

    def tearDown(self):
        self.tmp.cleanup()

    def fake(self, name, body):
        f = self.bin / name
        f.write_text("#!/bin/sh\n" + textwrap.dedent(body).strip() + "\n")
        f.chmod(0o755)

    def run_script(self, *args, script="firewall.sh"):
        return subprocess.run(["bash", str(ROOT / script), *args], env=self.env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=30)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_show_uses_private_up_interfaces_and_config_ports(self):
        self.config.write_text(json.dumps({"port": 9083, "https_port": 9483}))
        out = self.run_script("show", "--config", str(self.config)).stdout.splitlines()
        self.assertEqual(out, [
            r"sudo ufw allow from 192.168.1.0/24 to any port 9083,9483 proto tcp comment XR\ Control\ Panel\ \(LAN\)",
            r"sudo ufw allow from 192.168.86.0/24 to any port 9083,9483 proto tcp comment XR\ Control\ Panel\ \(LAN\)"])
        self.assertEqual(self.calls(), [])

    def test_allow_adds_one_rule_per_network(self):
        r = self.run_script("allow", "--config", str(self.config))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c for c in self.calls() if c != "ufw status"], [
            "ufw allow from 192.168.1.0/24 to any port 8083,8483 proto tcp comment XR Control Panel (LAN)",
            "ufw allow from 192.168.86.0/24 to any port 8083,8483 proto tcp comment XR Control Panel (LAN)"])
        r = self.run_script("allow", "--subnet", "not-a-net", "--subnet", "10.1.0.0/16")
        self.assertIn("skipping invalid subnet", r.stderr)
        self.assertIn("ufw allow from 10.1.0.0/16 to any port 8083,8483 proto tcp comment XR Control Panel (LAN)",
                      self.calls())

    def test_remove_deletes_only_exact_ipv4_panel_rules(self):
        r = self.run_script("remove")
        self.assertEqual(r.returncode, 0, r.stderr)
        deletes = [c for c in self.calls() if c.startswith("ufw delete")]
        self.assertEqual(deletes, [
            "ufw delete allow from 192.168.86.0/24 to any port 8083,8483 proto tcp",
            "ufw delete allow from 192.168.1.0/24 to any port 8083,8483 proto tcp"])
        self.assertFalse(any("--force" in c or c.split()[2:3] and c.split()[2].isdigit() for c in deletes))

    def test_inactive_ufw_or_no_sudo_changes_nothing(self):
        (Path(self.tmp.name) / "status.txt").write_text("Status: inactive\n")
        self.assertIn("not active", self.run_script("allow").stdout)
        self.assertIn("not active", self.run_script("remove").stdout)
        self.assertEqual(self.calls(), ["ufw status"] * 2)
        self.log.unlink()
        (Path(self.tmp.name) / "no-sudo").touch()
        out = self.run_script("allow", "--config", str(self.config)).stdout
        self.assertIn("needs sudo", out)
        self.assertIn(r"sudo ufw allow from 192.168.86.0/24 to any port 8083,8483 proto tcp comment XR\ Control", out)
        self.assertEqual(self.calls(), [])

    def test_uninstall_refuses_what_is_not_a_panel_install(self):
        not_panel = Path(self.tmp.name) / "photos"
        not_panel.mkdir()
        (not_panel / "keep.jpg").write_text("x")
        for prefix in (str(not_panel), "/", str(self.home)):
            r = self.run_script("--prefix", prefix, script="uninstall.sh")
            self.assertEqual(r.returncode, 1, prefix)
            self.assertIn("does not look like an XR Control Panel installation", r.stderr)
        self.assertTrue((not_panel / "keep.jpg").exists())
        self.assertEqual(self.calls(), [])  # refused before stopping or changing anything

    def test_uninstall_removes_app_service_and_panel_rules(self):
        app = self.home / ".local/share/xr-control-panel/app"
        app.mkdir(parents=True)
        (app / "server.py").write_text("")
        (app / "usb_pairing.py").write_text("")
        captures = self.home / ".local/share/xr-control-panel/captures"
        captures.mkdir()
        unit = self.home / ".config/systemd/user/xr-control-panel.service"
        unit.parent.mkdir(parents=True)
        unit.write_text("")
        r = self.run_script(script="uninstall.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(app.exists())
        self.assertFalse(unit.exists())
        self.assertTrue(captures.exists())  # kept without --purge
        calls = self.calls()
        self.assertIn("systemctl --user disable --now xr-control-panel.service", calls)
        self.assertEqual(len([c for c in calls if c.startswith("ufw delete")]), 2)
        self.log.unlink()
        app.mkdir()
        (app / "server.py").write_text("")
        (app / "tablet_client.py").write_text("")
        self.run_script("--keep-firewall", script="uninstall.sh")
        self.assertFalse(any(c.startswith("ufw") for c in self.calls()))


if __name__ == "__main__":
    unittest.main()
