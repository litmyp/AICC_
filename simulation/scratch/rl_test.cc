#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/applications-module.h"
#include "ns3/ipv4-global-routing-helper.h"
#include "ns3/log.h"
// 必须引入这两个头文件才能手动安装 RDMA 协议栈
#include "ns3/rdma-hw.h" // lty added
#include "ns3/rdma-driver.h" // lty added
#include "ns3/qbb-helper.h" // lty added: 使用 QBB 设备构建 RDMA 链路
#include "ns3/rdma-client-helper.h" // lty added: 简化 RDMA 应用安装
#include "ns3/qbb-net-device.h" // lty added: 获取接口索引以填充 RDMA 路由

using namespace ns3;

NS_LOG_COMPONENT_DEFINE ("RLTest");

int main (int argc, char *argv[])
{
  LogComponentEnable("RLInterface", LOG_LEVEL_ALL); // lty added: 打开 RL 接口日志观察共享内存注册
  LogComponentEnable("RLTest", LOG_LEVEL_ALL);

  NS_LOG_INFO ("Create nodes...");
  NodeContainer nodes;
  nodes.Create (2);

  InternetStackHelper stack;
  stack.Install (nodes);

  NS_LOG_INFO ("Create channels...");
  QbbHelper qbb;
  qbb.SetDeviceAttribute ("DataRate", StringValue ("100Gbps"));
  qbb.SetChannelAttribute ("Delay", StringValue ("1us"));
  NetDeviceContainer devices = qbb.Install (nodes);

  NS_LOG_INFO ("Install RDMA Driver manually...");
  // lty added: 提前初始化 RdmaHw/RdmaDriver，便于 RL 共享内存注册队列对
  for (uint32_t i = 0; i < nodes.GetN(); ++i)
    {
      Ptr<Node> node = nodes.Get (i);
      Ptr<RdmaHw> rdmaHw = CreateObject<RdmaHw>();
      rdmaHw->SetAttribute ("CcMode", UintegerValue (1)); // lty added: 设置 DCQCN，便于 RL 侧采集拥塞信号
      rdmaHw->SetAttribute ("L2AckInterval", UintegerValue (1)); // lty added: 启用 ACK，避免默认 0 时触发 shouldn't receive ack
      Ptr<RdmaDriver> rdma = CreateObject<RdmaDriver>();
      rdma->SetNode (node);
      rdma->SetRdmaHw (rdmaHw);
      node->AggregateObject (rdma);
      rdma->Init (); // lty added: 初始化 RDMA 栈，供强化学习共享内存注册 QP
    }

  NS_LOG_INFO ("Assign IP Addresses...");
  Ipv4AddressHelper address;
  address.SetBase ("10.1.1.0", "255.255.255.0");
  Ipv4InterfaceContainer interfaces = address.Assign (devices);

  Ptr<QbbNetDevice> dev0 = DynamicCast<QbbNetDevice> (devices.Get (0));
  Ptr<QbbNetDevice> dev1 = DynamicCast<QbbNetDevice> (devices.Get (1));
  Ptr<RdmaDriver> drv0 = nodes.Get (0)->GetObject<RdmaDriver> ();
  Ptr<RdmaDriver> drv1 = nodes.Get (1)->GetObject<RdmaDriver> ();
  NS_ASSERT_MSG (dev0 && dev1, "Qbb devices missing"); // lty added: 保护 RDMA 表填充的前置条件
  NS_ASSERT_MSG (drv0 && drv1, "RdmaDriver missing"); // lty added: 确认驱动已聚合
  Ipv4Address host0To1 = interfaces.GetAddress (1); // lty added: 保存地址以满足非常量引用
  Ipv4Address host1To0 = interfaces.GetAddress (0); // lty added: 保存地址以满足非常量引用
  drv0->m_rdma->AddTableEntry (host0To1, dev0->GetIfIndex ()); // lty added: 主机0至主机1的 RDMA 转发表
  drv1->m_rdma->AddTableEntry (host1To0, dev1->GetIfIndex ()); // lty added: 主机1至主机0的 RDMA 转发表

  NS_LOG_INFO ("Setup RdmaClientHelper...");
  uint16_t pg = 0;
  Ipv4Address srcIp = interfaces.GetAddress (0);
  Ipv4Address dstIp = interfaces.GetAddress (1);
  uint16_t sPort = 1000;
  uint16_t dPort = 1000;
  uint64_t flowSize = 1000000;
  uint32_t win = 1000;
  uint64_t baseRtt = 2000; // lty added: 1us 单向 + 1us 返回
  RdmaClientHelper client (pg, srcIp, dstIp, sPort, dPort, flowSize, win, baseRtt);
  ApplicationContainer app = client.Install (nodes.Get (0));
  app.Start (Seconds (0.1));
  app.Stop (Seconds (1.0));

  NS_LOG_INFO ("Starting Simulation...");
  Simulator::Run ();
  Simulator::Destroy ();
  NS_LOG_INFO ("Simulation Finished.");

  return 0;
}
