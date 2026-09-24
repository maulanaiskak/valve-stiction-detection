from unittest.mock import MagicMock

from detector import DetectionResult, WindowInput
from persist import persist


def test_persist_writes_one_row_and_commits():
    db_conn = MagicMock()
    window = WindowInput("valve-1", [1.0, 2.0], [3.0, 4.0], 12345)
    result = DetectionResult(
        label="yes",
        ellipse_index=0.9,
        kano_verdict=True,
        has_activity=True,
        rf_label="yes",
        rf_probability=0.87,
    )

    persist(db_conn, window, result)

    db_conn.cursor.return_value.__enter__.return_value.execute.assert_called_once()
    db_conn.commit.assert_called_once()
