
#lty 在基础的DDPG算法修改

import numpy as np  # 导入 NumPy，用于处理数组和数学运算
import torch  # 导入 PyTorch，用于构建和训练神经网络
import torch.nn as nn  # 导入 PyTorch 的神经网络模块
import torch.optim as optim  # 导入 PyTorch 的优化器模块
from collections import deque  # 导入双端队列，用于实现经验回放池
import random  # 导入随机模块，用于从经验池中采样
import os  # 导入操作系统模块，用于文件路径操作
from NS3Env import NS3Env  # 导入自定义的网络环境

import pdb
 
# 定义 TSP 全连接网络
class TSP(nn.Module):
    def __init__(self, input_dim, hidden_dim=256):
        super(TSP, self).__init__()
        self.linear1 = nn.Linear(input_dim, hidden_dim)
        self.relu = nn.ReLU()
        self.output_dim = hidden_dim

    def forward(self, x):
        x = self.linear1(x)
        x = self.relu(x)
        return x

# 定义 MLP 全连接网络
class MLP(nn.Module):
    def __init__(self, input_dim, hidden_dim=256, output_dim=1, output_activation=None):
        super(MLP, self).__init__()
        self.linear1 = nn.Linear(input_dim, hidden_dim)
        self.relu = nn.ReLU()
        self.linear2 = nn.Linear(hidden_dim, output_dim)
        self.output_activation = output_activation

    def forward(self, x):
        x = self.linear1(x)
        x = self.relu(x)
        x = self.linear2(x)
        if self.output_activation is not None:
            x = self.output_activation(x)
        return x
 
# 定义 Actor 网络（策略网络）
class Actor(nn.Module):
    def __init__(self, state_dim, action_dim, max_action):
        super(Actor, self).__init__()
        self.tsp = TSP(state_dim, 256)
        self.mlp = MLP(self.tsp.output_dim, 256, action_dim)
        self.max_action = max_action
 
    def forward(self, state):
        features = self.tsp(state)
        action = self.mlp(features)
        action = torch.tanh(action) * self.max_action
        return action
 
# 定义 Critic 网络（价值网络）
class Critic(nn.Module):
    def __init__(self, state_dim, action_dim):
        super(Critic, self).__init__()
        self.tsp = TSP(state_dim + action_dim, 256)
        self.mlp = MLP(self.tsp.output_dim, 256, 1)
 
    def forward(self, state, action):
        x = torch.cat([state, action], dim=1)
        features = self.tsp(x)
        q_value = self.mlp(features)
        return q_value
 
# 定义经验回放池
class ReplayBuffer:
    def __init__(self, max_size):
        self.buffer = deque(maxlen=max_size)  # 初始化一个双端队列，设置最大容量
 
    def add(self, state, action, reward, next_state, done):
        self.buffer.append((state, action, reward, next_state, done))  # 将经验存入队列
 
    def sample(self, batch_size):
        batch = random.sample(self.buffer, batch_size)  # 随机采样一个小批量数据
        states, actions, rewards, next_states, dones = zip(*batch)  # 解压采样数据
        return (np.array(states), np.array(actions), np.array(rewards),
                np.array(next_states), np.array(dones))  # 返回 NumPy 数组格式的数据
 
    def size(self):
        return len(self.buffer)  # 返回经验池中当前存储的样本数量
 
