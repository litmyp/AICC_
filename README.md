# RDMA-AICC

## Overview
本项目在HPCC的开源代码(./simulation)的基础上，将网络通信建模为环境，并用强化学习算法(./AICC_lty)来设计拥塞控制算法。

## Usage
### 启动仿真
1. cd ./simulation
2. conda activate ns317
3. ./waf --run "scratch/third_lty mix/config_lty.txt" >temp.txt

### 启动RL
0. 保证仿真启动后，再启动RL
1. cd ./AICC_lty
2. python DDPG_lty.py >temp_py.txt
3. 仿真结束后,ctrl+c退出

### 绘图
- python ./AICC_lty/process_temp_rates.py

## 核心设计
### 拥塞控制协议的核心实现
- 在rdma-hw.cc rdma-hw.h实现仿真端的拥塞控制算法、共享内存的创建与读写
- 仿真主程序：third_lty.cc
- 仿真配置文件：config_lty.txt (变量解读参考config_doc.txt)

### 强化学习的核心实现
- reader_lty.py:实现RL端对共享内存的读写
- NS3Env.py:将仿真器建模为强化学习中的环境，包括计算奖励值等
- DDPG_lty.py:模型的定义与DDPG算法的实现、ReplayBuffer的实现、训练推理全流程
- process_temp_rates.py:从temp.txt中读取节点id、时间戳、速率信息，绘图