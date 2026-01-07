#可以从temp.txt中读取数据，回执时间-速率变化折线图的脚本，适用于dcqcn、timely



import re
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

# Parse DCQCN rate logs from simulation/temp.txt and draw time-series lines per flow.
ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "simulation" / "temp.txt"
OUTPUT_PATH = Path(__file__).resolve().parent / "dcqcn_rates.png"

ts_re = re.compile(r"ts=(\d+)")
# Example line: lty added: node=4 qp=[0.4:10000 -> 0.1:100] current_rate=32.2145Gbps
rate_re = re.compile(r"node=(\d+).*?qp=\[(.*?)\].*?current_rate=([0-9.]+)Gbps")

records = []
last_ts = None

with INPUT_PATH.open() as src:
    for line in src:
        ts_match = ts_re.search(line)
        if ts_match:
            last_ts = int(ts_match.group(1))
        rate_match = rate_re.search(line)
        if rate_match and last_ts is not None:
            node = int(rate_match.group(1))
            flow = rate_match.group(2)
            rate = float(rate_match.group(3))
            t_sec = last_ts / 1e9  # timestamps are in ns
            records.append((t_sec, flow, node, rate))

if not records:
    raise SystemExit("No rate records found in temp.txt")

series = defaultdict(lambda: {"t": [], "r": []})
for t_sec, flow, node, rate in records:
    label = f"node {node} {flow}"
    series[label]["t"].append(t_sec)
    series[label]["r"].append(rate)

plt.figure(figsize=(10, 5))
for label, data in series.items():
    times, rates = zip(*sorted(zip(data["t"], data["r"])))
    plt.plot(times, rates, label=label, linewidth=1.0)

plt.xlabel("Time (s)")
plt.ylabel("Send rate (Gbps)")
plt.title("HPCC flow send rates vs time")
plt.grid(True, linestyle="--", alpha=0.4)
plt.legend(loc="best")
plt.tight_layout()
plt.savefig(OUTPUT_PATH, dpi=150)
print(f"Parsed {len(records)} samples across {len(series)} flows")
print(f"Saved plot to {OUTPUT_PATH}")