# DDPG智能体类定义
class DDPGAgent:
    # 初始化方法，设置智能体的参数和模型
    def __init__(self, state_dim, action_dim, max_action, gamma=0.99, tau=0.005, buffer_size=100000, batch_size=64):
        # 定义actor网络（策略网络）及其目标网络
        self.actor = Actor(state_dim, action_dim, max_action)
        self.actor_target = Actor(state_dim, action_dim, max_action)
        # 将目标actor网络的参数初始化为与actor网络一致
        self.actor_target.load_state_dict(self.actor.state_dict())
        # 定义actor网络的优化器
        self.actor_optimizer = optim.Adam(self.actor.parameters(), lr=1e-4)
 
        # 定义critic网络（值网络）及其目标网络
        self.critic = Critic(state_dim, action_dim)
        self.critic_target = Critic(state_dim, action_dim)
        # 将目标critic网络的参数初始化为与critic网络一致
        self.critic_target.load_state_dict(self.critic.state_dict())
        # 定义critic网络的优化器
        self.critic_optimizer = optim.Adam(self.critic.parameters(), lr=1e-3)
 
        # 保存动作的最大值，用于限制动作范围
        self.max_action = max_action
        # 折扣因子，用于奖励的时间折扣
        self.gamma = gamma
        # 软更新系数，用于目标网络的更新
        self.tau = tau
        # 初始化经验回放池
        self.replay_buffer = ReplayBuffer(buffer_size)
        # 每次训练的批量大小
        self.batch_size = batch_size
 
    # 选择动作的方法
    def select_action(self, state, noise_std=0.0):
        # 将状态转换为张量
        state = torch.FloatTensor(state.reshape(1, -1))
        # 使用actor网络预测动作，并将结果转换为NumPy数组
        action = self.actor(state).detach().cpu().numpy().flatten()
        if noise_std > 0.0:
            noise = np.random.normal(0, noise_std, size=action.shape)
            action = action + noise
        action = np.clip(action, -self.max_action, self.max_action)
        return action
 
    # 训练方法
    def train(self):
        # 如果回放池中样本数量不足，直接返回
        if self.replay_buffer.size() < self.batch_size:
            print(f"回放池中样本数量不足，直接返回")
            return {
                "trained": False,
                "reason": "insufficient_data",
                "buffer_size": self.replay_buffer.size(),
                "batch_size": self.batch_size,
            }
 
        # 从回放池中采样一批数据
        states, actions, rewards, next_states, dones = self.replay_buffer.sample(self.batch_size)
 
        # 将采样的数据转换为张量
        states = torch.FloatTensor(states)
        actions = torch.FloatTensor(actions)
        rewards = torch.FloatTensor(rewards).unsqueeze(1)  # 添加一个维度以匹配Q值维度
        next_states = torch.FloatTensor(next_states)
        dones = torch.FloatTensor(dones).unsqueeze(1)  # 添加一个维度以匹配Q值维度
 
        # 计算critic的损失
        with torch.no_grad():  # 关闭梯度计算
            next_actions = self.actor_target(next_states)  # 使用目标actor网络预测下一步动作
            target_q = self.critic_target(next_states, next_actions)  # 目标Q值
            # 使用贝尔曼方程更新目标Q值
            target_q = rewards + (1 - dones) * self.gamma * target_q
 
        # 当前Q值
        current_q = self.critic(states, actions)
        # 均方误差损失
        critic_loss = nn.MSELoss()(current_q, target_q)

        # 优化critic网络
        self.critic_optimizer.zero_grad()
        critic_loss.backward()
        self.critic_optimizer.step()

        # 计算actor的损失
        actor_loss = -self.critic(states, self.actor(states)).mean()  # 策略梯度目标为最大化Q值

        # 优化actor网络
        self.actor_optimizer.zero_grad()
        actor_loss.backward()
        self.actor_optimizer.step()

        # 更新目标网络参数（软更新）
        for target_param, param in zip(self.critic_target.parameters(), self.critic.parameters()):
            target_param.data.copy_(self.tau * param.data + (1 - self.tau) * target_param.data)

        for target_param, param in zip(self.actor_target.parameters(), self.actor.parameters()):
            target_param.data.copy_(self.tau * param.data + (1 - self.tau) * target_param.data)

        # 计算Q值统计信息
        with torch.no_grad():
            q_mean = current_q.mean().item()
            q_std = current_q.std().item()
            q_min = current_q.min().item()
            q_max = current_q.max().item()
            target_q_mean = target_q.mean().item()

        return {
            "trained": True,
            "critic_loss": critic_loss.item(),
            "actor_loss": actor_loss.item(),
            "buffer_size": self.replay_buffer.size(),
            "q_mean": q_mean,
            "q_std": q_std,
            "q_min": q_min,
            "q_max": q_max,
            "target_q_mean": target_q_mean,
        }
 
    # 将样本添加到回放池中
    def add_to_replay_buffer(self, state, action, reward, next_state, done):
        self.replay_buffer.add(state, action, reward, next_state, done)
    
    # 获取模型参数的统计信息
    def get_model_stats(self, network_name="actor"):
        """
        获取模型参数的统计信息
        Args:
            network_name: 网络名称，'actor' 或 'critic'
        Returns:
            dict: 包含参数统计信息的字典
        """
        if network_name == "actor":
            network = self.actor
        elif network_name == "critic":
            network = self.critic
        else:
            raise ValueError("network_name must be 'actor' or 'critic'")
        
        all_params = []
        for param in network.parameters():
            if param.requires_grad:
                all_params.append(param.data.cpu().numpy().flatten())
        
        if len(all_params) == 0:
            return {}
        
        all_params = np.concatenate(all_params)
        
        return {
            "mean": float(np.mean(all_params)),
            "std": float(np.std(all_params)),
            "min": float(np.min(all_params)),
            "max": float(np.max(all_params)),
        }

    # 保存模型的方法
    def save(self, filepath):
        """
        保存模型到指定路径
        Args:
            filepath: 保存路径（不需要包含文件扩展名，会自动添加.pth）
        """
        # 确保目录存在
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)
        
        # 保存所有网络和优化器的状态
        checkpoint = {
            'actor_state_dict': self.actor.state_dict(),
            'actor_target_state_dict': self.actor_target.state_dict(),
            'critic_state_dict': self.critic.state_dict(),
            'critic_target_state_dict': self.critic_target.state_dict(),
            'actor_optimizer_state_dict': self.actor_optimizer.state_dict(),
            'critic_optimizer_state_dict': self.critic_optimizer.state_dict(),
            'max_action': self.max_action,
            'gamma': self.gamma,
            'tau': self.tau,
        }
        
        # 如果文件路径没有扩展名，添加.pth
        if not filepath.endswith('.pth') and not filepath.endswith('.pt'):
            filepath += '.pth'
        
        torch.save(checkpoint, filepath)
        print(f"模型已保存到: {filepath}")

    # 加载模型的方法
    def load(self, filepath):
        """
        从指定路径加载模型
        Args:
            filepath: 模型文件路径
        Returns:
            bool: 如果成功加载返回True，如果文件不存在返回False
        """
        if not os.path.exists(filepath):
            print(f"模型文件不存在: {filepath}，将使用新初始化的模型继续训练")
            return False
        
        checkpoint = torch.load(filepath, map_location='cpu')
        
        try:
            # 加载网络状态
            self.actor.load_state_dict(checkpoint['actor_state_dict'], strict=False)
            self.actor_target.load_state_dict(checkpoint['actor_target_state_dict'], strict=False)
            self.critic.load_state_dict(checkpoint['critic_state_dict'], strict=False)
            self.critic_target.load_state_dict(checkpoint['critic_target_state_dict'], strict=False)
            
            # 加载优化器状态（如果存在）
            if 'actor_optimizer_state_dict' in checkpoint:
                self.actor_optimizer.load_state_dict(checkpoint['actor_optimizer_state_dict'])
            if 'critic_optimizer_state_dict' in checkpoint:
                self.critic_optimizer.load_state_dict(checkpoint['critic_optimizer_state_dict'])
            
            # 加载其他参数（如果存在）
            if 'max_action' in checkpoint:
                self.max_action = checkpoint['max_action']
            if 'gamma' in checkpoint:
                self.gamma = checkpoint['gamma']
            if 'tau' in checkpoint:
                self.tau = checkpoint['tau']
            
            print(f"模型已从 {filepath} 加载")
            return True
        except Exception as e:
            print(f"加载模型时出现错误: {e}，将使用新初始化的模型继续训练")
            return False
 
