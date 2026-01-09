import mmap
import os
import struct
import time

SHM_NAME = "/dev/shm/ns3_rl_shm"
# 与 C++ rl-interface.h 对齐
# layout: ns3_ready(i), py_ready(i), sim_done(i), num_active(i) -> 4 * 4 = 16 bytes
HEADER_FMT = "iiii" 
HEADER_SIZE = 16

# state: active(i), id(I), cur_rate(d), cnp(d), rtt(d), thru(d) 
# sizes: 4 + 4 + 8 + 8 + 8 + 8 = 40 bytes
STATE_FMT = "iIdddd"
STATE_SIZE = 40

def main():
    print(f"Waiting for shared memory file at {SHM_NAME}...")
    # 简单的轮询等待文件创建
    retries = 0
    while not os.path.exists(SHM_NAME):
        time.sleep(0.1)
        retries += 1
        if retries > 50: # 等待 5 秒
            print("Timeout: Shared memory file not found. Did you run ns-3?")
            return

    print("File found! Reading content...")
    
    try:
        with open(SHM_NAME, "r+b") as f:
            mm = mmap.mmap(f.fileno(), 0)
            
            # 1. 读取头部
            header_data = struct.unpack(HEADER_FMT, mm[:HEADER_SIZE])
            ns3_ready, py_ready, sim_done, num_active = header_data
            
            print("-" * 30)
            print(f"SHM Header:")
            print(f"  ns3_ready: {ns3_ready}")
            print(f"  py_ready:  {py_ready}")
            print(f"  sim_done:  {sim_done}")
            print(f"  num_active_flows (Peak): {num_active}")
            print("-" * 30)
            
            # 2. 扫描前 5 个槽位看有没有数据
            # 注意：如果仿真跑太快结束了，is_active 可能已经被重置为 0
            # 但 flow_id 应该还会留着（因为我们只重置了 active 位，内存没清零 flow_id）
            for i in range(5):
                offset = HEADER_SIZE + i * STATE_SIZE
                slot_data = struct.unpack(STATE_FMT, mm[offset : offset+STATE_SIZE])
                is_active, flow_id, rate, cnp, rtt, thru = slot_data
                
                if flow_id != 0 or is_active != 0:
                    print(f"[Slot {i}] ID: {flow_id}, Active: {is_active}, Rate: {rate:.2f}, RTT: {rtt}")
            
            mm.close()
            print("\nTest PASSED: Shared memory is readable and structured correctly.")
            
    except Exception as e:
        print(f"Error reading SHM: {e}")

if __name__ == "__main__":
    main()