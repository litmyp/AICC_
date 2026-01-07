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
    
    def __init__(self, min_action=1.0, max_action=100.0, action_dim=1, max_steps=1000, link_capacity_bps=100e9):
        super().__init__()
        
        # 1. 定义状态空间：rtt纳秒、cnp标记位、timestamp_ns、qp当前速率（Gbps）
        # 保持与共享内存一致的精度（rtt_ns/ timestamp_ns 为 uint64）
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(4,),  # rtt, cnp, timestamp_ns, qp_rate
            dtype=np.float64
        )
        
        # 2. 定义动作空间为“下一步目标速率”（Gbps） lty added
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
        # lty added: 链路带宽（用于 util 计算，默认 100Gbps，可按拓扑调整）
        self.link_capacity_bps = link_capacity_bps
    
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
            return np.array([0.0, 0.0, 0.0, 0.0], dtype=np.float64)
        
        # 提取RTT、CNP以及timestamp（纳秒）
        # 直接保持双精度，避免 uint64 时间戳精度丢失
        rtt_ns = np.float64(data.rtt_ns)  # 纳秒
        cnp = np.float64(data.cnp)
        timestamp_ns = np.float64(getattr(data, "timestamp_ns", 0))
        qp_rate = np.float64(getattr(data, "qp_rate", 0.0))  # 当前QP速率（Gbps）
        
        observation = np.array([rtt_ns, cnp, timestamp_ns, qp_rate], dtype=np.float64)
        return observation
    
    def clip_action(self, action):
        """
        将模型输出（无界）压缩到目标速率区间 [min_action, max_action] Gbps，先 tanh 再线性映射 lty added
        """
        if isinstance(action, np.ndarray):
            raw_val = float(action[0])
        else:
            raw_val = float(action)

        # 平滑压缩到 [-1, 1]（避免无界输出触发硬截断） lty added
        normalized = np.tanh(raw_val)
        # 线性映射到速率区间 lty added
        rate = (normalized + 1.0) * 0.5 * (self.max_action - self.min_action) + self.min_action
        rate = np.clip(rate, self.min_action, self.max_action)  # lty added: 边界保护

        print(f"原始输出: {raw_val:.4f}, 归一化: {normalized:.4f}, 目标速率: {rate:.4f} Gbps")

        if isinstance(action, np.ndarray):
            return np.array([rate], dtype=action.dtype)
        return rate
    
    def _update_action(self, action): # lty added: 将目标速率写回ns3，供仿真端直接设置速率
        meta = self._last_data
        if meta is not None:
            print(
                f"推理得到的目标速率: {action} Gbps (node_id={meta.node_id}, "
                f"sequence={meta.sequence}, timestamp_ns={meta.timestamp_ns})"
            )
        else:
            print(f"推理得到的目标速率: {action} Gbps (元数据未知)")

        # lty added: 提取动作值（目标速率 Gbps）
        rate = float(action[0]) if isinstance(action, np.ndarray) else float(action)
        # 使用与状态共享内存相同的共享内存（发送速率写在padding末尾的保留空间）
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
            
            # lty added: 写入目标速率（Gbps），仿真端直接使用
            data_view = RttShmData.from_buffer(self.action_shm_mmap)
            data_view.new_rate = float(rate)
            self.action_shm_mmap.flush()
            
        except Exception as e:
            # 如果写入失败，不中断程序，只打印错误
            print(f"写入动作共享内存时出错: {e}")
    
    def _calculate_reward(self, state, next_state): #计算reward TODO: 根据实际需求调整奖励函数
        ''' 1.ADPG中的奖励函数
        beta = 1.5
        target = 0.064
        scale = 12.5 # 以上三个数值可能需要调整

        base_rtt = 6000 # 暂定且写死，保留了一定的余量

        rtt_inflation = state[0] / base_rtt # 此处的rtt_inf是相对于basertt的，不是两个状态间的rtt变化
        rtt_inflation = max(rtt_inflation - beta, 0)
        reward = rtt_inflation * np.sqrt(state[3])
        reward = (reward - target) * scale

        return reward
        '''

        ''' 2.
        beta = 1
        target = 0.064
        scale = 12.5 # 以上三个数值可能需要调整
        k = 0.5 # cnp系数

        base_rtt = 4160 # 暂定且写死，保留了一定的余量

        init_rate = 100 #暂定写死100Gbps

        rtt_inflation = state[0] / base_rtt # 此处的rtt_inf是相对于basertt的，不是两个状态间的rtt变化
        rtt_inflation = max(rtt_inflation - beta, 0)
        reward = rtt_inflation * np.sqrt(state[3])
        reward = (reward - target) * scale + state[3] / init_rate - k * state[1]

        return reward  
        ''' 
        ''' 3.
        beta = 1
        # target = 0.064
        scale = 12.5 # 以上三个数值可能需要调整
        k = 0.5 # cnp系数

        base_rtt = 4160 # 暂定且写死，保留了一定的余量

        init_rate = 100 #暂定写死100Gbps

        rtt_inflation = next_state[0] / base_rtt # 此处的rtt_inf是相对于basertt的，不是两个状态间的rtt变化
        rtt_inflation = max(rtt_inflation - beta, 0)
        reward = rtt_inflation * np.sqrt(next_state[3])
        reward = reward * scale + next_state[3] / init_rate - k * next_state[1]

        return reward  
        '''
        '''
        4.
        beta = 1

        base_rtt = 4160 # 暂定且写死，保留了一定的余量
        init_rate = 100 #暂定写死100Gbps

        rtt_inflation = state[0] / base_rtt # 此处的rtt_inf是相对于basertt的，不是两个状态间的rtt变化
        rtt_inflation = max(rtt_inflation - beta, 0)
        reward = state[3] / init_rate - rtt_inflation - state[1] # util - rtt_inflation -cnp

        return reward  
        '''
        '''5.
        k_cnp = 0.5

        base_rtt = 4160 # 暂定且写死，保留了一定的余量
        init_rate = 100 #暂定写死100Gbps

        reward = state[3] / init_rate + base_rtt / state[0] - k_cnp * state[1] # util - 1/rtt_inflation -0.5*cnp

        return reward  
        '''
        # '''6.
        k_util = 0.1
        k_rtt = 0.6
        k_cnp = 0.3

        base_rtt = 4160 # 暂定且写死，保留了一定的余量
        init_rate = 100 #暂定写死100Gbps

        reward = k_util * next_state[3] / init_rate + k_rtt * (base_rtt / next_state[0]- 1) - k_cnp * next_state[1] # util - 1/rtt_inflation -0.5*cnp

        return reward 
        # '''
        '''12.
        return next_state[3]*0.001 -next_state[1] - next_state[0] * 1e-6
        '''
        '''7.
        k_util = 0.6
        k_rtt = 1.4
        k_cnp = 2

        base_rtt = 4160 # 暂定且写死，保留了一定的余量
        init_rate = 100 #暂定写死100Gbps

        reward = k_util * state[3] / init_rate + k_rtt * (base_rtt / state[0] - 1) - k_cnp * state[1] # util - 1/rtt_inflation -0.5*cnp

        return reward
        '''
        '''8. state ->next_state
        k_util = 0.7 * 0.125
        k_rtt = 1
        k_cnp = 1

        base_rtt = 4160 # 暂定且写死，保留了一定的余量
        init_rate = 100 #暂定写死100Gbps

        reward = k_util * next_state[3] / init_rate + k_rtt * (base_rtt / next_state[0] - 1) - k_cnp * next_state[1] # util - 1/rtt_inflation -0.5*cnp

        return reward
        '''

        '''9
        k_util = 0.7
        k_rtt = 1
        k_cnp = 1

        base_rtt = 4160 # 暂定且写死，保留了一定的余量
        init_rate = 100 #暂定写死100Gbps

        reward = k_util * state[3] / init_rate + k_rtt * (base_rtt / state[0] - 1) - k_cnp * state[1] # util - 1/rtt_inflation -0.5*cnp

        return reward * 0.07
        '''
        ''' 10.
        rtt = state[0]
        cnp = state[1]
        reward = - rtt * 1e-6 - cnp # 加上rate吗
        return reward
        '''
        ''' 11.
        k_util = 0.7
        k_rtt = 1
        k_cnp = 1

        base_rtt = 4160 # 暂定且写死，保留了一定的余量
        init_rate = 100 #暂定写死100Gbps

        reward = k_util * next_state[3] / init_rate + k_rtt * (base_rtt / next_state[0] - 1) - k_cnp * next_state[1] # util - 1/rtt_inflation -0.5*cnp

        return reward
        '''

        
    
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
