#!/usr/bin/env python3
# 读取 temp.txt 中的 node_id / timestamp / rate，按节点绘制速率折线图

import argparse
import re
from pathlib import Path
from typing import Tuple

import matplotlib.pyplot as plt
import pandas as pd


def _pick_columns(df: pd.DataFrame) -> Tuple[str, str, str]:
    """
    猜测 node_id / timestamp / rate 列名。
    允许文件自带表头；若无表头则默认前三列。
    """
    cols_lower = {c.lower(): c for c in df.columns}
    node_col = None
    ts_col = None
    rate_col = None

    for key in cols_lower:
        if node_col is None and "node" in key:
            node_col = cols_lower[key]
        if ts_col is None and ("ts" in key or "time" in key):
            ts_col = cols_lower[key]
        if rate_col is None and ("rate" in key or "speed" in key):
            rate_col = cols_lower[key]

    # 无表头时，pandas 会用整数列名 0,1,2...
    if node_col is None:
        node_col = df.columns[0]
    if ts_col is None:
        ts_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
    if rate_col is None:
        rate_col = df.columns[2] if len(df.columns) > 2 else df.columns[-1]

    return node_col, ts_col, rate_col


def _to_gbps(val) -> float:
    """
    将速率值统一为 Gbps。支持纯数字（默认 Gbps）或带单位字符串。
    支持单位：bps、K/M/Gbps 或 b/s、B/s 常见写法。
    """
    if pd.isna(val):
        return float("nan")
    if isinstance(val, (int, float)):
        return float(val)

    text = str(val).strip()
    m = re.search(r"([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)", text)
    if not m:
        return float("nan")
    num = float(m.group(1))
    unit = text[m.end():].strip().lower()

    if unit.startswith("gb"):
        factor = 1.0
    elif unit.startswith("mb"):
        factor = 1e-3
    elif unit.startswith("kb"):
        factor = 1e-6
    elif unit.startswith("b"):
        factor = 1e-9
    else:
        factor = 1.0  # 默认视为 Gbps
    return num * factor


def plot_rates(df: pd.DataFrame, node_col: str, ts_col: str, rate_col: str, save_path: Path, show: bool):
    plt.figure(figsize=(12, 6))
    for node_id, group in df.groupby(node_col):
        plt.plot(
            group[ts_col],
            group[rate_col],
            label=f"Node {node_id}",
            marker="o",
            linewidth=1.2,
            markersize=3,
        )

    plt.xlabel("Timestamp")
    plt.ylabel("Rate (Gbps)")
    plt.title("Per-node Rate over Time")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150)
        print(f"图像已保存到: {save_path}")
    if show:
        plt.show()
    else:
        plt.close()


def main():
    parser = argparse.ArgumentParser(description="根据 temp.txt 中的 node_id、时间戳、速率绘制折线图（速率单位 Gbps）")
    parser.add_argument("--input", "-i", default="temp.txt", help="输入文件路径，默认 temp.txt")
    parser.add_argument("--output", "-o", default="temp_rate_plot.png", help="输出图像路径，默认 temp_rate_plot.png")
    parser.add_argument("--no-show", action="store_true", help="不弹出图像窗口，仅保存文件")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        # 兼容在 AICC_lty 目录下运行，temp.txt 在 simulation/ 下的情况
        candidate = Path(__file__).resolve().parent.parent / "simulation" / path.name
        if candidate.exists():
            path = candidate
        else:
            raise FileNotFoundError(f"找不到输入文件: {path}")

    records = []
    # 针对 temp.txt 的日志格式：依次出现 “My CC: node=..” -> “在时刻:...执行一次对共享内存的写入” -> “新速率 100 Gb/s”
    node_re = re.compile(r"node\s*=\s*(\d+)")
    ts_re = re.compile(r"在时刻[:：]\s*([0-9]+)")
    rate_re = re.compile(r"新速率\s*([0-9.+-eE]+)\s*g[bp]/?s", re.IGNORECASE)
    # 兜底：若有 csv/三列数字行，后续再尝试

    last_node = None
    last_ts = None
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            m_node = node_re.search(line)
            if m_node:
                last_node = int(m_node.group(1))
            m_ts = ts_re.search(line)
            if m_ts:
                try:
                    last_ts = float(m_ts.group(1))
                except ValueError:
                    last_ts = None
            m_rate = rate_re.search(line)
            if m_rate and last_node is not None and last_ts is not None:
                rate_val = _to_gbps(m_rate.group(1) + "Gbps")
                records.append((last_node, last_ts, rate_val))
                # 不清空 last_node/last_ts，允许连续速率记录复用

    # 如果未解析到记录，再尝试通用三列行
    if not records:
        rows = []
        with path.open() as f:
            for line in f:
                if not line.strip() or line.strip().startswith("#"):
                    continue
                tokens = re.split(r"[,\s]+", line.strip())
                if len(tokens) != 3:
                    continue
                try:
                    node_val = float(tokens[0])
                    ts_val = float(tokens[1])
                    rate_val = tokens[2]
                except ValueError:
                    continue
                rows.append((node_val, ts_val, rate_val))
        if not rows:
            raise ValueError("未能从输入文件提取到 node/timestamp/rate 数据，请确认日志格式")
        df = pd.DataFrame(rows, columns=["node_id", "timestamp", "rate"])
    else:
        df = pd.DataFrame(records, columns=["node_id", "timestamp", "rate"])

    node_col, ts_col, rate_col = _pick_columns(df)

    # 统一类型
    df[node_col] = pd.to_numeric(df[node_col], errors="coerce")
    df[ts_col] = pd.to_numeric(df[ts_col], errors="coerce")
    df[rate_col] = df[rate_col].apply(_to_gbps)

    df = df.dropna(subset=[node_col, ts_col, rate_col])
    df = df.sort_values([node_col, ts_col])

    plot_rates(df, node_col, ts_col, rate_col, Path(args.output), show=not args.no_show)


if __name__ == "__main__":
    main()
