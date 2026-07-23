"""Тесты якоря реальности.

Главные здесь — не те, что проверяют «работает», а те, что проверяют
«нельзя обмануть»: попытка передать мнение вместо доказательства должна
падать, а несостоявшаяся проверка — считаться непройденной.
"""

from __future__ import annotations

import http.server
import threading
import urllib.parse
import time

import pytest

from first_graph.anchors import anchor
from first_graph.graph import Trace

# ─────────────────────────────────────────────────────────────
# ГЛАВНОЕ: якорь отказывается принимать мнение
# ─────────────────────────────────────────────────────────────


def test_лямбда_вместо_команды_это_ошибка():
    with pytest.raises(TypeError, match="не принимает функцию"):
        anchor({}, command=lambda s: True)  # type: ignore[arg-type]


def test_лямбда_вместо_файла_это_ошибка():
    with pytest.raises(TypeError, match="не принимает функцию"):
        anchor({}, file=lambda s: True)  # type: ignore[arg-type]


def test_лямбда_вместо_адреса_это_ошибка():
    with pytest.raises(TypeError, match="не принимает функцию"):
        anchor({}, url=lambda s: True)  # type: ignore[arg-type]


def test_ошибка_объясняет_куда_идти_за_проверкой_логикой():
    with pytest.raises(TypeError, match="gate"):
        anchor({}, command=lambda s: True)  # type: ignore[arg-type]


def test_строка_вместо_списка_аргументов_это_ошибка():
    # Защита от shell-инъекций: только список аргументов.
    with pytest.raises(TypeError, match="список аргументов"):
        anchor({}, command="pytest -q")  # type: ignore[arg-type]


def test_без_доказательства_это_ошибка():
    with pytest.raises(ValueError, match="ровно один"):
        anchor({})


def test_два_доказательства_сразу_это_ошибка():
    with pytest.raises(ValueError, match="ровно один"):
        anchor({}, command=["true"], url="https://example.com")


# ─────────────────────────────────────────────────────────────
# Команда
# ─────────────────────────────────────────────────────────────


def test_команда_с_нулевым_кодом_проходит():
    state, passed = anchor({}, command=["python3", "-c", "raise SystemExit(0)"])

    assert passed is True
    assert state["anchors"][-1].passed is True
    assert "код возврата 0" in state["anchors"][-1].detail


def test_команда_с_ненулевым_кодом_не_проходит():
    state, passed = anchor({}, command=["python3", "-c", "raise SystemExit(3)"])

    assert passed is False
    assert "код 3" in state["anchors"][-1].detail


def test_в_причине_видно_последнюю_строку_ошибки():
    state, passed = anchor(
        {},
        command=[
            "python3",
            "-c",
            "import sys; print('сломалось на строке 14', file=sys.stderr); sys.exit(1)",
        ],
    )

    assert passed is False
    assert "сломалось на строке 14" in state["anchors"][-1].detail


def test_несуществующая_команда_это_НЕ_пройдено_а_не_падение():
    # Отказ в сторону безопасности: не смогли проверить — значит не доказано.
    state, passed = anchor({}, command=["такой-команды-нет-12345"])

    assert passed is False
    assert "не найдена" in state["anchors"][-1].detail


def test_таймаут_это_не_пройдено():
    state, passed = anchor(
        {}, command=["python3", "-c", "import time; time.sleep(5)"], timeout=0.3
    )

    assert passed is False
    assert "таймаут" in state["anchors"][-1].detail


# ─────────────────────────────────────────────────────────────
# Файл
# ─────────────────────────────────────────────────────────────


def test_существующий_файл_проходит(tmp_path):
    target = tmp_path / "app.apk"
    target.write_text("собрано")

    _, passed = anchor({}, file=target)

    assert passed is True


def test_отсутствующий_файл_не_проходит(tmp_path):
    _, passed = anchor({}, file=tmp_path / "нет.apk")

    assert passed is False


def test_свежий_артефакт_проходит(tmp_path):
    source = tmp_path / "src.py"
    source.write_text("код")
    time.sleep(0.01)
    built = tmp_path / "app.apk"
    built.write_text("сборка")

    _, passed = anchor({}, file=built, newer_than=source)

    assert passed is True


def test_устаревший_артефакт_не_проходит(tmp_path):
    # Классика: сборка есть, но старее исходников — значит не пересобрали.
    built = tmp_path / "app.apk"
    built.write_text("старая сборка")
    time.sleep(0.01)
    source = tmp_path / "src.py"
    source.write_text("новый код")

    state, passed = anchor({}, file=built, newer_than=source)

    assert passed is False
    assert "не пересобран" in state["anchors"][-1].detail


def test_свежесть_папки_считается_по_самому_новому_файлу(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "старый.py").write_text("a")
    built = tmp_path / "app.apk"
    built.write_text("сборка")
    time.sleep(0.01)
    (src_dir / "новый.py").write_text("b")  # правка после сборки

    _, passed = anchor({}, file=built, newer_than=src_dir)

    assert passed is False


# ─────────────────────────────────────────────────────────────
# Адрес
# ─────────────────────────────────────────────────────────────


class _Тихий(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — имя задано базовым классом
        # Раскодируем путь: якорь присылает кириллицу percent-encoded
        path = urllib.parse.unquote(self.path)
        code = 200 if path in ("/health", "/здоровье") else 503
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # глушим лог в stderr
        pass


@pytest.fixture
def сервер():
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Тихий)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_живой_адрес_проходит(сервер):
    _, passed = anchor({}, url=f"{сервер}/health")

    assert passed is True


def test_неожиданный_статус_не_проходит(сервер):
    state, passed = anchor({}, url=f"{сервер}/broken")

    assert passed is False
    assert "503" in state["anchors"][-1].detail


def test_можно_ждать_несколько_статусов(сервер):
    _, passed = anchor({}, url=f"{сервер}/broken", expect={200, 503})

    assert passed is True


def test_мёртвый_адрес_это_не_пройдено():
    _, passed = anchor({}, url="http://127.0.0.1:1/nope", timeout=1)

    assert passed is False


# ─────────────────────────────────────────────────────────────
# Доказательства копятся и попадают в трассу
# ─────────────────────────────────────────────────────────────


def test_доказательства_накапливаются_в_состоянии():
    state, _ = anchor({}, command=["python3", "-c", ""])
    state, _ = anchor(state, command=["python3", "-c", "raise SystemExit(1)"])

    assert len(state["anchors"]) == 2
    assert [e.passed for e in state["anchors"]] == [True, False]


def test_якорь_не_мутирует_исходное_состояние():
    original = {"задача": "собрать"}

    anchor(original, command=["python3", "-c", ""])

    assert "anchors" not in original


def test_якорь_пишется_в_трассу():
    trace = Trace()

    anchor({}, command=["python3", "-c", "raise SystemExit(1)"], trace=trace)

    assert len(trace.failed) == 1
    assert "anchor:command" in str(trace)


def test_доказательство_читаемо_глазами():
    state, _ = anchor({}, command=["python3", "-c", ""])

    assert str(state["anchors"][-1]).startswith("✓ якорь [command]")


def test_кириллица_в_адресе_не_роняет_якорь(сервер):
    # Рунет: домены и пути на кириллице — норма. Якорь обязан их пережить,
    # а не упасть UnicodeEncodeError посреди графа.
    _, passed = anchor({}, url=f"{сервер}/здоровье")

    assert passed is True


def test_совсем_кривой_адрес_это_не_пройдено():
    state, passed = anchor({}, url="не адрес вовсе", timeout=1)

    assert passed is False
    assert state["anchors"][-1].passed is False