# 绘制学习曲线的方法
import matplotlib.pyplot as plt
 
def train_ddpg(episodes=1000, max_steps=200, env_kwargs=None, exploration_noise=0.1, 
               model_save_dir="./models", load_model_path=None, save_frequency=100, batch_size=64,
               train_frequency=1):
    """
    训练DDPG智能体
    Args:
        episodes: 训练轮数
        max_steps: 每个episode的最大步数
        env_kwargs: 环境参数字典
        exploration_noise: 探索噪声系数
        model_save_dir: 模型保存目录
        load_model_path: 要加载的模型路径（如果为None则不加载）
        save_frequency: 每隔多少个episode保存一次模型（0表示只在训练结束时保存）
        batch_size: 训练时的批量大小
        train_frequency: 每隔多少步训练一次（1表示每步都训练，2表示每2步训练一次，以此类推）
    """
    # 创建自定义网络环境
    env_kwargs = env_kwargs or {}
    if "max_steps" not in env_kwargs:
        env_kwargs["max_steps"] = max_steps
    env = NS3Env(**env_kwargs)
    state_dim = env.observation_space.shape[0]  # 状态空间维度
    action_dim = env.action_space.shape[0]  # 动作空间维度
    max_action = float(env.action_space.high[0])  # 动作最大值（单位：Gbps）

    # 初始化DDPG智能体
    agent = DDPGAgent(state_dim, action_dim, max_action, batch_size=batch_size)
    
    # 如果提供了模型路径，加载已有模型
    if load_model_path is not None:
        agent.load(load_model_path)
    
    rewards = []  # 用于存储每个episode的奖励

    episode_limit = env_kwargs.get("max_steps", getattr(env, "max_steps", max_steps))
    
    # 创建模型保存目录
    if model_save_dir:
        os.makedirs(model_save_dir, exist_ok=True)

    def _extract_env_meta(env_obj):
        """
        从环境中提取当前共享内存记录的元信息（node_id、sequence）。
        如果环境侧暂时没有元数据，则返回 (None, None)。
        """
        meta = getattr(env_obj, "_last_data", None)
        node_id = getattr(meta, "node_id", None) if meta is not None else None
        sequence = getattr(meta, "sequence", None) if meta is not None else None
        return node_id, sequence

    pending_transitions = {}
    step_count = 0  # 全局步数计数器，用于控制训练频率

    for episode in range(episodes):
        pending_transitions.clear()
        state, _ = env.reset()  # 重置环境，获取初始状态
        current_node_id, current_sequence = _extract_env_meta(env)
        episode_reward = 0  # 初始化每轮奖励为0
        for step in range(episode_limit):
            # 在每个episode的第一步打印推理前的模型参数统计信息
            if step == 0:
                actor_stats_before = agent.get_model_stats("actor")
                critic_stats_before = agent.get_model_stats("critic")
                print(f"[推理前] Episode {episode+1}, Step {step+1} - Actor参数: mean={actor_stats_before.get('mean', 0):.6f}, std={actor_stats_before.get('std', 0):.6f}, "
                      f"min={actor_stats_before.get('min', 0):.6f}, max={actor_stats_before.get('max', 0):.6f}")
                print(f"[推理前] Episode {episode+1}, Step {step+1} - Critic参数: mean={critic_stats_before.get('mean', 0):.6f}, std={critic_stats_before.get('std', 0):.6f}, "
                      f"min={critic_stats_before.get('min', 0):.6f}, max={critic_stats_before.get('max', 0):.6f}")
            
            # 选择动作
            noise_std = exploration_noise * agent.max_action if exploration_noise else 0.0
            action = agent.select_action(state, noise_std=noise_std)

            # 缓存当前node的state/action，等待下一次该node的数据来拼接transition
            if current_node_id is not None:
                pending_transitions[current_node_id] = {
                    "state": np.array(state, copy=True),
                    "action": np.array(action, copy=True),
                }
                print(f"======当前node_id是: {current_node_id}, 当前sequence是: {current_sequence}")
                print(f"======当前state是: {state}, 当前action是: {action}")
            else:    
                print(f"======当前node_id是: None, 当前sequence是: {current_sequence}")
            #pdb.set_trace()

            # 执行动作，获取环境反馈（reward 在此暂不使用，稍后重新计算）
            next_state, reward, done, truncated, _ = env.step(action)
            next_node_id, next_sequence = _extract_env_meta(env)

            # 只有在拿到同一条流下一次的state时才补齐transition
            if (
                next_node_id is not None
                and next_sequence is not None
                and next_sequence > 1
            ):
                pending_entry = pending_transitions.pop(next_node_id, None)
                if pending_entry is not None:
                    # 在拼接完整 transition 时重新计算奖励
                    computed_reward = env._calculate_reward(next_state)
                    agent.add_to_replay_buffer(
                        pending_entry["state"],
                        pending_entry["action"],
                        computed_reward,
                        next_state,
                        done or truncated,
                    )
                    print(f"======添加到回放池中: {pending_entry['state']}, {pending_entry['action']}, {computed_reward}, {next_state}, {done or truncated}")
                    # 累加奖励：仅在成功拼接并重算奖励时累计
                    episode_reward += computed_reward
 
            # 根据训练频率决定是否训练
            step_count += 1
            if step_count % train_frequency == 0:
                # 训练前获取模型参数统计
                actor_stats_before_train = agent.get_model_stats("actor")
                critic_stats_before_train = agent.get_model_stats("critic")
                
                # 执行训练
                train_result = agent.train()
                
                if train_result.get("trained", False):
                    # 训练后获取模型参数统计
                    actor_stats_after_train = agent.get_model_stats("actor")
                    critic_stats_after_train = agent.get_model_stats("critic")
                    
                    # 计算参数变化
                    actor_param_change = {
                        "mean": actor_stats_after_train.get("mean", 0) - actor_stats_before_train.get("mean", 0),
                        "std": actor_stats_after_train.get("std", 0) - actor_stats_before_train.get("std", 0),
                    }
                    critic_param_change = {
                        "mean": critic_stats_after_train.get("mean", 0) - critic_stats_before_train.get("mean", 0),
                        "std": critic_stats_after_train.get("std", 0) - critic_stats_before_train.get("std", 0),
                    }
                    
                    # 打印训练信息
                    print(f"[训练] Step {step_count} - Critic Loss: {train_result.get('critic_loss', 0):.6f}, "
                          f"Actor Loss: {train_result.get('actor_loss', 0):.6f}")
                    print(f"[训练] Step {step_count} - Q值统计: mean={train_result.get('q_mean', 0):.4f}, "
                          f"std={train_result.get('q_std', 0):.4f}, min={train_result.get('q_min', 0):.4f}, "
                          f"max={train_result.get('q_max', 0):.4f}, target_mean={train_result.get('target_q_mean', 0):.4f}")
                    print(f"[训练] Step {step_count} - 回放池大小: {train_result.get('buffer_size', 0)}")
                    print(f"[训练后] Step {step_count} - Actor参数变化: mean_change={actor_param_change['mean']:.6f}, "
                          f"std_change={actor_param_change['std']:.6f}")
                    print(f"[训练后] Step {step_count} - Actor参数: mean={actor_stats_after_train.get('mean', 0):.6f}, "
                          f"std={actor_stats_after_train.get('std', 0):.6f}, min={actor_stats_after_train.get('min', 0):.6f}, "
                          f"max={actor_stats_after_train.get('max', 0):.6f}")
                    print(f"[训练后] Step {step_count} - Critic参数变化: mean_change={critic_param_change['mean']:.6f}, "
                          f"std_change={critic_param_change['std']:.6f}")
                    print(f"[训练后] Step {step_count} - Critic参数: mean={critic_stats_after_train.get('mean', 0):.6f}, "
                          f"std={critic_stats_after_train.get('std', 0):.6f}, min={critic_stats_after_train.get('min', 0):.6f}, "
                          f"max={critic_stats_after_train.get('max', 0):.6f}")
                    print("-" * 80)
            
            # 更新当前状态
            state = next_state     
            current_node_id, current_sequence = next_node_id, next_sequence
            if done or truncated:  # 如果完成或达到步数限制，结束本轮
                break
 
        # 记录每轮的累计奖励
        rewards.append(episode_reward)
        
        # Episode结束时的统计信息
        actor_stats_episode = agent.get_model_stats("actor")
        critic_stats_episode = agent.get_model_stats("critic")
        buffer_size = agent.replay_buffer.size()
        
        print(f"\n{'='*80}")
        print(f"[Episode {episode + 1} 结束]")
        print(f"  Total Reward: {episode_reward:.4f}")
        print(f"  回放池大小: {buffer_size}")
        print(f"  Actor参数统计: mean={actor_stats_episode.get('mean', 0):.6f}, std={actor_stats_episode.get('std', 0):.6f}, "
              f"min={actor_stats_episode.get('min', 0):.6f}, max={actor_stats_episode.get('max', 0):.6f}")
        print(f"  Critic参数统计: mean={critic_stats_episode.get('mean', 0):.6f}, std={critic_stats_episode.get('std', 0):.6f}, "
              f"min={critic_stats_episode.get('min', 0):.6f}, max={critic_stats_episode.get('max', 0):.6f}")
        if episode > 0:
            avg_reward = np.mean(rewards[-10:]) if len(rewards) >= 10 else np.mean(rewards)
            print(f"  最近10个episode平均奖励: {avg_reward:.4f}")
        print(f"{'='*80}\n")
        
        # 定期保存模型
        if model_save_dir and save_frequency > 0 and (episode + 1) % save_frequency == 0:
            model_path = os.path.join(model_save_dir, f"ddpg_model_episode_{episode + 1}.pth")
            agent.save(model_path)
            print("执行一次模型保存")

    # 训练结束后保存最终模型
    if model_save_dir:
        final_model_path = os.path.join(model_save_dir, "ddpg_model_final.pth")
        agent.save(final_model_path)

    # 绘制学习曲线
    plt.plot(rewards)
    plt.title("Learning Curve")
    plt.xlabel("Episodes")
    plt.ylabel("Cumulative Reward")
    plt.show()

    env.close()  # 关闭环境
 
 
# 主函数运行
if __name__ == "__main__":
    # 定义训练轮数和环境参数
    episodes = 500
    # 每个episode的最大步数，可根据可用数据量灵活设置
    max_steps = 500
    # 模型保存目录
    model_save_dir = "./models"
    # 如果要加载已有模型，设置模型路径（例如: "./models/ddpg_model_final.pth"）
    load_model_path = "./models/ddpg_model_final.pth"  # 设置为None表示从头开始训练，或提供模型路径继续训练
    # 每隔多少个episode保存一次模型（设置为0表示只在训练结束时保存）
    save_frequency = 5
    # 训练时的批量大小 flow_num*4
    batch_size = 64
    # 每隔多少步训练一次（1表示每步都训练，2表示每2步训练一次，以此类推）
    train_frequency = 10
    
    # 开始训练
    train_ddpg(episodes=episodes, 
               max_steps=max_steps,
               model_save_dir=model_save_dir,
               load_model_path=load_model_path,
               save_frequency=save_frequency,
               batch_size=batch_size,
               train_frequency=train_frequency)