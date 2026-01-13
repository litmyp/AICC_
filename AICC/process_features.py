import mmap
import struct
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional

import posix_ipc

SHM_NAME = "/ns3_rl_shm"
HEADER_FMT = "<HHI"
SLOT_FMT = "<IHHQIIQQQQIq"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
SLOT_PREFIX_SIZE = struct.calcsize("<IHHQIIQQQQ")
SLOTS_TO_READ = 8
SHM_RETRY_INTERVAL = 0.05


@dataclass
class RawFeatures:
    qp_id: int
    interval_ns: int
    cnp_count: int
    packets_sent: int
    bytes_sent: int
    rtt_ns: int
    rate_bps: int
    timestamp_ns: int
    seq: int


@dataclass
class ProcessedFeatures:
    cnp_ratio: float
    bandwidth_bytes_per_s: float
    rtt_ns: int
    cur_rate_bps: int
    pre_action: float
    reward: float
    bytes_sent: int
    timestamp_ns: int

def calc_reward(features: RawFeatures, target_bw_bps: float = 100e9, base_rtt_ns: float = 4176.0) -> float:
    """
    计算 ADPG 拥塞控制奖励 (Attractor-Deflector).
    
    Args:
        features: RawFeatures 对象
        target_bw_bps: 物理链路带宽上限 (100Gbps = 100e9)
        base_rtt_ns: 基础物理往返时延 (实测 4176ns)
    """
    import math

    # === 0. ADPG 参数配置 ===
    # Beta = 1.3: 容忍约 1.25us (1252ns) 的物理抖动，远覆盖 4176->4200 的误差
    # Target = 0.7: 对应 52KB 排队延迟
    # Scale = 8.0: 初始推荐值
    BETA = 1.3
    TARGET = 0.7
    SCALE = 8.0

    # === 1. 计算归一化速率 (Normalized Rate) ===
    if target_bw_bps > 0:
        norm_rate = features.rate_bps / target_bw_bps
    else:
        norm_rate = 0.0
    norm_rate = max(0.0, min(norm_rate, 1.0))

    # === 2. 计算归一化 RTT (RTT Inflation) ===
    if base_rtt_ns > 0 and features.rtt_ns > 0:
        rtt_inflation = features.rtt_ns / base_rtt_ns
    else:
        rtt_inflation = 1.0

    # === 3. 应用 Beta 阈值 ===
    # 这里 Beta=1.3 已经提供了足够的容错
    effective_inflation = max(rtt_inflation - BETA, 0.0)

    # === 4. 计算误差信号 ===
    error_signal = effective_inflation * math.sqrt(norm_rate)

    # === 5. 计算最终奖励 ===
    reward = (error_signal - TARGET) * SCALE

    # ===6. 改成论文中的形式 -()^2*scale
    # reward = -(error_signal - TARGET)**2 * SCALE

    return reward


# def calc_reward(features: RawFeatures, target_bw_bps: float = 100e9, base_rtt_ns: float = 4176.0) -> float:
#     """
#     计算 ADPG 拥塞控制奖励 (Attractor-Deflector).
    
#     Args:
#         features: RawFeatures 对象
#         target_bw_bps: 物理链路带宽上限 (100Gbps = 100e9)
#         base_rtt_ns: 基础物理往返时延 (实测 4176ns)
#     """
#     import math

#     # === 0. ADPG 参数配置 ===
#     # Beta = 1.3: 容忍约 1.25us (1252ns) 的物理抖动，远覆盖 4176->4200 的误差
#     # Target = 0.7: 对应 52KB 排队延迟
#     # Scale = 8.0: 初始推荐值
#     BETA = 1.3
#     TARGET = 0.6
#     SCALE = 20.0

#     # === 1. 计算归一化速率 (Normalized Rate) ===
#     if target_bw_bps > 0:
#         norm_rate = features.rate_bps / target_bw_bps
#     else:
#         norm_rate = 0.0
#     norm_rate = max(0.0, min(norm_rate, 1.0))

#     # === 2. 计算归一化 RTT (RTT Inflation) ===
#     if base_rtt_ns > 0 and features.rtt_ns > 0:
#         rtt_inflation = features.rtt_ns / base_rtt_ns
#     else:
#         rtt_inflation = 1.0

#     # === 3. 应用 Beta 阈值 ===
#     # 这里 Beta=1.3 已经提供了足够的容错
#     effective_inflation = max(rtt_inflation - BETA, 0.0)

#     # === 4. 计算误差信号 ===
#     error_signal = effective_inflation * math.sqrt(norm_rate)

#     # === 5. 计算吞吐得分（使用实际发送量） ===
#     if features.interval_ns > 0:
#         realized_bps = (features.bytes_sent * 8) / (features.interval_ns * 1e-9)
#         throughput_score = realized_bps / target_bw_bps
#     else:
#         throughput_score = norm_rate  # 兜底

#     # ===6. 对超出目标的误差做惩罚，仅惩罚超标部分 ===
#     deviation = max(error_signal - TARGET, 0.0)
#     penalty = (deviation ** 2) * SCALE

#     reward = throughput_score - penalty

#     return reward

