from pathlib import Path
import hashlib
import pandas as pd
import numpy as np


def utc(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError(f"Timestamp must specify timezone (use Z): {value}")
    return stamp.tz_convert("UTC")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_bars(path):
    """Bitget JSONL arrays or canonical CSV. Timestamp denotes START of 1m bar."""
    path = Path(path)
    if path.suffix == ".jsonl":
        frame = pd.read_json(path, lines=True, convert_dates=False)
        if frame.shape[1] < 6:
            raise ValueError("Bitget candles require timestamp, OHLC and base volume")
        frame = frame.iloc[:, :6]
        frame.columns = ["timestamp", "open", "high", "low", "close", "volume"]
        frame["timestamp"] = pd.to_datetime(pd.to_numeric(frame.timestamp), unit="ms", utc=True)
    else:
        frame = pd.read_csv(path)
        frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    if not set(required) <= set(frame):
        raise ValueError(f"Required columns: {required}")
    frame = frame[required].copy()
    for col in required[1:]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    exact_duplicates = int(frame.duplicated().sum())
    frame = frame.drop_duplicates()
    if frame.timestamp.duplicated().any():
        raise ValueError(f"Conflicting duplicate candles: {path}")
    prices = frame[["open", "high", "low", "close"]]
    if not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any():
        raise ValueError(f"Nonpositive/missing/nonfinite OHLC: {path}")
    if frame.timestamp.isna().any() or (frame.timestamp != frame.timestamp.dt.floor("min")).any():
        raise ValueError("Invalid or non-minute bar timestamps")
    if ((frame.high < prices.max(axis=1)) | (frame.low > prices.min(axis=1))).any():
        raise ValueError(f"OHLC bounds inconsistent: {path}")
    if (frame.volume.dropna() < 0).any() or np.isinf(frame.volume).any():
        raise ValueError("Negative/nonfinite volume")
    missing_volume = int(frame.volume.isna().sum())
    frame["volume"] = frame.volume.fillna(0)  # unknown capacity -> cannot fill
    frame = frame.sort_values("timestamp").set_index("timestamp")
    if frame.empty:
        raise ValueError(f"Empty candles: {path}")
    diagnostic = {"path": str(path.resolve()), "sha256": sha256(path), "rows": len(frame),
                  "first_bar": str(frame.index[0]), "last_bar": str(frame.index[-1]),
                  "exact_duplicates_removed": exact_duplicates,
                  "unknown_volume_rows": missing_volume,
                  "zero_volume_fraction": float((frame.volume == 0).mean())}
    return frame, diagnostic


def load_funding(path):
    path = Path(path)
    if path.suffix == ".jsonl":
        frame = pd.read_json(path, lines=True, convert_dates=False)
        frame = frame.rename(columns={"fundingTime": "timestamp", "fundingRate": "rate"})
        frame["timestamp"] = pd.to_datetime(pd.to_numeric(frame.timestamp), unit="ms", utc=True)
    else:
        frame = pd.read_csv(path)
        frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    if not {"timestamp", "rate"} <= set(frame):
        raise ValueError("Funding requires timestamp,rate")
    frame["rate"] = pd.to_numeric(frame.rate, errors="raise")
    if frame.timestamp.isna().any() or not np.isfinite(frame.rate).all():
        raise ValueError("Invalid funding event")
    if "mark" in frame:
        frame["mark"] = pd.to_numeric(frame.mark, errors="raise")
        known = frame.mark.dropna()
        if not np.isfinite(known).all() or (known <= 0).any():
            raise ValueError("Invalid funding settlement mark")
    frame = frame.drop_duplicates()
    if frame.timestamp.duplicated().any():
        raise ValueError("Conflicting funding events")
    return frame.sort_values("timestamp").set_index("timestamp")


def window_diagnostics(spot, perp, start, end):
    # Include bars whose COMPLETION is inside [start, end).
    grid = pd.date_range(start, end, freq="1min", inclusive="left")
    s = spot.index + pd.Timedelta(minutes=1)
    p = perp.index + pd.Timedelta(minutes=1)
    common = s.intersection(p).intersection(grid)
    return {"calendar_days": (end - start).total_seconds() / 86400,
            "expected_minutes": len(grid), "paired_minutes": len(common),
            "paired_coverage_fraction": len(common) / len(grid) if len(grid) else 0,
            "spot_missing_minutes": len(grid.difference(s)),
            "perp_missing_minutes": len(grid.difference(p)),
            "note": "Calendar coverage includes market closures; no holiday inference is made."}
