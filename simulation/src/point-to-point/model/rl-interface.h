// lty added
#ifndef RL_INTERFACE_H
#define RL_INTERFACE_H

#include <stdint.h>
#include <array>
#include "ns3/ptr.h"
#include "ns3/object.h"

namespace ns3 {

class RdmaQueuePair;

// 共享内存基本配置
static constexpr uint16_t kRlMaxFlows = 64;
static constexpr uint16_t kRlShmVersion = 2;
static const char kRlShmName[] = "/ns3_rl_shm";

// MI 状态槽
struct __attribute__((packed)) RlSlot { // lty added: packed 避免共享内存对齐偏移
    volatile uint32_t seq;       // 奇数=写入中，偶数=稳定
    uint16_t qp_id;              // NodeId（发送端 ID）
    uint16_t padding;            // 对齐占位
    uint64_t interval_len_ns;    // MI 长度，默认 100000ns
    uint32_t cnp_count;          // 当前 MI 内 CNP=1 数量
    uint32_t tx_pkts;            // 当前 MI 内发送的包数
    uint64_t tx_bytes;           // 当前 MI 内发送的字节数
    uint64_t rtt_mean_ns;        // RTT 均值
    uint64_t tx_rate_bps;        // 当前速率 (bit/s)
    uint64_t timestamp_ns;       // 写入时间戳
    volatile uint32_t result_seq; // lty added: 外部结果的完成序号，达到当前seq后仿真可继续
    int64_t result_value;        // lty added: 外部返回的结果值（如动作/速率），默认0
};

struct RlShmHeader {
    uint16_t version;
    uint16_t slot_count;
    uint32_t slot_size;
};

struct RlShmLayout {
    RlShmHeader header;
    RlSlot slots[kRlMaxFlows];
};

struct RlSample {
    uint16_t qp_id;
    uint16_t padding; // 对齐占位
    uint64_t interval_len_ns;
    uint32_t cnp_count;
    uint32_t tx_pkts;
    uint64_t tx_bytes;
    uint64_t rtt_mean_ns;
    uint64_t tx_rate_bps;
    uint64_t timestamp_ns;
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

    // 写入一条采样数据
    // 返回最终稳定的 seq（偶数），失败返回 0
    uint32_t PublishSample(int slot_index, const RlSample& sample);

    // lty added: 等待指定slot的外部结果写回，阻塞直到 result_seq >= target_seq
    bool WaitForResult(int slot_index, uint32_t target_seq, uint64_t timeout_us = 0);

    // lty added: 读取外部写回的结果值（不阻塞），按 double 解释
    bool GetResultValue(int slot_index, double& out_value);

    // lty added: 处理完一次MI后清空槽位，避免数据滞留
    void ClearSlot(int slot_index);

private:
    void EnsureInit();

    int m_shm_fd;
    RlShmLayout* m_shm_ptr;
    
    // 维护 slot_index -> QP 的映射，方便快速访问
    std::array<Ptr<RdmaQueuePair>, kRlMaxFlows> m_active_qps;
};

} // namespace ns3

#endif
