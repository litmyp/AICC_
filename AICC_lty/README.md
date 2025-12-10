本文件夹用于存放RDMA AICC的python端实现
- reader_lty.py:以1ms为时间间隔，循环访问共享内存，打印其中记录的RTT信息和cnp标志位
- temp_py.txt:记录执行python程序后的输出信息
- DDPG_base.py:原始版的ddpg算法，参考的csdn开源实现
- NS3Env.py：把ns3建模为environment