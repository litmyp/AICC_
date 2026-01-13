import mmap, struct, time, posix_ipc, os

# lty added: 简单交互脚本，读取共享内存并向 result_seq/result_value 写回

SHM_NAME = "/ns3_rl_shm"
SLOTS_TO_READ = 8  # third_lty 有 8 条 flow
POLL_INTERVAL = 0.1  # 秒
HEADER_FMT = "<HHI"
SLOT_FMT = "<IHHQIIQQQQIq"  # 对应 RlSlot 结构
HEADER_SIZE = struct.calcsize(HEADER_FMT)
SLOT_PREFIX_SIZE = struct.calcsize("<IHHQIIQQQQ")  # lty added: result_seq/value 的偏移


def open_shm():
    while True:
        try:
            shm = posix_ipc.SharedMemory(SHM_NAME)
            m = mmap.mmap(shm.fd, 0)
            shm.close_fd()
            return m
        except FileNotFoundError:
            time.sleep(0.05)


def read_slots(m):
    version, slot_count, slot_size = struct.unpack_from(HEADER_FMT, m, 0)
    print(f"hdr: ver={version}, slots={slot_count}, slot_size={slot_size}")
    slots = []
    for i in range(min(SLOTS_TO_READ, slot_count)):
        off = HEADER_SIZE + i * slot_size
        seq1 = struct.unpack_from("<I", m, off)[0]
        if seq1 % 2:  # 写入中，跳过
            continue
        (seq2, qp_id, _pad, interval_ns, cnp, pkts, bytes_, rtt_ns, rate_bps,
         ts_ns, result_seq, result_value) = struct.unpack_from(SLOT_FMT, m, off)
        if seq1 != seq2 or seq2 == 0:
            continue  # 不稳定或还未写过
        slots.append({
            "slot": i,
            "seq": seq2,
            "qp_id": qp_id,
            "interval_ns": interval_ns,
            "cnp": cnp,
            "pkts": pkts,
            "bytes": bytes_,
            "rtt_ns": rtt_ns,
            "rate_bps": rate_bps,
            "ts_ns": ts_ns,
            "result_seq": result_seq,
            "result_value": result_value,
            "offset": off,
            "slot_size": slot_size,
        })
        print(f"slot {i}: qp_id={qp_id} seq={seq2} mi_ns={interval_ns} "
              f"cnp={cnp} pkts={pkts} bytes={bytes_} rtt_ns={rtt_ns} "
              f"rate_bps={rate_bps} ts_ns={ts_ns} "
              f"result_seq={result_seq} result_value={result_value}")
    return version, slot_count, slot_size, slots


def write_result(m, slot_off, target_seq, result_value):
    # lty added: 写入 result_value 后，再写 result_seq 让仿真继续
    result_seq_off = slot_off + SLOT_PREFIX_SIZE
    result_value_off = result_seq_off + 4
    struct.pack_into("<q", m, result_value_off, result_value)
    struct.pack_into("<I", m, result_seq_off, target_seq)


if __name__ == "__main__":
    m = open_shm()
    try:
        while True:
            os.system("clear")
            version, slot_cnt, slot_size, slots = read_slots(m)
            print("\n输入格式: <slot_id> <result_value>，回车仅刷新，q 退出")
            cmd = input(">>> ").strip()
            if cmd.lower() in ("q", "quit", "exit"):
                break
            if cmd == "":
                time.sleep(POLL_INTERVAL)
                continue
            parts = cmd.split()
            if len(parts) < 1:
                continue
            try:
                slot_id = int(parts[0])
                res_val = float(parts[1]) if len(parts) > 1 else 0.0
            except ValueError:
                print("格式错误，需形如: 0 1.23")
                time.sleep(1)
                continue
            if slot_id < 0 or slot_id >= slot_cnt:
                print(f"非法 slot_id: {slot_id}")
                time.sleep(1)
                continue
            slot_info = next((s for s in slots if s["slot"] == slot_id), None)
            if not slot_info:
                print(f"slot {slot_id} 当前无稳定数据，等待下一次采样")
                time.sleep(1)
                continue
            # 以 double 的 IEEE754 位型写入到 int64 槽位，让 C++ 端按 double 解释
            packed = struct.unpack("<q", struct.pack("<d", res_val))[0]
            write_result(m, slot_info["offset"], slot_info["seq"], packed)
            print(f"已写回: slot={slot_id} target_seq={slot_info['seq']} value={res_val}")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
