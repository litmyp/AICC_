import re
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


def parse_samples(path, t_start=None, t_end=None):
    pattern = re.compile(r"\[RL Sample\].*?qp_id=(\d+).*?rate_bps=(\d+).*?ts_ns=(\d+)")
    data = defaultdict(list)
    for line in Path(path).read_text().splitlines():
        m = pattern.search(line)
        if not m:
            continue
        qp = int(m.group(1))
        rate_gbps = int(m.group(2)) / 1e9
        ts_s = int(m.group(3)) / 1e9
        if t_start is not None and ts_s < t_start:
            continue
        if t_end is not None and ts_s > t_end:
            continue
        data[qp].append((ts_s, rate_gbps))
    return data


def plot_rates(data, title, out_file):
    if not data:
        raise SystemExit("no RL Sample lines found in the specified window")
    plt.figure(figsize=(10, 6))
    for qp, pts in sorted(data.items()):
        pts.sort()
        xs, ys = zip(*pts)
        plt.plot(xs, ys, label="qp %s" % qp)
    plt.xlabel("time (s)")
    plt.ylabel("rate (Gbps)")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_file)
    print("saved %s" % out_file)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Plot qp rate over time from a log file")
    parser.add_argument("--file", default="simulation/temp.txt", help="input log file path")
    parser.add_argument(
        "--start",
        type=float,
        default=None,
        help="start time (s), default None",
    )
    parser.add_argument(
        "--end",
        type=float,
        default=None,
        help="end time (s), default None; set only end if you want",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="output png path (default: <log_dir>/rl_rate_plot.png)",
    )
    args = parser.parse_args()

    log_path = Path(args.file)
    data = parse_samples(log_path, args.start, args.end)
    title = "Rate vs time per qp"
    if args.start is not None or args.end is not None:
        title += f" ({args.start if args.start is not None else '-inf'}s - {args.end if args.end is not None else 'inf'}s)"
    out = Path(args.out) if args.out else log_path.with_name("rl_rate_plot.png")
    plot_rates(data, title, out)
