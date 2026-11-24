import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test_server"))

from local_smtp_server import DEFAULT_USERS, ensure_certs, start_servers, stop_servers

from dispatcher import Credentials, SecurityMode, SMTPConfig

ensure_certs()

USER, PASSWORD = next(iter(DEFAULT_USERS.items()))
MAX_SIZE = 200_000


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    ca, _, _ = ensure_certs()
    ports = {"starttls": free_port(), "ssl": free_port()}
    inbox = tmp_path_factory.mktemp("inbox")
    controllers, handler = start_servers(ports["starttls"], ports["ssl"], inbox=inbox,
                                         max_size=MAX_SIZE, quiet=True)
    yield {"ports": ports, "ca": str(ca), "handler": handler}
    stop_servers(controllers)


@pytest.fixture
def starttls_cfg(server):
    return SMTPConfig("t", "localhost", server["ports"]["starttls"], SecurityMode.STARTTLS,
                      timeout=5, ca_file=server["ca"])


@pytest.fixture
def ssl_cfg(server):
    return SMTPConfig("t", "localhost", server["ports"]["ssl"], SecurityMode.SSL,
                      timeout=5, ca_file=server["ca"])


@pytest.fixture
def creds():
    return Credentials(USER, PASSWORD)
