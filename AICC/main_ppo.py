"""
PPO 版本入口：逻辑与 main_rl 类似，保留“先训练后推理”与“纯推理”两种模式。
- 默认读取环境变量 AICC_INFER_ONLY，默认值 1 表示仅推理，不训练。
- 训练阶段仅针对第一个出现的 qp 使用 RLFlowEnv 进行 on-policy learn。
- 推理阶段对所有 qp 做特征 -> 动作 -> 回写，与 DDPG 版本一致。
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.logger import configure

if __package__ is None or __package__ == "":
    # 允许直接 python main_ppo.py 运行
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from AICC.process_features import FeatureProcessor, ProcessedFeatures
    from AICC.rl_ddpg import RLFlowEnv, build_observation, map_action
else:
    from .process_features import FeatureProcessor, ProcessedFeatures
    from .rl_ddpg import RLFlowEnv, build_observation, map_action

# ===== 可调参数 =====
# 纯推理模式开关：默认开启（AICC_INFER_ONLY=1），设置为 0 可启用训练
INFER_ONLY = os.getenv("AICC_INFER_ONLY", "1") == "1"
HISTORY_LENGTH = 4
TOTAL_TIMESTEPS = 10_000  # 仅训练模式使用
POLL_INTERVAL = 0.001  # 1ms
WAIT_TIMEOUT = None    # 等待新 MI 超时（None 表示一直等）

# 归一化常数（需与 RLFlowEnv 保持一致，可按实际链路调整）
BW_NORM = 12.5e9   # bytes/s，对应 100Gbps
RTT_NORM = 1e6     # ns，1ms
RATE_NORM = 1e11   # bps，100Gbps
BYTES_NORM = 1e6   # 1MB
TS_NORM = 1e9      # ns -> 秒

# 模型保存路径
MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_PATH = MODEL_DIR / "ppo_adpg.zip"


def _load_saved_model(env: RLFlowEnv) -> Optional[PPO]:
    """
    如果存在已保存模型则加载。
    """
    if not MODEL_PATH.exists():
        return None
    print(f"检测到已有模型，尝试从 {MODEL_PATH} 加载")
    model = PPO.load(MODEL_PATH, env=env, device="auto")
    return model


def _save_model(model: PPO) -> None:
    """
    保存模型，便于下次启动直接加载。
    """
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save(MODEL_PATH)
    print(f"PPO 模型已保存到 {MODEL_PATH}")


def _build_ppo(env: RLFlowEnv) -> PPO:
    return PPO(
        "MlpPolicy",
        env,
        learning_rate=3e-4,
        n_steps=64,
        batch_size=64,
        gae_lambda=0.95,
        gamma=0.99,
        clip_range=0.2,
        verbose=1,
    )


def main():
    fp = FeatureProcessor(history_length=HISTORY_LENGTH)

    # 等待任意 qp 出现以便训练
    first_qp = None
    wait_counter = 0
    print("等待共享内存数据以确定训练的第一个 qp ...")
    while first_qp is None:
        updates = fp.update_from_shm()
        if updates:
            first_qp = next(iter(updates.keys()))
            break
        time.sleep(POLL_INTERVAL)
        wait_counter += 1
        if wait_counter % 1000 == 0:
            print("仍在等待仿真端写入 /ns3_rl_shm，请确认 ns-3 已运行并产生 MI 数据")
    if INFER_ONLY:
        print(f"检测到 qp_id={first_qp}，启用纯推理模式（AICC_INFER_ONLY=1）")
    else:
        print(f"检测到 qp_id={first_qp}，开始 PPO 训练")

    env = RLFlowEnv(
        qp_id=first_qp,
        feature_processor=fp,
        history_length=HISTORY_LENGTH,
        poll_interval=POLL_INTERVAL,
        wait_timeout=WAIT_TIMEOUT,
    )

    model = _load_saved_model(env)
    if model is None:
        model = _build_ppo(env)
        print("未检测到已保存模型，初始化新 PPO 模型")
    else:
        print("已加载保存的 PPO 模型")

    model.set_logger(configure(folder=None, format_strings=["stdout"]))

    if not INFER_ONLY:
        # on-policy 训练：直接使用 env.learn 收集 rollouts
        model.learn(total_timesteps=TOTAL_TIMESTEPS, reset_num_timesteps=False, progress_bar=False)
        _save_model(model)
        print("训练完成，进入推理阶段")

    feature_dim = len(ProcessedFeatures.__dataclass_fields__)
    obs_dim = feature_dim * HISTORY_LENGTH

    # 推理循环：对所有 qp 进行动作计算并写回
    while True:
        updates = fp.update_from_shm()  # 更新所有 qp 的历史
        if not updates:
            time.sleep(POLL_INTERVAL)
            continue
        for qp_id, _processed in updates.items():
            history = fp.history.get_history(qp_id)
            obs = build_observation(
                history,
                bw_norm=BW_NORM,
                rtt_norm=RTT_NORM,
                rate_norm=RATE_NORM,
                bytes_norm=BYTES_NORM,
                ts_norm=TS_NORM,
                obs_dim=obs_dim,
            )
            action, _ = model.predict(obs, deterministic=True)
            action_val = map_action(float(action[0]))
            fp.update_pre_action(qp_id, action_val)
            fp.write_action(qp_id, action_val)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
