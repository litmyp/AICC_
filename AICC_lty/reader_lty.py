#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lty 把ns3写进共享内存中的数据都出来
"""

import mmap
import struct
import time
import sys
import ctypes
from ctypes import c_uint64, c_uint32, c_uint16, c_uint8, c_char
import os

# 共享内存名称（与rdma-hw中保持一致）
SHM_NAME = "/rtt_shm_lty"

# RTT数据结构定义
class RttShmData(ctypes.Structure):
    _pack_ = 1  # 按1字节对齐，避免对齐问题
    _fields_ = [
        ("sequence", c_uint64),       
        ("node_id", c_uint32),        
        ("sip", c_uint32),            
        ("sport", c_uint16),          
        ("_pad1", c_uint16),          
        ("dip", c_uint32),            
        ("dport", c_uint16),          
        ("_pad2", c_uint16),          
        ("ack_seq", c_uint32),        
        ("rtt_ns", c_uint64),         
        ("timestamp_ns", c_uint64),   
        ("cnp",c_uint8),
        ("_pad3", c_uint8 * 3),
        ("qp_rate", ctypes.c_float),   # 当前QP速率（Gbps）
        ("reserved", c_char * 48),
        ("new_rate", ctypes.c_float),  # lty added: 目标速率（Gbps），-1 表示未更新
        ("padding2", c_char * 4),
    ]


def get_version_tuple(data: "RttShmData"):
    """
    返回共享内存中一条记录的版本标识，用于判断数据是否更新。
    组合 sequence / node_id / timestamp_ns 可以区分不同节点在不同时刻写入的数据。
    """
    return (
        int(data.sequence),
        int(data.node_id),
        int(data.timestamp_ns),
    )

def ip_to_string(ip):
    # 将32位整数IP地址转换为字符串格式
    return f"{ip & 0xFF}.{(ip >> 8) & 0xFF}.{(ip >> 16) & 0xFF}.{(ip >> 24) & 0xFF}"

def read_rtt_from_shm(shm_mmap=None, check_file_exists=True):

    try:
        #存在，直接使用
        if shm_mmap is not None:
            data = RttShmData.from_buffer_copy(shm_mmap)
            return data, shm_mmap
        
        #不存在，需要先创建再使用
        shm_path = f"/dev/shm{SHM_NAME}"
        
        if check_file_exists and not os.path.exists(shm_path):
            # 共享内存不存在，返回None但不打印错误（由调用者决定是否等待）
            return None, None
        
        #打开共享内存文件
        shm_fd = open(shm_path, "r+b")
        #映射
        shm_size = ctypes.sizeof(RttShmData)
        shm_mmap = mmap.mmap(shm_fd.fileno(), shm_size, access=mmap.ACCESS_READ)
        shm_fd.close()  # mmap后可以关闭文件描述符
        
        #读数据
        data = RttShmData.from_buffer_copy(shm_mmap)
        
        return data, shm_mmap
        
    except Exception as e:
        print(f"读取共享内存时出错: {e}")
        return None, None

def monitor_rtt(interval=0.01, max_iterations=None):

    last_version = None
    shm_mmap = None
    
    print(f"开始监控RTT(共享内存: {SHM_NAME})")
    
    # 等待共享内存被创建
    print("等待共享内存创建...")
    while shm_mmap is None:
        data, shm_mmap = read_rtt_from_shm()
        if shm_mmap is None:
            time.sleep(0.001)  # 等待1ms后重试
    
    # 共享内存已创建，开始监控
    print("共享内存已连接，监控开启...\n")
    
    iteration = 0
    try:
        
        while True:
            if max_iterations is not None and iteration >= max_iterations:
                break
            
            #读取数据
            data, shm_mmap = read_rtt_from_shm(shm_mmap, check_file_exists=False)
            
            # 如果读取失败（共享内存可能被删除），重新等待
            if data is None:
                print("共享内存已断开，等待重新连接...")
                shm_mmap = None
                # 等待共享内存重新创建
                while shm_mmap is None:
                    data, shm_mmap = read_rtt_from_shm()
                    if shm_mmap is None:
                        time.sleep(0.01)  # 等待10ms后重试
                print("共享内存已重新连接，继续监控...\n")
                last_version = None  # 重置版本信息，以便重新开始监控
                continue
            
            # 检查是否有新数据（通过版本号判断）
            current_version = get_version_tuple(data)
            if current_version != last_version:
                # 有新数据，打印信息
                sip_str = ip_to_string(data.sip)
                dip_str = ip_to_string(data.dip)
                rtt_ms = data.rtt_ns / 1000000.0
                timestamp_ms = data.timestamp_ns / 1000000.0
                
                print(f"[序列号: {data.sequence}] "
                      f"节点ID: {data.node_id} | "
                      f"QP: [{sip_str}:{data.sport} -> {dip_str}:{data.dport}] | "
                      f"ACK序列: {data.ack_seq} | "
                      f"RTT: {data.rtt_ns} ns ({rtt_ms:.3f} ms) | "
                      f"CNP: {data.cnp} | "
                      f"时间戳: {timestamp_ms:.3f} ms | "
                      f"QP速率: {data.qp_rate:.3f} Gbps | "
                      f"new_rate: {data.new_rate:.3f} Gbps")  # lty added: 打印目标速率
                
                last_version = current_version
                iteration += 1
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n监控已停止")
    finally:
        # 清理资源
        if shm_mmap is not None:
            shm_mmap.close()

# def read_once():
#     """读取一次RTT数据并打印"""
#     data, shm_mmap = read_rtt_from_shm()
    
#     if data is None:
#         return
    
#     # 清理资源
#     if shm_mmap is not None:
#         shm_mmap.close()
    
#     sip_str = ip_to_string(data.sip)
#     dip_str = ip_to_string(data.dip)
#     rtt_ms = data.rtt_ns / 1000000.0
#     timestamp_ms = data.timestamp_ns / 1000000.0
    
#     print(f"=== RTT数据 ===")
#     print(f"序列号: {data.sequence}")
#     print(f"节点ID: {data.node_id}")
#     print(f"源地址: {sip_str}:{data.sport}")
#     print(f"目标地址: {dip_str}:{data.dport}")
#     print(f"ACK序列号: {data.ack_seq}")
#     print(f"RTT: {data.rtt_ns} ns ({rtt_ms:.3f} ms)")
#     print(f"时间戳: {data.timestamp_ns} ns ({timestamp_ms:.3f} ms)")
#     print("===============")

if __name__ == "__main__":
    interval = 0.001  # 默认1ms检查间隔
    monitor_rtt(interval=interval)
