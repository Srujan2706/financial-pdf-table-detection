import csv, json
from src.result_exporter import export_results

def test_export_schema_and_values(tmp_path):
    rows = [{"Table Title": "Balance Sheet", "Page Number": 2, "ignored": "x"}]
    csv_path, json_path = export_results(rows, tmp_path, "sample")
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        assert next(csv.DictReader(f)) == {"Table Title": "Balance Sheet", "Page Number": "2"}
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload == [{"Table Title": "Balance Sheet", "Page Number": 2}]
    assert list(payload[0]) == ["Table Title", "Page Number"]
