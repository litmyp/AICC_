# lty 用于实现ns3网络仿真的gym环境

import gym
from gym import spaces
import numpy as np
import mmap
import struct
import os
import ctypes
import time
from reader_lty import read_rtt_from_shm, SHM_NAME, RttShmData#, get_version_tuple

import pdb

class NS3Env(gym.Env):
    # 自定义环境类
    
    def __init__(self, min_action=1.0, max_action=100.0, action_dim=1, max_steps=1000):
        super().__init__()
        
        # 1. 定义状态空间：rtt纳秒、cnp标记位、timestamp_ns（由共享内存提供）
        # 保持与共享内存一致的精度（rtt_ns/ timestamp_ns 为 uint64）
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(3,),  # rtt, cnp, timestamp_ns
            dtype=np.float64
        )
        
        # 2. 定义动作空间为发送速率
        self.action_space = spaces.Box(
            low=min_action,
            high=max_action,
            shape=(action_dim,),  # action_dim 由参数传入， 其实就是1
            dtype=np.float32
        )
        
        # 3. 共享内存相关（由ns3创建和销毁，Python端只使用）
        # 状态共享内存（只读）：用于读取RTT和CNP信息
        self.state_shm_mmap = None  # 状态共享内存映射对象
        self.last_version = None  # 用于检测数据更新
        self._last_data = None  # 最近一次读取到的原始数据
        # 动作共享内存（可写）：用于写入动作（发送速率）
        self.action_shm_mmap = None  # 动作共享内存映射对象
        self.poll_interval = 0.001
        self.wait_timeout = None
        
        # 4. 环境参数
        self.step_count = 0
        self.max_steps = max_steps
        self.min_action = min_action
        self.max_action = max_action
    
    def _wait_for_new_data(self):
        """
        以timestamp_ns作为版本号，要求严格递增才视为新数据
        """
        start_time = time.time()
        while True:
            data, self.state_shm_mmap = read_rtt_from_shm(self.state_shm_mmap, check_file_exists=False)
            if data is None:
                return None
            
            # 使用 timestamp_ns 作为版本号，要求严格递增才视为新数据
            ts = getattr(data, "timestamp_ns", None)
            if ts is None:
                ts = 0

            if self.last_version is None or ts > self.last_version:
                self.last_version = ts
                self._last_data = data
                return data

            # 若设置了超时，则超时后返回当前数据
            if self.wait_timeout is not None and (time.time() - start_time) >= self.wait_timeout:
                self._last_data = data
                return data

            time.sleep(self.poll_interval)

    # 备份
    # def _wait_for_new_data(self):
    #     """
    #     等待共享内存中的数据出现变化（sequence/node_id/timestamp_ns 任一不同）。
    #     如果 wait_timeout 为 None，则持续等待直至新数据到来；否则在超时后返回最后一次读取的数据。
    #     """
    #     start_time = time.time()
    #     while True:
    #         data, self.state_shm_mmap = read_rtt_from_shm(self.state_shm_mmap, check_file_exists=False)
    #         if data is None:
    #             return None
    #         version = get_version_tuple(data)
    #         if self.last_version is None or version != self.last_version:
    #             self.last_version = version
    #             self._last_data = data
    #             return data
    #         if self.wait_timeout is not None and (time.time() - start_time) >= self.wait_timeout:
    #             self._last_data = data
    #             return data
    #         time.sleep(self.poll_interval)

    def _read_observation(self): #从状态共享内存读取观测值（RTT和CNP）

        data = self._wait_for_new_data()

        if data is None:
            # 如果读取失败（共享内存可能还未创建或被销毁），返回零值
            return np.array([0.0, 0.0, 0.0], dtype=np.float32)
        
        # 提取RTT、CNP以及timestamp（纳秒）
        # 直接保持双精度，避免 uint64 时间戳精度丢失
        rtt_ns = np.float64(data.rtt_ns)  # 纳秒
        cnp = np.float64(data.cnp)
        timestamp_ns = np.float64(getattr(data, "timestamp_ns", 0))
        
        observation = np.array([rtt_ns, cnp, timestamp_ns], dtype=np.float64)
        return observation
    
    def clip_action(self, action):
        """
        将action平滑映射到有效范围内（min_action到max_action之间）
        使用tanh函数进行平滑映射，避免粗暴截断
        
        Args:
            action: 原始动作值，可以是numpy数组或标量
            
        Returns:
            numpy.ndarray: 映射后的动作值（保持与输入相同的格式）
        """
        # 提取动作值（如果是数组，取第一个元素）
        if isinstance(action, np.ndarray):
            raw_rate = float(action[0])
            # 使用tanh进行平滑映射
            # 假设输入范围大致在[-max_action, max_action]，先归一化到[-1, 1]
            # 使用缩放因子确保tanh能充分利用输入范围
            scale_factor = self.max_action  # 可根据实际情况调整
            normalized = np.tanh(raw_rate / scale_factor)  # 映射到 [-1, 1]
            # 将[-1, 1]线性映射到[min_action, max_action]
            rate = self.min_action + (normalized + 1.0) / 2.0 * (self.max_action - self.min_action)
            print(f"原始rate: {raw_rate:.4f} Gbps, 归一化后: {normalized:.4f}, 映射后rate: {rate:.4f} Gbps")
            # 返回相同格式的数组
            return np.array([rate], dtype=action.dtype)
        else:
            raw_rate = float(action)
            # 使用tanh进行平滑映射
            scale_factor = self.max_action
            normalized = np.tanh(raw_rate / scale_factor)
            rate = self.min_action + (normalized + 1.0) / 2.0 * (self.max_action - self.min_action)
            print(f"原始rate: {raw_rate:.4f} Gbps, 归一化后: {normalized:.4f}, 映射后rate: {rate:.4f} Gbps")
            return rate
    
    def _update_action(self, action): # 将发送速率写回ns3，变量是float类型，单位为Gbps
        meta = self._last_data
        if meta is not None:
            print(
                f"推理得到的action是: {action} Gbps (node_id={meta.node_id}, "
                f"sequence={meta.sequence}, timestamp_ns={meta.timestamp_ns})"
            )
        else:
            print(f"推理得到的action是: {action} Gbps (元数据未知)")

        # 提取动作值（如果是数组，取第一个元素；此时action已经是clip后的）
        rate = float(action[0]) if isinstance(action, np.ndarray) else float(action)
        # 使用与状态共享内存相同的共享内存（发送速率写在cnp后面的padding区域）
        shm_path = f"/dev/shm{SHM_NAME}"
        
        try:
            # 如果共享内存不存在，返回（由ns3创建）
            if not os.path.exists(shm_path):
                return
            
            # 如果还没有映射，打开并映射
            # 共享内存大小就是RttShmData的大小（速率写在padding区域，不需要额外空间）
            if self.action_shm_mmap is None:
                shm_fd = open(shm_path, "r+b")
                shm_size = ctypes.sizeof(RttShmData)  # RttShmData的大小（112字节）
                self.action_shm_mmap = mmap.mmap(shm_fd.fileno(), shm_size, access=mmap.ACCESS_WRITE)
                shm_fd.close()
            
            # 计算发送速率在共享内存中的偏移量（在cnp字段之后，padding区域的开头）
            # cnp字段偏移量 + cnp字段大小 = 48 + 1 = 49字节
            cnp_offset = RttShmData.cnp.offset
            cnp_size = ctypes.sizeof(ctypes.c_uint8)
            rate_offset = cnp_offset + cnp_size  # 49字节
            
            # 写入速率值（使用struct.pack将float转换为4字节）
            ctypes.c_float.from_buffer(self.action_shm_mmap, rate_offset).value = float(rate)
            self.action_shm_mmap.flush()
            
        except Exception as e:
            # 如果写入失败，不中断程序，只打印错误
            print(f"写入动作共享内存时出错: {e}")
    
    def _calculate_reward(self, state, next_state): #计算reward TODO: 根据实际需求调整奖励函数

        # rtt_ns = state[0]
        cnp = state[1] 
        # rtt_penalty = -rtt_ns * 1e-7  # 1e-7 = 0.1 / 1000000，保持与毫秒版本相同的比例
        # cnp_penalty = -cnp * 1.0  # CNP=1时惩罚-1.0，CNP=0时无惩罚
        
        # reward = rtt_penalty + cnp_penalty
        next_rtt = next_state[0]
        pre_rtt = state[0]
        dt = next_state[2] - state[2]
        #print(f"计算奖励函数时，打印时间戳,旧的是{state[2]} 新的是{next_state[2]}")
        #pdb.set_trace()
        # 防止时间戳无效或为0导致除零/NaN
        if not np.isfinite(dt) or dt == 0:
            print(f"calculate_reward: 非法时间差 dt={dt}, 使用仅基于cnp的惩罚")
            pdb.set_trace()
            return -cnp * 1.0
        dr = next_rtt - pre_rtt
        if not np.isfinite(dr):
            print(f"calculate_reward: 非法rtt差值 dr={dr}, 使用仅基于cnp的惩罚")
            return -cnp * 1.0
        diff = dr / dt
        reward = -diff * 0.1 - cnp * 1.0
        
        return reward
    
    def reset(self, seed=None, options=None): #重置环境，开始新的episode
        # 调用父类的reset方法（设置随机种子）
        super().reset(seed=seed)
        
        # 重置步数计数
        self.step_count = 0
        self.last_version = None
        self._last_data = None
        
        # 从共享内存读取初始观测值（由ns3写入）
        state = self._read_observation()
        info = {}  # 可选：返回额外信息
        return state, info
    
    def step(self, action): #执行一步动作

        # 1. 将动作传递给ns3（动作更新）

        self._update_action(action)
        
        # 2. 从共享内存读取新状态（状态读取，由ns3写入）
        next_state = self._read_observation()
        
        # 3. 奖励计算由上层在拼接完整transition时决定，这里先置零
        reward = 0.0
        
        # 4. 判断是否结束
        self.step_count += 1
        done = False  # 根据环境逻辑判断（例如：达到目标性能）
        truncated = (self.step_count >= self.max_steps)  # 步数限制
        info = {}  # 可选：返回额外信息
        
        return next_state, reward, done, truncated, info
    
    # def render(self, mode='human'):
    #     """
    #     渲染环境（可选，用于可视化）
    #     """
    #     pass
    
    def close(self):

        # 关闭状态共享内存映射（不销毁共享内存本身）
        if self.state_shm_mmap is not None:
            self.state_shm_mmap.close()
            self.state_shm_mmap = None
        
        # 关闭动作共享内存映射（不销毁共享内存本身）
        if self.action_shm_mmap is not None:
            self.action_shm_mmap.close()
            self.action_shm_mmap = None