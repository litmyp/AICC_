#!/usr/bin/env python3
"""Plot per-algorithm flow rate evolution from the RDMA flow rate trace."""

import argparse
import csv
import os
from collections import defaultdict
from typing import DefaultDict, Dict, List, Tuple

import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Draw per-algorithm flow rate curves from flow_rate.csv produced by ns-3 RDMA traces.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="mix/flow_rate.csv",
        help="Path to the flow-rate trace CSV (default: mix/flow_rate.csv)",
    )
    parser.add_argument(
        "--output-dir",
        default="mix/flow_rate_plots",
        help="Directory where PNG figures will be written (default: mix/flow_rate_plots)",
    )
    return parser.parse_args()


FlowKey = Tuple[str, str, str, str, str]


def load_samples(path: str) -> DefaultDict[str, DefaultDict[FlowKey, List[Tuple[float, float]]]]:
    per_algo: DefaultDict[str, DefaultDict[FlowKey, List[Tuple[float, float]]]] = defaultdict(lambda: defaultdict(list))
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "time_ns",
            "src_ip",
            "src_port",
            "dst_ip",
            "dst_port",
            "priority",
            "rate_bps",
            "cc_tag",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing columns in {path}: {sorted(missing)}")
        for row in reader:
            key = (
                row["src_ip"],
                row["src_port"],
                row["dst_ip"],
                row["dst_port"],
                row["priority"],
            )
            time_s = float(row["time_ns"]) / 1e9
            rate_gbps = float(row["rate_bps"]) / 1e9
            per_algo[row["cc_tag"]][key].append((time_s, rate_gbps))
    return per_algo


def ensure_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def sanitize_tag(tag: str) -> str:
    safe = tag.replace(" ", "_")
    return "".join(ch for ch in safe if ch.isalnum() or ch in {"_", "-"}) or "default"


def describe_flow(key: FlowKey) -> str:
    src_ip, src_port, dst_ip, dst_port, priority = key
    return f"{src_ip}:{src_port}→{dst_ip}:{dst_port} PG{priority}"


def plot_algorithm(cc_tag: str, flows: Dict[FlowKey, List[Tuple[float, float]]], out_dir: str) -> None:
    usable = {key: pts for key, pts in flows.items() if pts}
    if not usable:
        return
    fig, ax = plt.subplots(figsize=(9, 5))
    for key, points in sorted(usable.items()):
        points.sort(key=lambda item: item[0])
        times, rates = zip(*points)
        ax.plot(times, rates, linewidth=1.4, label=describe_flow(key))
    ax.set_title(f"{cc_tag} Flow Rates")
    ax.set_xlabel("Simulation Time (s)")
    ax.set_ylabel("Rate (Gbps)")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(loc="best", fontsize="small")
    fig.tight_layout()
    filename = f"flow_rates_{sanitize_tag(cc_tag)}.png"
    fig.savefig(os.path.join(out_dir, filename))
    plt.close(fig)


def main() -> None:
    args = parse_args()
    ensure_dir(args.output_dir)
    per_algo = load_samples(args.input)
    if not per_algo:
        print("No samples found – please check the input file.")
        return
    for cc_tag, flows in per_algo.items():
        plot_algorithm(cc_tag, flows, args.output_dir)
    print(f"Generated {len(per_algo)} plot(s) in {args.output_dir}")


if __name__ == "__main__":
    main()
