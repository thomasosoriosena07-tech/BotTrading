"""Protecciones comunes de la suite (D030, fase F1).

- Red bloqueada en tiempo de ejecución en todas las pruebas: complementa
  la guarda estática de D019. Alcance (revisión de Codex): impide crear
  sockets con el módulo socket, conectar, resolver nombres y enviar
  datagramas (sendto, sendmsg). NO es un aislamiento del sistema: no
  cubre sockets creados antes del fixture (la suite no crea ninguno),
  el uso directo de _socket ni extensiones nativas o subprocesos.
- paper/ (diario oficial de T019) debe quedar idéntico tras la suite.
  Ejecutar la suite con la tarea D028 deshabilitada o fuera de su
  ventana de las 08:00, o la comprobación puede fallar por una
  actualización legítima.
"""

import hashlib
import socket
from pathlib import Path

import pytest

PAPER_DIR = Path(__file__).resolve().parents[1] / "paper"


class NetworkBlocked(RuntimeError):
    """Una prueba intentó usar la red."""


def _blocked(*args, **kwargs):
    raise NetworkBlocked("red bloqueada en las pruebas (D030)")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "__init__", _blocked)
    monkeypatch.setattr(socket.socket, "sendto", _blocked)
    monkeypatch.setattr(socket.socket, "sendmsg", _blocked, raising=False)
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    monkeypatch.setattr(socket, "socketpair", _blocked)


def paper_hashes() -> dict[str, str]:
    """SHA-256 de cada archivo de paper/, recursivo, por ruta relativa."""
    if not PAPER_DIR.is_dir():
        return {}
    return {path.relative_to(PAPER_DIR).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(PAPER_DIR.rglob("*")) if path.is_file()}


@pytest.fixture(autouse=True, scope="session")
def paper_untouched():
    before = paper_hashes()
    yield
    after = paper_hashes()
    if after != before:
        changed = sorted(n for n in before.keys() | after.keys() if before.get(n) != after.get(n))
        pytest.fail(f"la suite modificó paper/: {changed}")