class SharedMemoryFeatureReader:
    def __init__(self, shm_name: str = SHM_NAME, slots_to_read: int = SLOTS_TO_READ):
        self.shm_name = shm_name
        self.slots_to_read = slots_to_read
        self._mmap = self._open_shm()
        self._last_seq_by_slot: Dict[int, int] = {}
        self._slot_meta_by_qp: Dict[int, Dict[str, int]] = {}

    def _open_shm(self) -> mmap.mmap:
        while True:
            try:
                shm = posix_ipc.SharedMemory(self.shm_name)
                mm = mmap.mmap(shm.fd, 0)
                shm.close_fd()
                return mm
            except FileNotFoundError:
                time.sleep(SHM_RETRY_INTERVAL)

    def read_raw_features(self, qp_id: Optional[int] = None) -> List[RawFeatures]:
        _, slot_count, slot_size = struct.unpack_from(HEADER_FMT, self._mmap, 0)
        features: List[RawFeatures] = []
        for idx in range(min(self.slots_to_read, slot_count)):
            offset = HEADER_SIZE + idx * slot_size
            seq1 = struct.unpack_from("<I", self._mmap, offset)[0]
            if seq1 % 2:
                continue  # writer is mid-update
            (seq2, slot_qp_id, _pad, interval_ns, cnp, pkts, bytes_sent, rtt_ns,
             rate_bps, ts_ns, _, _) = struct.unpack_from(SLOT_FMT, self._mmap, offset)
            if seq1 != seq2 or seq2 == 0:
                continue  # unstable data or not yet written
            self._last_seq_by_slot[idx] = seq2
            self._slot_meta_by_qp[slot_qp_id] = {"offset": offset, "seq": seq2}
            if qp_id is not None and slot_qp_id != qp_id:
                continue
            features.append(
                RawFeatures(
                    qp_id=slot_qp_id,
                    interval_ns=interval_ns,
                    cnp_count=cnp,
                    packets_sent=pkts,
                    bytes_sent=bytes_sent,
                    rtt_ns=rtt_ns,
                    rate_bps=rate_bps,
                    timestamp_ns=ts_ns,
                    seq=seq2,
                )
            )
        return features

    def write_action(self, qp_id: int, action_value: float) -> None:
        """
        将动作写回共享内存，按 tools/test.py 的 result_seq/result_value 约定：
        先写 double 位型到 result_value，再写 result_seq 以唤醒仿真端。
        """
        if qp_id not in self._slot_meta_by_qp:
            raise RuntimeError(f"qp_id={qp_id} 尚未有对应的 slot 元数据，请先读取一次特征")
        offset = self._slot_meta_by_qp[qp_id]["offset"]
        target_seq = self._slot_meta_by_qp[qp_id]["seq"]
        result_seq_off = offset + SLOT_PREFIX_SIZE
        result_value_off = result_seq_off + 4
        packed_val = struct.unpack("<q", struct.pack("<d", float(action_value)))[0]
        struct.pack_into("<q", self._mmap, result_value_off, packed_val)
        struct.pack_into("<I", self._mmap, result_seq_off, target_seq)


class FeatureHistory:
    def __init__(self, history_length: int):
        self.history_length = history_length
        self.state_history_dict: Dict[int, Deque[ProcessedFeatures]] = {}
        self.pre_action_dict: Dict[int, float] = {}

    def _process_features(self, raw_features: RawFeatures) -> ProcessedFeatures:
        packets = max(raw_features.packets_sent, 1)
        interval_ns = max(raw_features.interval_ns, 1)
        cnp_ratio = raw_features.cnp_count * 1.0 / packets
        bandwidth = raw_features.bytes_sent * 1e9 / interval_ns
        return ProcessedFeatures(
            cnp_ratio=cnp_ratio,
            bandwidth_bytes_per_s=bandwidth,
            rtt_ns=raw_features.rtt_ns,
            cur_rate_bps=raw_features.rate_bps,
            pre_action=self._get_pre_action(raw_features.qp_id),
            reward=calc_reward(raw_features),
            bytes_sent=raw_features.bytes_sent,
            timestamp_ns=raw_features.timestamp_ns,
        )

    def _get_pre_action(self, qp_id: int) -> float:
        return self.pre_action_dict.get(qp_id, 1.0)

    def update_pre_action(self, qp_id: int, pre_action: float) -> None:
        self.pre_action_dict[qp_id] = pre_action

    def update_history(self, raw_features: Iterable[RawFeatures]) -> Dict[int, ProcessedFeatures]:
        latest: Dict[int, ProcessedFeatures] = {}
        for raw in raw_features:
            qp_id = raw.qp_id
            if qp_id not in self.state_history_dict:
                self.state_history_dict[qp_id] = deque(maxlen=self.history_length)
            processed = self._process_features(raw)
            history = self.state_history_dict[qp_id]
            history.append(processed)
            while len(history) < self.history_length:
                history.append(processed)
            latest[qp_id] = processed
        return latest

    def get_history(self, qp_id: int) -> List[ProcessedFeatures]:
        if qp_id not in self.state_history_dict:
            return []
        return list(self.state_history_dict[qp_id])


class FeatureProcessor:
    def __init__(self, history_length: int, shm_name: str = SHM_NAME, slots_to_read: int = SLOTS_TO_READ):
        self.reader = SharedMemoryFeatureReader(shm_name=shm_name, slots_to_read=slots_to_read)
        self.history = FeatureHistory(history_length=history_length)

    def update_from_shm(self, qp_id: Optional[int] = None) -> Dict[int, ProcessedFeatures]:
        raw_features = self.reader.read_raw_features(qp_id=qp_id)
        return self.history.update_history(raw_features)

    def update_pre_action(self, qp_id: int, pre_action: float) -> None:
        self.history.update_pre_action(qp_id, pre_action)

    def write_action(self, qp_id: int, action_value: float) -> None:
        self.reader.write_action(qp_id, action_value)
