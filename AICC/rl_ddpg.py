import time
from typing import Dict, Iterable, List, Optional

import numpy as np
try:
    import gymnasium as gym  # 推荐使用 gymnasium，避免 shimmy 依赖
    from gymnasium import spaces
except ImportError as e:
    raise ImportError(
        "缺少 gymnasium，请先安装：pip install 'gymnasium>=0.28'（SB3 现基于 gymnasium，"
        "否则会报 shimmy 缺失）"
    ) from e
from stable_baselines3 import DDPG
from stable_baselines3.common.noise import NormalActionNoise

from .process_features import FeatureProcessor, ProcessedFeatures


class RLFlowEnv(gym.Env):
    """
    一个最小的 Gym 环境示例：面向单个 qp，使用 FeatureProcessor 从共享内存取状态，
    将连续动作写入 pre_action 轨迹，奖励直接来自 processed features（当前 reward=1）。
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        qp_id: int,
        feature_processor: FeatureProcessor,
        history_length: int,
        poll_interval: float = 0.001,  # 1ms 轮询
        wait_timeout: Optional[float] = None,
    ):
        super().__init__()
        self.qp_id = qp_id
        self.fp = feature_processor
        self.history_length = history_length
        self.poll_interval = poll_interval
        self.wait_timeout = wait_timeout
        self._feature_dim = len(ProcessedFeatures.__dataclass_fields__)
        # 归一化常数（可按实际链路能力调整）
        self._bw_norm = 12.5e9  # bytes/s，对应 100 Gbps
        self._rtt_norm = 1e6    # ns，1 ms
        self._rate_norm = 1e11  # bps，100 Gbps
        self._bytes_norm = 1e6  # 1 MB
        self._ts_norm = 1e9     # ns -> 秒

        obs_dim = self._feature_dim * history_length
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )
        # 动作空间：连续一维，供策略输出，后续经 tanh 再映射到实际值
        self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32)

        self._last_features: Optional[ProcessedFeatures] = None

    def _wait_new_features(self) -> ProcessedFeatures:
        deadline = time.time() + self.wait_timeout if self.wait_timeout is not None else None
        while True:
            processed = self.fp.update_from_shm(qp_id=self.qp_id)
            if self.qp_id in processed:
                self._last_features = processed[self.qp_id]
                return self._last_features
            time.sleep(self.poll_interval)
            if deadline is not None and time.time() >= deadline:
                raise RuntimeError(f"等待 qp_id={self.qp_id} 的新特征超时")

    def _obs_from_history(self) -> np.ndarray:
        history = self.fp.history.get_history(self.qp_id)
        return build_observation(
            history,
            bw_norm=self._bw_norm,
            rtt_norm=self._rtt_norm,
            rate_norm=self._rate_norm,
            bytes_norm=self._bytes_norm,
            ts_norm=self._ts_norm,
            obs_dim=self.observation_space.shape[0],
        )

    def reset(self, *, seed: Optional[int] = None, options: Optional[Dict] = None):
        super().reset(seed=seed)
        self._wait_new_features()
        obs = self._obs_from_history()
        return obs, {}

    def step(self, action):
        action_val = map_action(float(action[0]))
        self.fp.update_pre_action(self.qp_id, action_val)
        self.fp.write_action(self.qp_id, action_val)
        processed = self._wait_new_features()
        obs = self._obs_from_history()
        reward = float(processed.reward)
        info = {"processed": processed, "action": action_val}
        terminated = False
        truncated = False
        return obs, reward, terminated, truncated, info


def build_ddpg(
    env: RLFlowEnv,
    action_noise_sigma: float = 0.1,
    learning_rate: float = 1e-3,
    learning_starts: int = 1000,
    buffer_size: int = 100_000,
) -> DDPG:
    n_actions = env.action_space.shape[-1]
    action_noise = NormalActionNoise(mean=np.zeros(n_actions), sigma=action_noise_sigma * np.ones(n_actions))
    model = DDPG(
        "MlpPolicy",
        env,
        learning_rate=learning_rate,
        action_noise=action_noise,
        learning_starts=learning_starts,
        buffer_size=buffer_size,
        verbose=1,
    )
    return model


def train_ddpg(
    env: RLFlowEnv,
    total_timesteps: int = 10_000,
    action_noise_sigma: float = 0.1,
    learning_rate: float = 1e-3,
) -> DDPG:
    model = build_ddpg(env, action_noise_sigma=action_noise_sigma, learning_rate=learning_rate)
    model.learn(total_timesteps=total_timesteps)
    return model


def map_action(raw: float) -> float:
    raw = np.tanh(raw)  # 归一化到 [-1,1]
    if raw >= 0:
        return 1 + 0.2 * raw  # [1, 1.2]
    return 1 / (1 - 0.2 * raw)  # 约 [0.83, 1)


def build_observation(
    history: Iterable[ProcessedFeatures],
    bw_norm: float,
    rtt_norm: float,
    rate_norm: float,
    bytes_norm: float,
    ts_norm: float,
    obs_dim: int,
) -> np.ndarray:
    hist_list: List[ProcessedFeatures] = list(history)
    if not hist_list:
        return np.zeros((obs_dim,), dtype=np.float32)
    vals = []
    for item in hist_list:
        vals.extend(
            [
                np.clip(item.cnp_ratio, 0.0, 1.0),
                item.bandwidth_bytes_per_s / bw_norm,
                item.rtt_ns / rtt_norm,
                item.cur_rate_bps / rate_norm,
                item.pre_action,
                np.clip(item.reward / 100.0, -10.0, 10.0),
                item.bytes_sent / bytes_norm,
                item.timestamp_ns / ts_norm,
            ]
        )
    return np.array(vals, dtype=np.float32)
