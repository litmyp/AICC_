// lty added
#ifndef RL_INTERFACE_H
#define RL_INTERFACE_H

#include <stdint.h>
#include <vector>
#include "ns3/ptr.h"
#include "ns3/object.h"
//#include "ns3/rdma-queue-pair.h"

namespace ns3 {

class RdmaQueuePair;

// 定义最大支持的流数量，防止内存溢出
#define MAX_RL_FLOWS 1024
#define SHM_NAME "/ns3_rl_shm"

// === 共享内存数据布局 ===
// 这个结构体必须在 C++ 和 Python 中完全字节对齐
struct ShmLayout {
    // 同步标志位
    volatile int32_t ns3_ready;      // 1: ns-3 数据已就绪，Python 可读
    volatile int32_t py_ready;       // 1: Python 动作已写入，ns-3 可读
    volatile int32_t sim_done;       // 1: 仿真结束
    volatile int32_t num_active_flows; // 当前活跃流的数量

    // 状态数据区 (State) - 发送给 Python
    struct {
        int32_t is_active;           // 1: 该槽位有效, 0: 空闲
        uint32_t flow_id;            // 用于调试
        double cur_rate;             // 当前速率 (bps)
        double cnp_rate;             // CNP 数量 / 包数量 (周期内)
        double avg_rtt;              // 平均 RTT (ns)
        double throughput;           // 吞吐量 (bytes / period)
    } states[MAX_RL_FLOWS];

    // 动作指令区 (Action) - 从 Python 接收
    struct {
        double target_rate;          // 目标速率 (bps)
    } actions[MAX_RL_FLOWS];
};

class RLInterface {
public:
    static RLInterface* Get(); // 单例获取
    
    RLInterface();
    ~RLInterface();

    // 初始化共享内存
    void Init();

    // 注册 QP 到共享内存槽位
    // 返回值：分配到的 slot index，如果满了返回 -1
    int RegisterQp(Ptr<RdmaQueuePair> qp);

    // 注销 QP，释放槽位
    void UnregisterQp(int slot_index);

    // [核心] 这里的逻辑稍后实现，现在先留空
    // 负责把所有注册 QP 的数据写入 Shm，并等待 Python
    void Step();

private:
    int m_shm_fd;
    ShmLayout* m_shm_ptr;
    
    // 维护 slot_index -> QP 的映射，方便快速访问
    Ptr<RdmaQueuePair> m_active_qps[MAX_RL_FLOWS];
};

} // namespace ns3

#endif