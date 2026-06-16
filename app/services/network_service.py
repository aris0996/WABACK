import socket
from urllib.parse import urlparse


def tcp_probe(url, timeout=5):
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return {"ok": False, "error": "Host URL tidak valid", "host": "", "port": port}
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"ok": True, "host": host, "port": port}
    except socket.gaierror as exc:
        return {
            "ok": False,
            "host": host,
            "port": port,
            "error": f"DNS/host tidak bisa di-resolve: {exc}",
            "hint": "Periksa hostname. Untuk Docker Linux, gunakan host.docker.internal hanya jika extra_hosts aktif.",
        }
    except socket.timeout:
        return {
            "ok": False,
            "host": host,
            "port": port,
            "error": "Connection timeout",
            "hint": "Port tidak bisa dijangkau dari container/server. Cek firewall, security group, service listen address, dan IP/port.",
        }
    except OSError as exc:
        return {
            "ok": False,
            "host": host,
            "port": port,
            "error": str(exc),
            "hint": "Service mungkin mati, port salah, atau hanya listen di 127.0.0.1.",
        }
