import subprocess
import sys
from pathlib import Path

from src import main as cli


def test_importing_cli_does_not_load_tesseract():
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import src.main; print('pytesseract' in sys.modules)",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"


def test_cli_reports_pdf_before_detection(monkeypatch, tmp_path, capsys):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"")
    output_path = tmp_path / "output"
    output_before_detection = []
    ocr_settings = []

    def detect(pdf, use_ocr):
        output_before_detection.append(capsys.readouterr().out)
        ocr_settings.append(use_ocr)
        return []

    monkeypatch.setattr(cli, "detect_tables", detect)
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", str(pdf_path), "--output", str(output_path)],
    )

    cli.main()

    assert output_before_detection == ["Processing sample.pdf...\n"]
    assert ocr_settings == [True]
    assert "sample.pdf: 0 table(s)" in capsys.readouterr().out
