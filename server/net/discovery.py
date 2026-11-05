"""Sunucuyu yerel ağda bulma (UDP broadcast). (Sahibi: A)

Nasıl çalışır:
1. Öğrenci uygulaması ağdaki herkese (broadcast) "LABSINAV_DISCOVER" yazan bir UDP paketi yollar.
2. Eğitmen bilgisayarında çalışan DiscoveryResponder bu paketi alır ve
   {"service": "labsinav", "host": "<ip>", "port": 8765} cevabını yollar.
3. İstemci, cevabın GELDİĞİ adresi sunucu adresi olarak kullanır.
"""

import json
import socket
import threading

from shared import config


def get_local_ip() -> str:
    """Bu bilgisayarın yerel ağdaki IP adresi (durum çubuğunda göstermek için).

    UDP 'connect' paket göndermez; işletim sistemi sadece hangi ağ kartının
    kullanılacağını seçer. İnternet olmasa da çalışır, ağ hiç yoksa 127.0.0.1 döner.
    """
    for probe in ("10.255.255.255", "192.168.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((probe, 1))
                ip = sock.getsockname()[0]
                if not ip.startswith("0."):
                    return ip
        except OSError:
            continue
    return "127.0.0.1"


class DiscoveryResponder(threading.Thread):
    """Keşif isteklerine cevap veren arka plan thread'i."""

    def __init__(self, ws_port: int = config.WS_PORT, port: int = config.DISCOVERY_PORT) -> None:
        super().__init__(name="DiscoveryResponder", daemon=True)
        self.ws_port = ws_port
        self._stop_event = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("", port))  # bağlanamazsa OSError — çağıran yakalar
        self.port = self._sock.getsockname()[1]  # port=0 verildiyse (testler) gerçek port
        self._sock.settimeout(0.5)   # stop() kontrolü için periyodik uyanma

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                data, addr = self._sock.recvfrom(1024)
            except TimeoutError:
                continue
            except OSError:
                break  # soket kapatıldı
            if data.strip() == config.DISCOVERY_MAGIC:
                self._reply(addr)

    def _reply(self, addr: tuple[str, int]) -> None:
        answer = {"service": config.SERVICE_NAME, "host": get_local_ip(), "port": self.ws_port}
        try:
            self._sock.sendto(json.dumps(answer).encode("utf-8"), addr)
        except OSError:
            pass  # tek bir cevabın gidememesi dinleyiciyi durdurmamalı

    def stop(self) -> None:
        self._stop_event.set()
        self._sock.close()


def _parse_answer(data: bytes) -> int | None:
    """Geçerli bir LabSınav cevabıysa WebSocket portunu döner."""
    try:
        answer = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(answer, dict) or answer.get("service") != config.SERVICE_NAME:
        return None
    port = answer.get("port")
    return port if isinstance(port, int) else None


def discover_server(
    timeout: float = config.DISCOVERY_TIMEOUT_SEC, port: int = config.DISCOVERY_PORT
) -> tuple[str, int] | None:
    """Ağdaki LabSınav sunucusunu arar. Bulursa (ip, ws_port), bulamazsa None döner.

    Bloklayan bir fonksiyondur: arayüzden çağırırken ayrı thread kullanın.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        # Önce tüm ağa, sonra aynı bilgisayara (tek makinede deneme için) sor.
        for target in ("255.255.255.255", "127.0.0.1"):
            try:
                sock.sendto(config.DISCOVERY_MAGIC, (target, port))
            except OSError:
                continue  # ör. ağ kartı yoksa broadcast başarısız olur
        try:
            while True:
                data, addr = sock.recvfrom(1024)
                ws_port = _parse_answer(data)
                if ws_port is not None:
                    host = addr[0]
                    return host, ws_port
        except (TimeoutError, OSError):
            return None
