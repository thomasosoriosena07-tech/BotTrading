"""Validación de lo publicable (D030 punto 7, F2b-3): sin red ni escritura en paper/."""

import hashlib
import zipfile

import pytest

import bottrading.publication as publication
from bottrading.publication import PUBLISHABLE, PublicationError, main, validate_files

from conftest import PAPER_DIR

LEDGER_HEADER = ("symbol,side,signal_time,execution_time,reference_price,price,quantity,fee,"
                 "slippage_cost,cash_after\n")
ROW = ("BTCUSDT,buy,2026-08-17T00:00:00+00:00,2026-10-01T00:00:00+00:00,83623.59,83665.4,"
       "0.1194,9.99,4.99,0.0\n")


def anchor(ledger: bytes, rows: int, day="2026-10-13") -> bytes:
    return f"last_day={day}\nrows={rows}\nsha256={hashlib.sha256(ledger).hexdigest()}\n".encode()


def good_files() -> dict[str, bytes]:
    ledger = (LEDGER_HEADER + ROW).encode()
    return {
        "paper/ledger.csv": ledger,
        "paper/ledger.state": anchor(ledger, 1),
        "paper/equity.csv": b"date,symbol,strategy_equity,buy_and_hold_equity\n"
                            b"2026-10-01,BTCUSDT,10135.04,10135.04\n",
        "paper/report.md": "# Paper trading\n\nSimulación sin dinero.\n".encode(),
        "paper/dashboard.html": b"<!doctype html><svg viewBox='0 0 1 1'></svg>",
    }


