"""Target-device evaluation harness for Raspberry Pi transfer testing.

Run on the target device:

    python -m lobby_attendance.evaluate --camera-index 0 --iterations 20 --output evaluation-report.json

This produces a machine-readable JSON report with camera diagnostics,
per-interaction latency, status distribution, and host resource metrics.
It does NOT store frames, embeddings, identities, or biometric data.
It does NOT constitute pilot approval, PAD evidence, or accuracy validation.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc


def _host_info() -> dict[str, Any]:
    """Collect safe host metadata without secrets or biometric data."""
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "python": platform.python_version(),
        "hostname": platform.node(),
    }
    try:
        info["cpu_count"] = os.cpu_count()
    except Exception:
        info["cpu_count"] = None

    # Raspberry Pi temperature (Linux thermal zone)
    thermal_path = Path("/sys/class/thermal/thermal_zone0/temp")
    if thermal_path.exists():
        try:
            info["cpu_temp_c"] = int(thermal_path.read_text().strip()) / 1000.0
        except Exception:
            info["cpu_temp_c"] = None
    else:
        info["cpu_temp_c"] = None

    # Memory
    try:
        import shutil
        total, used, free = shutil.disk_usage(".")
        info["disk_total_mb"] = total // (1024 * 1024)
        info["disk_free_mb"] = free // (1024 * 1024)
    except Exception:
        pass

    meminfo_path = Path("/proc/meminfo")
    if meminfo_path.exists():
        try:
            lines = meminfo_path.read_text().splitlines()
            for line in lines:
                if line.startswith("MemTotal:"):
                    info["mem_total_kb"] = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    info["mem_available_kb"] = int(line.split()[1])
        except Exception:
            pass

    return info


def _camera_diagnostics(camera_index: int) -> dict[str, Any]:
    """Probe the camera without storing any frames."""
    diag: dict[str, Any] = {"camera_index": camera_index, "available": False}
    try:
        import cv2
    except ImportError:
        diag["error"] = "opencv-unavailable"
        return diag

    capture = None
    try:
        capture = cv2.VideoCapture(camera_index)
        if not capture or not capture.isOpened():
            diag["error"] = "camera-not-opened"
            return diag
        diag["available"] = True
        diag["backend"] = capture.getBackendName()
        diag["width"] = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        diag["height"] = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        diag["fps"] = capture.get(cv2.CAP_PROP_FPS)

        # Test a single frame read
        ok, frame = capture.read()
        diag["first_frame_ok"] = ok
        if ok and frame is not None:
            diag["actual_shape"] = list(frame.shape)
        else:
            diag["actual_shape"] = None
    except Exception as exc:
        diag["error"] = str(exc)[:200]
    finally:
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass
    return diag


def _run_provider_benchmark(
    camera_index: int,
    model_path: str | None,
    model_directory: str | None,
    model_sha256: str | None,
    iterations: int,
    interaction_timeout: float,
    sampling_interval: float,
) -> dict[str, Any]:
    """Run bounded provider interactions and collect latency/status metrics."""
    from .config import Settings
    from .vision import OpenCVVisionProvider, VisionStatus
    from .vision.opencv import demo_presence_liveness_checker

    liveness_checker = demo_presence_liveness_checker if model_path else None
    provider = OpenCVVisionProvider(
        camera_index=camera_index,
        model_path=model_path,
        approved_model_directory=model_directory,
        expected_model_sha256=model_sha256,
        liveness_checker=liveness_checker,
        min_face_size=40,
    )

    results: dict[str, Any] = {
        "model_version": provider.model_version,
        "iterations_requested": iterations,
        "iterations_completed": 0,
        "interaction_timeout_seconds": interaction_timeout,
        "sampling_interval_seconds": sampling_interval,
        "latencies_ms": [],
        "status_counts": {},
        "errors": [],
    }

    for i in range(iterations):
        start = time.perf_counter()
        until = datetime.now(UTC) + timedelta(seconds=interaction_timeout)
        try:
            samples = provider.observe(until=until, interval_seconds=sampling_interval)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            results["latencies_ms"].append(round(elapsed_ms, 2))
            results["iterations_completed"] += 1

            for sample in samples:
                status = sample.status.value if hasattr(sample.status, "value") else str(sample.status)
                results["status_counts"][status] = results["status_counts"].get(status, 0) + 1
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            results["latencies_ms"].append(round(elapsed_ms, 2))
            results["errors"].append({"iteration": i, "error": str(exc)[:200]})

        # Brief pause between interactions to simulate real usage
        time.sleep(0.5)

    # Compute summary statistics
    latencies = results["latencies_ms"]
    if latencies:
        results["latency_summary"] = {
            "min_ms": round(min(latencies), 2),
            "max_ms": round(max(latencies), 2),
            "mean_ms": round(statistics.mean(latencies), 2),
            "median_ms": round(statistics.median(latencies), 2),
            "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95)], 2) if len(latencies) >= 2 else round(latencies[0], 2),
            "stdev_ms": round(statistics.stdev(latencies), 2) if len(latencies) >= 2 else 0.0,
        }
    else:
        results["latency_summary"] = None

    return results


def _run_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    """Assemble the complete evaluation report."""
    started_at = datetime.now(UTC).isoformat()

    report: dict[str, Any] = {
        "evaluation_type": "target-device-evaluation",
        "started_at": started_at,
        "host": _host_info(),
        "camera_diagnostics": _camera_diagnostics(args.camera_index),
        "provider_benchmark": None,
        "completed_at": None,
        "verdict": "incomplete",
        "notes": [
            "This report is local engineering evidence only.",
            "It does not constitute pilot approval, PAD evidence, or accuracy validation.",
            "No frames, embeddings, identities, or biometric data are stored.",
        ],
    }

    # Only run the provider benchmark if the camera is available
    if report["camera_diagnostics"]["available"]:
        report["provider_benchmark"] = _run_provider_benchmark(
            camera_index=args.camera_index,
            model_path=args.model_path,
            model_directory=args.model_directory,
            model_sha256=args.model_sha256,
            iterations=args.iterations,
            interaction_timeout=args.interaction_timeout,
            sampling_interval=args.sampling_interval,
        )

        benchmark = report["provider_benchmark"]
        if benchmark["iterations_completed"] == benchmark["iterations_requested"] and not benchmark["errors"]:
            report["verdict"] = "camera-and-provider-operational"
        elif benchmark["iterations_completed"] > 0:
            report["verdict"] = "partial-with-errors"
        else:
            report["verdict"] = "provider-failed"
    else:
        report["verdict"] = "camera-unavailable"

    report["completed_at"] = datetime.now(UTC).isoformat()

    # Add thermal check at end
    thermal_path = Path("/sys/class/thermal/thermal_zone0/temp")
    if thermal_path.exists():
        try:
            report["host"]["cpu_temp_c_end"] = int(thermal_path.read_text().strip()) / 1000.0
        except Exception:
            pass

    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Lobby Attendance target-device evaluation harness",
        epilog="Run on the Raspberry Pi with a USB camera to produce deployment evidence.",
    )
    parser.add_argument("--camera-index", type=int, default=0, help="Camera device index (default: 0)")
    parser.add_argument("--model-path", type=str, default=None, help="Path to the Haar Cascade or approved model XML")
    parser.add_argument("--model-directory", type=str, default=None, help="Approved model directory restriction")
    parser.add_argument("--model-sha256", type=str, default=None, help="Expected SHA-256 of the model asset")
    parser.add_argument("--iterations", type=int, default=20, help="Number of interaction cycles (default: 20)")
    parser.add_argument("--interaction-timeout", type=float, default=2.0, help="Per-interaction timeout in seconds (default: 2.0)")
    parser.add_argument("--sampling-interval", type=float, default=0.2, help="Sampling interval in seconds (default: 0.2)")
    parser.add_argument("--output", type=str, default="evaluation-report.json", help="Output JSON report path")
    parser.add_argument("--quiet", action="store_true", help="Suppress stdout summary")

    args = parser.parse_args(argv)

    if not args.quiet:
        print(f"[evaluate] Starting target-device evaluation (camera={args.camera_index}, iterations={args.iterations})")

    report = _run_evaluation(args)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if not args.quiet:
        print(f"[evaluate] Verdict: {report['verdict']}")
        if report["provider_benchmark"] and report["provider_benchmark"]["latency_summary"]:
            summary = report["provider_benchmark"]["latency_summary"]
            print(f"[evaluate] Latency: mean={summary['mean_ms']:.0f}ms, p95={summary['p95_ms']:.0f}ms, max={summary['max_ms']:.0f}ms")
            print(f"[evaluate] Status distribution: {report['provider_benchmark']['status_counts']}")
        print(f"[evaluate] Report written to: {output_path}")

    sys.exit(0 if report["verdict"] in ("camera-and-provider-operational", "partial-with-errors") else 1)


if __name__ == "__main__":
    main()
