本文件夹用于存放RDMA AICC的python端实现
- reader_lty.py:以1ms为时间间隔，循环访问共享内存，打印其中记录的RTT信息和cnp标志位
- temp_py.txt:记录执行python程序后的输出信息
- DDPG_base.py:原始版的ddpg算法，参考的csdn开源实现
- NS3Env.py：把ns3建模为environment
- action_plot4flows.png:四条流
    4
    2  1 3 100 5000000 2
    3  1 3 100 5000000 2.0001
    4  1 3 100 5000000 2.0001
    5  1 3 100 5000000 2.0001
- action_plot4flows_tanh.png:使用tanh将action平滑映射到1-100之间，四条流
    4
    2  1 3 100 5000000 2
    3  1 3 100 5000000 2.0001
    4  1 3 100 5000000 2.0001
    5  1 3 100 5000000 2.0001
- action_plot_4flows_retrain.png:重新训练后用四条流做的测试
- action_plot_1flow.png:重新训练后用一条流做的测试，此图90%的reward都是0
- action_plot1222.png:调整到逐个包返回ack、reward从我求导改为做差后的测试结果，在通信过程中有三个流依次到达
- action_plot1222'.png:在原来的基础上又加大了瓶颈
- action_plot1M.png:交换机缓冲区改成1M
- timely_rate_series.png:修改T_LOW和T_HIGH后，timley对两条流的通信做出的速率调控折线图
- action_plot_11.png:调好cnp的kmin和kmax的设置之后，用七条流进行仿真，cc_mode=16，has_win保持1，var_win保持1
- action_plot_10.png:在上述配置之下，has_win保持1，var_win置0
- action_plot_00.png:在上述配置之下，has_win置0，var_win置0
-------------------切换到dcqcn再分别测试一下11、10、00-----
- action_plot_dcqcn_11.png
- action_plot_dcqcn_10.png
- action_plot_dcqcn_00.png
-------------------切换到timely再分别测试一下11、10、00-----
- action_plot_timely_11.png
- action_plot_timely_10.png
- action_plot_timely_00.png