def zip_of(tmp_path, files, name="pub.zip"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for member, content in files.items():
            archive.writestr(member, content)
    return path


def test_real_committed_paper_files_are_publishable(tmp_path):
    files = {name: (PAPER_DIR.parent / name).read_bytes() for name in PUBLISHABLE}
    assert main([str(zip_of(tmp_path, files))]) == 0


def test_synthetic_good_files_are_publishable():
    validate_files(good_files())


@pytest.mark.parametrize("change", ["extra", "missing", "renamed"])
def test_only_the_closed_list_can_be_published(tmp_path, change, capsys):
    files = good_files()
    if change == "extra":
        files["paper/notas.txt"] = b"x"
    elif change == "missing":
        del files["paper/report.md"]
    else:
        files["paper/Report.md"] = files.pop("paper/report.md")
    assert main([str(zip_of(tmp_path, files))]) == 1
    assert "lista cerrada" in capsys.readouterr().out


@pytest.mark.parametrize("row", [
    ROW.replace("BTCUSDT", "BNBUSDT"),
    ROW.replace(",buy,", ",short,"),
    ROW.replace("2026-08-17T00:00:00+00:00", "2026-08-17T00:00:00"),  # sin zona
    ROW.replace("2026-08-17T00:00:00+00:00", "17/08/2026"),
    ROW.replace("83623.59", "nan"),
    ROW.replace("83623.59", "inf"),
    ROW.replace("0.0\n", "0.0,extra\n"),
    ROW.replace("\n", "\r\n"),
])
def test_ledger_schema_is_closed(row):
    files = good_files()
    ledger = (LEDGER_HEADER + row).encode()
    files["paper/ledger.csv"] = ledger
    files["paper/ledger.state"] = anchor(ledger, 1)
    with pytest.raises(PublicationError, match="ledger.csv"):
        validate_files(files)


@pytest.mark.parametrize("state", [
    lambda ledger: anchor(ledger, 2),
    lambda ledger: anchor(ledger + b"x", 1),
    lambda ledger: anchor(ledger, 1, "2026-13-40"),
    lambda ledger: anchor(ledger, 1) + b"extra=1\n",
    lambda ledger: anchor(ledger, 1).replace(b"\n", b"\r\n"),
])
def test_anchor_must_match_the_ledger(state):
    files = good_files()
    files["paper/ledger.state"] = state(files["paper/ledger.csv"])
    with pytest.raises(PublicationError, match="ledger.state"):
        validate_files(files)


@pytest.mark.parametrize("row", [
    b"2026-10-1,BTCUSDT,1,1\n", b"2026-10-01,XRPUSDT,1,1\n", b"2026-10-01,BTCUSDT,abc,1\n",
    b"2026-10-01,BTCUSDT,1\n",
])
def test_equity_schema_is_closed(row):
    files = good_files()
    files["paper/equity.csv"] = b"date,symbol,strategy_equity,buy_and_hold_equity\n" + row
    with pytest.raises(PublicationError, match="equity.csv"):
        validate_files(files)


@pytest.mark.parametrize(("name", "content"), [
    ("paper/dashboard.html", b"<html><script>alert(1)</script></html>"),
    ("paper/dashboard.html", b"<img src='https://evil.example/x.png'>"),
    ("paper/dashboard.html", b"<link href='//cdn.example.com/a.css'>"),
    ("paper/report.md", b"ver http://example.com"),
])
def test_scripts_and_external_urls_are_refused(name, content):
    files = good_files()
    files[name] = content
    with pytest.raises(PublicationError, match="no permitido|scripts o URLs"):
        validate_files(files)


@pytest.mark.parametrize("html", [
    "<img src=x onerror=alert(1)>",  # revisión de Codex: atributo de evento
    "<div onclick='x()'>a</div>",
    "<svg onload=alert(1)></svg>",
    "<a href='javascript:alert(1)'>a</a>",
    "<p style='background: url(x)'>a</p>",
    "<p style='color: red'>a</p>",
    "<meta http-equiv='refresh' content='0;url=x'>",
    "<style>@import 'x.css';</style>",
    "<style>body { background: url(x) }</style>",
    "<iframe></iframe>",
    "<object></object>",
    "<base>",
    "<form></form>",
    "<?xml-stylesheet href='x'?>",
])
def test_dashboard_only_allows_whitelisted_tags_and_attributes(html):
    files = good_files()
    files["paper/dashboard.html"] = f"<!doctype html><html><body>{html}</body></html>".encode()
    with pytest.raises(PublicationError, match="no permitido"):
        validate_files(files)


def test_dashboard_whitelist_accepts_what_dashboard_py_generates():
    files = good_files()
    files["paper/dashboard.html"] = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>x</title><style>:root { --strategy: #123456 }</style></head><body>"
        '<span><i style="background: var(--strategy)"></i>a</span>'
        '<svg viewBox="0 0 10 10" role="img" aria-label="t"><title>t</title>'
        '<line class="grid" x1="0" x2="1" y1="0" y2="1"></line>'
        '<polyline points="0,0 1,1"></polyline><text x="1" y="1" text-anchor="end">1</text></svg>'
        "</body></html>").encode()
    validate_files(files)


@pytest.mark.parametrize("report", [
    "# Informe\n<b>negrita</b>\n", "# Informe\n<!-- comentario -->\n",
    "# Informe\n[pulsa](javascript:alert(1))\n", "# Informe\n![img](x.png)\n",
    "# Informe\njavascript:alert(1)\n",
])
def test_report_has_no_html_or_links(report):
    files = good_files()
    files["paper/report.md"] = report.encode()
    with pytest.raises(PublicationError, match="report.md"):
        validate_files(files)


@pytest.mark.parametrize("value", ["1_000", " 1", "+1", "1.", ".5", "0x10", "1e", "١٢"])
def test_numbers_must_use_the_closed_decimal_format(value):
    files = good_files()
    files["paper/equity.csv"] = (b"date,symbol,strategy_equity,buy_and_hold_equity\n"
                                 + f"2026-10-01,BTCUSDT,{value},1\n".encode())
    with pytest.raises(PublicationError, match="equity.csv"):
        validate_files(files)


@pytest.mark.parametrize("value", ["0.0", "-3.5", "1e-05", "1.2e+20", "10135.04422688642"])
def test_repr_float_formats_are_accepted(value):
    files = good_files()
    files["paper/equity.csv"] = (b"date,symbol,strategy_equity,buy_and_hold_equity\n"
                                 + f"2026-10-01,BTCUSDT,{value},1\n".encode())
    validate_files(files)


@pytest.mark.parametrize("leak", [
    "apiKey=abc", "X-MBX-APIKEY: abc", "secret", "signature=abc", "api_key",
    "vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A",  # clave de ejemplo
])
def test_credential_patterns_are_refused(leak):
    files = good_files()
    files["paper/report.md"] = f"# Informe\n{leak}\n".encode()
    with pytest.raises(PublicationError, match="credencial"):
        validate_files(files)


def test_lowercase_sha256_is_not_mistaken_for_a_key():
    files = good_files()
    files["paper/report.md"] = ("hash " + hashlib.sha256(b"x").hexdigest() + "\n").encode()
    validate_files(files)


def test_non_utf8_and_oversized_files_are_refused(tmp_path, monkeypatch, capsys):
    files = good_files()
    files["paper/report.md"] = "Simulación".encode("latin-1")
    with pytest.raises(PublicationError, match="UTF-8"):
        validate_files(files)
    monkeypatch.setattr(publication, "MAX_BYTES", 10)
    assert main([str(zip_of(tmp_path, good_files()))]) == 1
    assert "tamaño excesivo" in capsys.readouterr().out


def test_missing_or_corrupt_archive_is_rejected_without_traceback(tmp_path, capsys):
    assert main([str(tmp_path / "no-existe.zip")]) == 1
    (tmp_path / "roto.zip").write_bytes(b"no es un zip")
    assert main([str(tmp_path / "roto.zip")]) == 1
    assert capsys.readouterr().out.count("PUBLICACION RECHAZADA") == 2


# --- revisión de Codex de 1910866 -----------------------------------------------------


def dashboard_with(fragment, head=""):
    files = good_files()
    files["paper/dashboard.html"] = (
        f"<!doctype html><html><head>{head}</head><body>{fragment}</body></html>").encode()
    return files


@pytest.mark.parametrize("fragment", [
    "<!--[if IE]><script>alert(1)</script><![endif]-->",  # evasión de Codex
    "<!-- comentario cualquiera -->",
    "<![CDATA[x]]>",
])
def test_html_comments_and_cdata_are_refused(fragment):
    with pytest.raises(PublicationError, match="comentario HTML|declaración"):
        validate_files(dashboard_with(fragment))


def test_only_the_html5_doctype_is_allowed():
    files = good_files()
    files["paper/dashboard.html"] = b'<!DOCTYPE html SYSTEM "x"><html></html>'
    with pytest.raises(PublicationError, match="declaración"):
        validate_files(files)


@pytest.mark.parametrize("css", [
    r"a{background:u\72l(\2f\2fevil.example/x)}",  # evasión de Codex: url() con escapes
    "a{background:url(x.png)}",
    "a{background:image-set(\"x.png\" 1x)}",
    "a{width:expression(alert(1))}",
    "@import \"x.css\";",
    "@font-face{font-family:x;src:local(x)}",
    "a{background:u/**/rl(x)}",
    "a{content:'x'}",
    "a{background:-webkit-image-set(\"x\" 1x)}",
    "a{background:URL(x)}",
])
def test_css_is_allowlisted(css):
    with pytest.raises(PublicationError, match="CSS"):
        validate_files(dashboard_with("", f"<style>{css}</style>"))


def test_css_generated_by_dashboard_py_is_accepted():
    css = (':root{--strategy:#123}[data-theme="dark"]{--strategy:#456}'
           "@media (prefers-color-scheme: dark){:root{--strategy:#789}}"
           ".grid{grid-template-columns:repeat(auto-fit, minmax(16rem, 1fr));"
           "color:var(--strategy)}")
    validate_files(dashboard_with("", f"<style>{css}</style>"))


@pytest.mark.parametrize("text", [
    "www.example.com",  # revisión de Codex: autoenlace sin //
    "WWW.Example.org/x", "contacto: alguien@example.com", "mailto:alguien",
    "data:text/html;base64,PHNjcmlwdD4=", "vbscript:x", "ftp://example.com",
])
def test_linkable_text_is_refused_in_report_and_dashboard(text):
    files = good_files()
    files["paper/report.md"] = f"# Informe\n{text}\n".encode()
    with pytest.raises(PublicationError, match="report.md"):
        validate_files(files)
    with pytest.raises(PublicationError, match="dashboard.html"):
        validate_files(dashboard_with(f"<p>{text}</p>"))


@pytest.mark.parametrize("report", [
    "Ver [ledger][ref]\n\n[ref]: paper/ledger.csv\n",  # revisión de Codex: referencia
    "Ver [ledger]\n\n[ledger]: paper/ledger.csv\n",  # referencia abreviada
    "Nota[^1]\n\n[^1]: detalle\n",  # nota al pie
    "![grafico][img]\n\n[img]: x.png\n",
    "[ref]: paper/ledger.csv\n",
])
def test_reference_links_footnotes_and_brackets_are_refused(report):
    files = good_files()
    files["paper/report.md"] = f"# Informe\n{report}".encode()
    with pytest.raises(PublicationError, match="report.md"):
        validate_files(files)


def test_ordinary_report_text_with_file_names_is_accepted():
    files = good_files()
    files["paper/report.md"] = ("# Informe\nProtocolo en DECISIONS.md D027; datos en "
                                "paper/ledger.csv. Retorno: -0.84 %.\n").encode()
    validate_files(files)
