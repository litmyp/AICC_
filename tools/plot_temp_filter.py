"""
从 simulation/temp_filter.txt 解析 RL Sample 日志，按 qp 绘制发送速率（bytes/mi_ns -> Gbps）随时间折线。

示例：
    python tools/plot_temp_filter.py
    python tools/plot_temp_filter.py --file simulation/temp_filter.txt --end 2.1s --output temp_filter_rate.png
"""

import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt


# 顺序可能变化，使用分段匹配
QP_RE = re.compile(r"qp_id=(?P<qp_id>\d+)")
BYTES_RE = re.compile(r"bytes=(?P<bytes>\d+)")
MI_RE = re.compile(r"mi_ns=(?P<mi_ns>\d+)")
TS_RE = re.compile(r"ts_ns=(?P<ts_ns>\d+)")
PKTS_RE = re.compile(r"pkts=(?P<pkts>\d+)")


def parse_end(value: str) -> int:
    """
    将 --end 参数解析为纳秒。
    支持纯数字（视为纳秒）或以 s 结尾的秒数（如 1.5s）。
    """
    if value.endswith("s"):
        return int(float(value[:-1]) * 1e9)
    return int(float(value))


def parse_file(path: Path, end_ns: int | None = None) -> Dict[int, List[Tuple[int, float]]]:
    """
    返回 {qp_id: [(ts_ns, gbps), ...]}，按时间排序。
    """
    data: Dict[int, List[Tuple[int, float]]] = {}
    with path.open("r") as f:
        for line in f:
            m_qp = QP_RE.search(line)
            m_bytes = BYTES_RE.search(line)
            m_mi = MI_RE.search(line)
            m_ts = TS_RE.search(line)
            m_pkts = PKTS_RE.search(line)
            if not (m_qp and m_bytes and m_mi and m_ts and m_pkts):
                continue
            qp_id = int(m_qp.group("qp_id"))
            bytes_sent = int(m_bytes.group("bytes"))
            mi_ns = int(m_mi.group("mi_ns"))
            ts_ns = int(m_ts.group("ts_ns"))
            pkts = int(m_pkts.group("pkts"))
            if end_ns is not None and ts_ns > end_ns:
                continue
            if pkts <= 0:
                continue
            if mi_ns <= 0:
                continue
            # 计算 Mbps/Gbps: bytes * 8 / (mi_ns * 1e-9) / 1e9
            gbps = (bytes_sent * 8) / (mi_ns * 1e-9) / 1e9
            data.setdefault(qp_id, []).append((ts_ns, gbps))
    for qp_id in data:
        data[qp_id].sort(key=lambda x: x[0])
    return data


def plot(
    data: Dict[int, List[Tuple[int, float]]],
    output: Path,
    show: bool,
    fig_width: float,
    fig_height: float,
) -> None:
    if not data:
        print("没有可绘制的数据")
        return

    # 对齐到全局最早 ts_ns，确保横轴严格按照时间顺序。
    min_ts = min(ts for series in data.values() for ts, _ in series)

    plt.figure(figsize=(fig_width, fig_height))
    for qp_id, series in sorted(data.items()):
        ts_ns, gbps = zip(*series)
        ts_rel_ms = [(t - min_ts) / 1e6 for t in ts_ns]  # 相对全局起点的时间（ms）
        plt.plot(ts_rel_ms, gbps, label=f"qp {qp_id}")
    plt.xlabel("时间（相对全局最早 ts_ns，ms）")
    plt.ylabel("发送速率（Gbps，按 bytes/mi_ns）")
    plt.title("temp_filter 每个 qp 的发送速率随时间变化")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output)
    print(f"已保存图像到 {output}")
    if show:
        plt.show()


def main():
    parser = argparse.ArgumentParser(description="根据 temp_filter.txt 绘制速率-时间图（bytes/mi_ns -> Gbps）")
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("simulation/temp_filter.txt"),
        help="输入日志文件路径（默认 simulation/temp_filter.txt）",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="截止时间，默认单位 ns；可用 <秒>s 表示秒，例如 2.5s",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("temp_filter_pkts.png"),
        help="输出图像路径（默认 temp_filter_pkts.png）",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="保存后同时弹出显示图像",
    )
    parser.add_argument(
        "--figwidth",
        type=float,
        default=14.0,
        help="图像宽度（英寸），默认 14",
    )
    parser.add_argument(
        "--figheight",
        type=float,
        default=6.0,
        help="图像高度（英寸），默认 6",
    )
    args = parser.parse_args()

    end_ns = parse_end(args.end) if args.end is not None else None
    data = parse_file(args.file, end_ns=end_ns)
    plot(
        data,
        args.output,
        show=args.show,
        fig_width=args.figwidth,
        fig_height=args.figheight,
    )


if __name__ == "__main__":
    main()
