"""Measure actual read endpoints at changing replay clocks, separating index warm-up."""
import json
import statistics
import time

from fastapi.testclient import TestClient
from backend.api.main import create_app


def main():
    result = {}
    with TestClient(create_app()) as client:
        for name, path in (("tactics", "/api/matches/match_001/tactics?window_s=60"),
                           ("profile", "/api/matches/match_001/players/nil_10/profile?window_s=300")):
            start = time.perf_counter()
            response = client.get(path + "&at_s=3784")
            response.raise_for_status()
            cold = (time.perf_counter() - start) * 1000
            values = []
            for at in range(3785, 3805):
                start = time.perf_counter()
                response = client.get(path + f"&at_s={at}")
                response.raise_for_status()
                values.append((time.perf_counter() - start) * 1000)
            result[name] = {"cold_ms": round(cold, 2), "samples": len(values), "p50_ms": round(statistics.median(values), 2),
                            "p95_ms": round(sorted(values)[int(.95 * len(values)) - 1], 2), "max_ms": round(max(values), 2)}
    print(json.dumps(result, indent=2))
    return int(any(row["p95_ms"] >= 300 for row in result.values()))


if __name__ == "__main__":
    raise SystemExit(main())
