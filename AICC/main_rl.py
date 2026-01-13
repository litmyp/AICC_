"""
主入口：启动前先运行 ns-3 仿真确保 /ns3_rl_shm 可用。
逻辑：
1) 等待任何 qp 的特征出现，选第一个 qp 训练 DDPG（单环境训练）。
2) 训练完成后，循环读取共享内存，对所有出现的 qp 计算历史特征 -> 推理动作 -> 写回共享内存。
如需调整参数，直接改下方常量即可，然后 `python -m AICC.main_rl` 启动。
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
from stable_baselines3 import DDPG
from stable_baselines3.common.logger import configure
from typing import Optional

if __package__ is None or __package__ == "":
    # 允许直接 python main_rl.py 运行
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from AICC.process_features import FeatureProcessor, ProcessedFeatures
    from AICC.rl_ddpg import RLFlowEnv, build_ddpg, build_observation, map_action
else:
    from .process_features import FeatureProcessor, ProcessedFeatures
    from .rl_ddpg import RLFlowEnv, build_ddpg, build_observation, map_action

# ===== 可调参数 =====
# 纯推理模式开关：默认开启（AICC_INFER_ONLY=1），设置环境变量为 0 可恢复训推
# INFER_ONLY = os.getenv("AICC_INFER_ONLY", "0") == "1" #训推
INFER_ONLY = os.getenv("AICC_INFER_ONLY", "1") == "1" #纯推理
HISTORY_LENGTH = 4
TOTAL_TIMESTEPS = 10_000
POLL_INTERVAL = 0.001  # 1ms
WAIT_TIMEOUT = None    # 等待新 MI 超时（None 表示一直等）
ONLINE_TRAIN_INTERVAL = 10     # 每处理多少次推理后训练一次
ONLINE_GRADIENT_STEPS = 1      # 每次触发训练的梯度步数

# 归一化常数（需与 RLFlowEnv 保持一致，可按实际链路调整）
BW_NORM = 12.5e9   # bytes/s，对应 100Gbps
RTT_NORM = 1e6     # ns，1ms
RATE_NORM = 1e11   # bps，100Gbps
BYTES_NORM = 1e6   # 1MB
TS_NORM = 1e9      # ns -> 秒
# 模型保存路径
MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_PATH = MODEL_DIR / "ddpg_adpg.zip"
REPLAY_BUFFER_PATH = MODEL_DIR / "ddpg_adpg_replay_buffer.pkl"
# ====================


def _load_saved_model(env: RLFlowEnv) -> Optional[DDPG]:
    """
    如果存在已保存模型则加载，带上 replay buffer 方便继续训练。
    """
    if not MODEL_PATH.exists():
        return None
    print(f"检测到已有模型，尝试从 {MODEL_PATH} 加载")
    model = DDPG.load(MODEL_PATH, env=env, device="auto")
    if REPLAY_BUFFER_PATH.exists():
        try:
            model.load_replay_buffer(str(REPLAY_BUFFER_PATH))
            print(f"已加载 replay buffer：{REPLAY_BUFFER_PATH}")
        except Exception as exc:  # noqa: BLE001
            print(f"加载 replay buffer 失败，忽略继续：{exc}")
    return model


def _save_model(model: DDPG) -> None:
    """
    保存模型和 replay buffer，便于下次启动直接加载。
    """
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save(MODEL_PATH)
    try:
        model.save_replay_buffer(str(REPLAY_BUFFER_PATH))
    except Exception as exc:  # noqa: BLE001
        print(f"保存 replay buffer 失败（忽略）：{exc}")
    print(f"模型已保存到 {MODEL_PATH}")


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
        print(f"检测到 qp_id={first_qp}，开始训练")

    env = RLFlowEnv(
        qp_id=first_qp,
        feature_processor=fp,
        history_length=HISTORY_LENGTH,
        poll_interval=POLL_INTERVAL,
        wait_timeout=WAIT_TIMEOUT,
    )
    model = _load_saved_model(env)
    if model is None:
        model = build_ddpg(
            env,
            learning_rate=1e-3,
            action_noise_sigma=0.1,
            learning_starts=1,
            buffer_size=50_000,
        )
        # 直接进入在线推理+增量训练：先完成内部初始化
        model._setup_model()
        print("未检测到已保存模型，初始化新模型")
    else:
        print("已加载保存的模型，继续推理/训练")
    # 配置日志，避免直接 train 时缺少 logger
    model.set_logger(configure(folder=None, format_strings=["stdout"]))
    model._current_progress_remaining = 1.0
    if INFER_ONLY:
        print("初始化完成，进入纯推理（不训练/不保存）")
    else:
        print("初始化完成，进入在线推理+增量训练")

    feature_dim = len(ProcessedFeatures.__dataclass_fields__)
    obs_dim = feature_dim * HISTORY_LENGTH
    last_obs: dict[int, np.ndarray] = {}
    last_action: dict[int, np.ndarray] = {}
    step_counter = 0

    while True:
        updates = fp.update_from_shm()  # 更新所有 qp 的历史
        if not updates:
            time.sleep(POLL_INTERVAL)
            continue
        for qp_id, processed in updates.items():
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
            # 如果有上一状态与动作，则将当前 obs 作为 next_obs 加入经验池
            if not INFER_ONLY and qp_id in last_obs and qp_id in last_action:
                model.replay_buffer.add(
                    obs=last_obs[qp_id],
                    next_obs=obs,
                    action=last_action[qp_id],
                    reward=np.array([processed.reward], dtype=np.float32),
                    done=np.array([False], dtype=np.bool_),
                    infos=[{"TimeLimit.truncated": False}],
                )
            action, _ = model.predict(obs, deterministic=True)
            action_val = map_action(float(action[0]))
            fp.update_pre_action(qp_id, action_val)
            fp.write_action(qp_id, action_val)

            last_obs[qp_id] = obs
            last_action[qp_id] = np.array([action_val], dtype=np.float32)
            step_counter += 1

        if (
            not INFER_ONLY
            and step_counter >= ONLINE_TRAIN_INTERVAL
            and model.replay_buffer.size() > model.learning_starts
        ):
            model.train(batch_size=model.batch_size, gradient_steps=ONLINE_GRADIENT_STEPS)
            _save_model(model)
            step_counter = 0
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
