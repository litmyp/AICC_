// lty added
#include "rl-interface.h"
#include "rdma-queue-pair.h"
#include "ns3/log.h"
#include <sys/mman.h>
#include <sys/stat.h>        /* For mode constants */
#include <fcntl.h>           /* For O_* constants */
#include <unistd.h>
#include <errno.h>
#include <string.h>
#include <iostream>

namespace ns3 {

NS_LOG_COMPONENT_DEFINE("RLInterface");

static RLInterface* g_instance = nullptr;

RLInterface* RLInterface::Get() {
    if (g_instance == nullptr) {
        g_instance = new RLInterface();
    }
    return g_instance;
}

RLInterface::RLInterface() : m_shm_fd(-1), m_shm_ptr(nullptr) {
    for(int i=0; i<MAX_RL_FLOWS; ++i) {
        m_active_qps[i] = nullptr;
    }
}

RLInterface::~RLInterface() {
    if (m_shm_ptr != nullptr && m_shm_ptr != MAP_FAILED) {
        munmap(m_shm_ptr, sizeof(ShmLayout));
    }
    if (m_shm_fd != -1) {
        close(m_shm_fd);
        shm_unlink(SHM_NAME); // 删除共享内存文件
    }
}

void RLInterface::Init() {
    // 1. 创建共享内存对象
    m_shm_fd = shm_open(SHM_NAME, O_CREAT | O_RDWR, 0666);
    if (m_shm_fd == -1) {
        NS_FATAL_ERROR("Failed to shm_open: " << strerror(errno));
    }

    // 2. 设置文件大小
    if (ftruncate(m_shm_fd, sizeof(ShmLayout)) == -1) {
        NS_FATAL_ERROR("Failed to ftruncate shm: " << strerror(errno));
    }

    // 3. 映射到内存
    m_shm_ptr = (ShmLayout*)mmap(0, sizeof(ShmLayout), PROT_READ | PROT_WRITE, MAP_SHARED, m_shm_fd, 0);
    if (m_shm_ptr == MAP_FAILED) {
        NS_FATAL_ERROR("Failed to mmap shm: " << strerror(errno));
    }

    // 4. 初始化内存区域
    memset(m_shm_ptr, 0, sizeof(ShmLayout));
    
    NS_LOG_INFO("RLInterface Initialized. Shm Size: " << sizeof(ShmLayout));
    std::cout << "RLInterface: Shared Memory created at " << SHM_NAME << std::endl;
}

int RLInterface::RegisterQp(Ptr<RdmaQueuePair> qp) {
    if (!m_shm_ptr) Init();

    // 寻找空闲槽位
    for (int i = 0; i < MAX_RL_FLOWS; ++i) {
        if (m_active_qps[i] == nullptr) {
            m_active_qps[i] = qp;
            
            // 初始化共享内存中的状态
            m_shm_ptr->states[i].is_active = 1;
            m_shm_ptr->states[i].flow_id = qp->GetHash(); // 假设用Hash做ID
            m_shm_ptr->num_active_flows++;
            
            NS_LOG_INFO("Registered QP Hash: " << qp->GetHash() << " at Slot: " << i);
            return i;
        }
    }
    NS_LOG_WARN("RLInterface: No free slots available for new QP!");
    return -1;
}

void RLInterface::UnregisterQp(int slot_index) {
    if (slot_index < 0 || slot_index >= MAX_RL_FLOWS) return;
    
    if (m_active_qps[slot_index] != nullptr) {
        m_active_qps[slot_index] = nullptr;
        m_shm_ptr->states[slot_index].is_active = 0;
        m_shm_ptr->num_active_flows--;
        NS_LOG_INFO("Unregistered QP at Slot: " << slot_index);
    }
}

void RLInterface::Step() {
    // 暂时留空，下一步实现
}

} // namespace ns3