#include <ns3/simulator.h>
#include <ns3/seq-ts-header.h>
#include <ns3/udp-header.h>
#include <ns3/ipv4-header.h>
#include "ns3/ppp-header.h"
#include "ns3/boolean.h"
#include "ns3/uinteger.h"
#include "ns3/double.h"
#include "ns3/data-rate.h"
#include "ns3/pointer.h"
#include "rdma-hw.h"
#include "ppp-header.h"
#include "qbb-header.h"
#include "cn-header.h"

#include <iostream>
#include <algorithm>

#include <ns3/log.h>//lty added

// lty added,为了实现共享内存引入如下头文件
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstring>
#include <thread>
#include <chrono>
#include <unordered_set>
// 定义当前模块的日志组件名称，便于使用 NS_LOG 输出调试信息
NS_LOG_COMPONENT_DEFINE("RdmaHw");


namespace ns3{

namespace {
	// Tracks QPs that already emitted a minimum-rate warning to avoid repetitive logs.
	std::unordered_set<uint32_t> g_minRateWarningIssued;
	const bool kEnableRetransLogging = false;
}

TypeId RdmaHw::GetTypeId (void)
{
	static TypeId tid = TypeId ("ns3::RdmaHw")
		.SetParent<Object> ()
		.AddAttribute("MinRate",
				"Minimum rate of a throttled flow",
				DataRateValue(DataRate("100Mb/s")),
				MakeDataRateAccessor(&RdmaHw::m_minRate),
				MakeDataRateChecker())
		.AddAttribute("Mtu",
				"Mtu.",
				UintegerValue(1000),
				MakeUintegerAccessor(&RdmaHw::m_mtu),
				MakeUintegerChecker<uint32_t>())
		.AddAttribute ("CcMode",
				"which mode of DCQCN is running",
				UintegerValue(0),
				MakeUintegerAccessor(&RdmaHw::m_cc_mode),
				MakeUintegerChecker<uint32_t>())
		.AddAttribute("NACK Generation Interval",
				"The NACK Generation interval",
				DoubleValue(500.0),
				MakeDoubleAccessor(&RdmaHw::m_nack_interval),
				MakeDoubleChecker<double>())
		.AddAttribute("L2ChunkSize",
				"Layer 2 chunk size. Disable chunk mode if equals to 0.",
				UintegerValue(0),
				MakeUintegerAccessor(&RdmaHw::m_chunk),
				MakeUintegerChecker<uint32_t>())
		.AddAttribute("L2AckInterval",
				"Layer 2 Ack intervals. Disable ack if equals to 0.",
				UintegerValue(0),
				MakeUintegerAccessor(&RdmaHw::m_ack_interval),
				MakeUintegerChecker<uint32_t>())
		.AddAttribute("L2BackToZero",
				"Layer 2 go back to zero transmission.",
				BooleanValue(false),
				MakeBooleanAccessor(&RdmaHw::m_backto0),
				MakeBooleanChecker())
		.AddAttribute("EwmaGain",
				"Control gain parameter which determines the level of rate decrease",
				DoubleValue(1.0 / 16),
				MakeDoubleAccessor(&RdmaHw::m_g),
				MakeDoubleChecker<double>())
		.AddAttribute ("RateOnFirstCnp",
				"the fraction of rate on first CNP",
				DoubleValue(1.0),
				MakeDoubleAccessor(&RdmaHw::m_rateOnFirstCNP),
				MakeDoubleChecker<double> ())
		.AddAttribute("ClampTargetRate",
				"Clamp target rate.",
				BooleanValue(false),
				MakeBooleanAccessor(&RdmaHw::m_EcnClampTgtRate),
				MakeBooleanChecker())
		.AddAttribute("RPTimer",
				"The rate increase timer at RP in microseconds",
				DoubleValue(1500.0),
				MakeDoubleAccessor(&RdmaHw::m_rpgTimeReset),
				MakeDoubleChecker<double>())
		.AddAttribute("RateDecreaseInterval",
				"The interval of rate decrease check",
				DoubleValue(4.0),
				MakeDoubleAccessor(&RdmaHw::m_rateDecreaseInterval),
				MakeDoubleChecker<double>())
		.AddAttribute("FastRecoveryTimes",
				"The rate increase timer at RP",
				UintegerValue(5),
				MakeUintegerAccessor(&RdmaHw::m_rpgThreshold),
				MakeUintegerChecker<uint32_t>())
		.AddAttribute("AlphaResumInterval",
				"The interval of resuming alpha",
				DoubleValue(55.0),
				MakeDoubleAccessor(&RdmaHw::m_alpha_resume_interval),
				MakeDoubleChecker<double>())
		.AddAttribute("RateAI",
				"Rate increment unit in AI period",
				DataRateValue(DataRate("5Mb/s")),
				MakeDataRateAccessor(&RdmaHw::m_rai),
				MakeDataRateChecker())
		.AddAttribute("RateHAI",
				"Rate increment unit in hyperactive AI period",
				DataRateValue(DataRate("50Mb/s")),
				MakeDataRateAccessor(&RdmaHw::m_rhai),
				MakeDataRateChecker())
		.AddAttribute("VarWin",
				"Use variable window size or not",
				BooleanValue(false),
				MakeBooleanAccessor(&RdmaHw::m_var_win),
				MakeBooleanChecker())
		.AddAttribute("FastReact",
				"Fast React to congestion feedback",
				BooleanValue(true),
				MakeBooleanAccessor(&RdmaHw::m_fast_react),
				MakeBooleanChecker())
		.AddAttribute("MiThresh",
				"Threshold of number of consecutive AI before MI",
				UintegerValue(5),
				MakeUintegerAccessor(&RdmaHw::m_miThresh),
				MakeUintegerChecker<uint32_t>())
		.AddAttribute("TargetUtil",
				"The Target Utilization of the bottleneck bandwidth, by default 95%",
				DoubleValue(0.95),
				MakeDoubleAccessor(&RdmaHw::m_targetUtil),
				MakeDoubleChecker<double>())
		.AddAttribute("UtilHigh",
				"The upper bound of Target Utilization of the bottleneck bandwidth, by default 98%",
				DoubleValue(0.98),
				MakeDoubleAccessor(&RdmaHw::m_utilHigh),
				MakeDoubleChecker<double>())
		.AddAttribute("RateBound",
				"Bound packet sending by rate, for test only",
				BooleanValue(true),
				MakeBooleanAccessor(&RdmaHw::m_rateBound),
				MakeBooleanChecker())
		.AddAttribute("MultiRate",
				"Maintain multiple rates in HPCC",
				BooleanValue(true),
				MakeBooleanAccessor(&RdmaHw::m_multipleRate),
				MakeBooleanChecker())
		.AddAttribute("SampleFeedback",
				"Whether sample feedback or not",
				BooleanValue(false),
				MakeBooleanAccessor(&RdmaHw::m_sampleFeedback),
				MakeBooleanChecker())
		.AddAttribute("TimelyAlpha",
				"Alpha of TIMELY",
				DoubleValue(0.875),
				MakeDoubleAccessor(&RdmaHw::m_tmly_alpha),
				MakeDoubleChecker<double>())
		.AddAttribute("TimelyBeta",
				"Beta of TIMELY",
				DoubleValue(0.8),
				MakeDoubleAccessor(&RdmaHw::m_tmly_beta),
				MakeDoubleChecker<double>())
		.AddAttribute("TimelyTLow",
				"TLow of TIMELY (ns)",
				UintegerValue(50000),
				MakeUintegerAccessor(&RdmaHw::m_tmly_TLow),
				MakeUintegerChecker<uint64_t>())
		.AddAttribute("TimelyTHigh",
				"THigh of TIMELY (ns)",
				UintegerValue(500000),
				MakeUintegerAccessor(&RdmaHw::m_tmly_THigh),
				MakeUintegerChecker<uint64_t>())
		.AddAttribute("TimelyMinRtt",
				"MinRtt of TIMELY (ns)",
				UintegerValue(20000),
				MakeUintegerAccessor(&RdmaHw::m_tmly_minRtt),
				MakeUintegerChecker<uint64_t>())
		.AddAttribute("DctcpRateAI",
				"DCTCP's Rate increment unit in AI period",
				DataRateValue(DataRate("1000Mb/s")),
				MakeDataRateAccessor(&RdmaHw::m_dctcp_rai),
				MakeDataRateChecker())
		.AddAttribute("PintSmplThresh",
				"PINT's sampling threshold in rand()%65536",
				UintegerValue(65536),
				MakeUintegerAccessor(&RdmaHw::pint_smpl_thresh),
				MakeUintegerChecker<uint32_t>())
		;
	return tid;
}

// 构造函数，初始化速率追踪相关开关并设置缺省 ACK 刷新延迟
RdmaHw::RdmaHw()
	: m_flowRateTracePath("")          // 默认不写入速率追踪文件
	, m_flowRateTraceEnabled(false)    // 关闭速率追踪功能
{
	m_ackFlushTimeout = MicroSeconds(1); // 缺省将 ACK 聚合刷新定时器设为 1 微秒
}

// 确保硬件对象销毁时关闭速率跟踪文件流。
RdmaHw::~RdmaHw(){
	if (m_flowRateStream.is_open()){
		m_flowRateStream.close();
	}
}
/**
 * SetNode 的作用是把 RdmaHw 实例与给定的 Node 对象关联起来，
 * 然后立即调用 EnsureFlowRateTraceReady() 预先准备速率跟踪文件，
 * 避免第一次需要写入追踪数据时才去创建文件导致的延迟。
 */
void RdmaHw::SetNode(Ptr<Node> node){
	m_node = node;
	// 节点绑定后即可准备速率跟踪文件，避免第一次调用时延迟打开
	EnsureFlowRateTraceReady();
}

void RdmaHw::Setup(QpCompleteCallback cb){
	for (uint32_t i = 0; i < m_nic.size(); i++){
		Ptr<QbbNetDevice> dev = m_nic[i].dev;
		if (dev == NULL)
			continue;
		// share data with NIC
		dev->m_rdmaEQ->m_qpGrp = m_nic[i].qpGrp;// lty 管理所有qp，可以借此获取每个qp当前排队长度等信息
		// setup callback
		dev->m_rdmaReceiveCb = MakeCallback(&RdmaHw::Receive, this);
		dev->m_rdmaLinkDownCb = MakeCallback(&RdmaHw::SetLinkDown, this);
		dev->m_rdmaPktSent = MakeCallback(&RdmaHw::PktSent, this);
		// config NIC
		dev->m_rdmaEQ->m_rdmaGetNxtPkt = MakeCallback(&RdmaHw::GetNxtPacket, this);
	}
	// setup qp complete callback
	m_qpCompleteCallback = cb;
}

// 负责配置速率追踪CSV文件.
void RdmaHw::SetFlowRateTraceFile(const std::string &filePath){
	// 设置速率追踪文件路径
	m_flowRateTracePath = filePath;
	// 路径非空时启用速率追踪
	m_flowRateTraceEnabled = !filePath.empty();
	// 若禁用速率追踪且文件已打开则关闭文件流
	if (!m_flowRateTraceEnabled && m_flowRateStream.is_open()){
		m_flowRateStream.close();
	}
}

// 按需要打开文件并写入表头.
void RdmaHw::EnsureFlowRateTraceReady(){
	// 若未启用速率追踪，则无需准备文件
	if (!m_flowRateTraceEnabled)
		return;
	// 路径为空则无法写入文件，发出警告并禁用追踪功能
	if (m_flowRateTracePath.empty()){
		NS_LOG_WARN("RdmaHw: flow rate trace enabled but no file path provided");
		m_flowRateTraceEnabled = false;
		return;
	}
	// 文件已打开则无需重复准备
	if (m_flowRateStream.is_open())
		return;
	// 检查文件是否存在且非空，以决定是否需要写入表头
	bool needHeader = false;
	std::ifstream preview(m_flowRateTracePath.c_str(), std::ios::in);
	if (!preview.good() || preview.peek() == std::ifstream::traits_type::eof()){
		needHeader = true;
	}
	preview.close();	// 关闭预览流
	// 打开文件流以追加方式写入
	m_flowRateStream.open(m_flowRateTracePath.c_str(), std::ios::out | std::ios::app);
	// 检查文件是否成功打开
	if (!m_flowRateStream.is_open()){
		NS_LOG_WARN("RdmaHw: failed to open flow rate trace file " << m_flowRateTracePath);
		m_flowRateTraceEnabled = false;
		return;
	}
	// 如有必要，写入CSV表头
	if (needHeader){
		m_flowRateStream << "time_ns,node_id,src_ip,src_port,dst_ip,dst_port,priority,rate_bps,cc_tag\n";
		m_flowRateStream.flush();
	}
}

// 写入带时间戳的速率样本.
void RdmaHw::TraceFlowRate(Ptr<RdmaQueuePair> qp, const std::string &tag){
	//若未启用速率追踪则直接返回
	if (!m_flowRateTraceEnabled)
		return;
	EnsureFlowRateTraceReady();	// 确保文件已准备好
	// 文件流未打开则无法写入，直接返回
	if (!m_flowRateStream.is_open())
		return;
	// 写入一行速率数据
	m_flowRateStream << Simulator::Now().GetTimeStep() << ','
					<< m_node->GetId() << ','
					<< qp->sip << ','
					<< qp->sport << ','
					<< qp->dip << ','
					<< qp->dport << ','
					<< qp->m_pg << ','
					<< qp->m_rate.GetBitRate() << ','
					<< tag << '\n';
	m_flowRateStream.flush();	// 立即刷新以确保数据写入文件
}

uint32_t RdmaHw::GetNicIdxOfQp(Ptr<RdmaQueuePair> qp){
	auto &v = m_rtTable[qp->dip.Get()];
	if (v.size() > 0){
		return v[qp->GetHash() % v.size()];
	}else{
		NS_ASSERT_MSG(false, "We assume at least one NIC is alive");
	}
}
uint64_t RdmaHw::GetQpKey(uint32_t dip, uint16_t sport, uint16_t pg){
	return ((uint64_t)dip << 32) | ((uint64_t)sport << 16) | (uint64_t)pg;
}
Ptr<RdmaQueuePair> RdmaHw::GetQp(uint32_t dip, uint16_t sport, uint16_t pg){
	uint64_t key = GetQpKey(dip, sport, pg);
	auto it = m_qpMap.find(key);
	if (it != m_qpMap.end())
		return it->second;
	return NULL;
}
void RdmaHw::AddQueuePair(uint64_t size, uint16_t pg, Ipv4Address sip, Ipv4Address dip, uint16_t sport, uint16_t dport, uint32_t win, uint64_t baseRtt, Callback<void> notifyAppFinish){
	// create qp
	Ptr<RdmaQueuePair> qp = CreateObject<RdmaQueuePair>(pg, sip, dip, sport, dport);
	qp->SetSize(size);
	qp->SetWin(win);
	qp->SetBaseRtt(baseRtt);
	qp->SetVarWin(m_var_win);
	qp->SetAppNotifyCallback(notifyAppFinish);

	// add qp
	uint32_t nic_idx = GetNicIdxOfQp(qp);
	m_nic[nic_idx].qpGrp->AddQp(qp);
	uint64_t key = GetQpKey(dip.Get(), sport, pg);
	m_qpMap[key] = qp;

	// set init variables
	DataRate m_bps = m_nic[nic_idx].dev->GetDataRate();
	qp->m_rate = m_bps;
	qp->m_max_rate = m_bps;
	if (m_cc_mode == 1){
		qp->mlx.m_targetRate = m_bps;
	}else if (m_cc_mode == 3){
		qp->hp.m_curRate = m_bps;
		if (m_multipleRate){
			for (uint32_t i = 0; i < IntHeader::maxHop; i++)
				qp->hp.hopState[i].Rc = m_bps;
		}
	}else if (m_cc_mode == 7){
		qp->tmly.m_curRate = m_bps;
	}else if (m_cc_mode == 10){
		qp->hpccPint.m_curRate = m_bps;
	}

	// Notify Nic
	m_nic[nic_idx].dev->NewQp(qp);
}

void RdmaHw::DeleteQueuePair(Ptr<RdmaQueuePair> qp){
	// remove qp from the m_qpMap
	uint64_t key = GetQpKey(qp->dip.Get(), qp->sport, qp->m_pg);
	m_qpMap.erase(key);
}

Ptr<RdmaRxQueuePair> RdmaHw::GetRxQp(uint32_t sip, uint32_t dip, uint16_t sport, uint16_t dport, uint16_t pg, bool create){
	uint64_t key = ((uint64_t)dip << 32) | ((uint64_t)pg << 16) | (uint64_t)dport;
	auto it = m_rxQpMap.find(key);
	if (it != m_rxQpMap.end())
		return it->second;
	if (create){
		// create new rx qp
		Ptr<RdmaRxQueuePair> q = CreateObject<RdmaRxQueuePair>();
		// init the qp
		q->sip = sip;
		q->dip = dip;
		q->sport = sport;
		q->dport = dport;
		q->m_ecn_source.qIndex = pg;
		q->m_lastAckedSeq = 0;
		q->m_pendingEcnBits = 0;
		q->m_hasLastIntHeader = false;
		// store in map
		m_rxQpMap[key] = q;
		return q;
	}
	return NULL;
}
uint32_t RdmaHw::GetNicIdxOfRxQp(Ptr<RdmaRxQueuePair> q){
	auto &v = m_rtTable[q->dip];
	if (v.size() > 0){
		return v[q->GetHash() % v.size()];
	}else{
		NS_ASSERT_MSG(false, "We assume at least one NIC is alive");
	}
}
void RdmaHw::DeleteRxQp(uint32_t dip, uint16_t pg, uint16_t dport){
	uint64_t key = ((uint64_t)dip << 32) | ((uint64_t)pg << 16) | (uint64_t)dport;
	auto it = m_rxQpMap.find(key);
	if (it != m_rxQpMap.end()){
		Ptr<RdmaRxQueuePair> q = it->second;
		if (q->m_ackFlushEvent.IsRunning()){
			Simulator::Cancel(q->m_ackFlushEvent);
			q->m_ackFlushEvent = EventId();
		}
		m_rxQpMap.erase(it);
	}
}

int RdmaHw::ReceiveUdp(Ptr<Packet> p, CustomHeader &ch){
	uint8_t ecnbits = ch.GetIpv4EcnBits();

	uint32_t payload_size = p->GetSize() - ch.GetSerializedSize();

	// TODO find corresponding rx queue pair
	Ptr<RdmaRxQueuePair> rxQp = GetRxQp(ch.dip, ch.sip, ch.udp.dport, ch.udp.sport, ch.udp.pg, true);
	if (ecnbits != 0){
		rxQp->m_ecn_source.ecnbits |= ecnbits;
		rxQp->m_ecn_source.qfb++;
	}
	rxQp->m_ecn_source.total++;
	rxQp->m_pendingEcnBits |= ecnbits;
	rxQp->m_lastIntHeader = ch.udp.ih;
	rxQp->m_hasLastIntHeader = true;

	int x = ReceiverCheckSeq(ch.udp.seq, rxQp, payload_size);
	switch (x){
	case 1:
		SendReceiverFeedback(rxQp, rxQp->ReceiverNextExpectedSeq, true, rxQp->m_pendingEcnBits != 0, ch.udp.ih);
		break;
	case 2:
		SendReceiverFeedback(rxQp, rxQp->ReceiverNextExpectedSeq, false, rxQp->m_pendingEcnBits != 0, ch.udp.ih);
		break;
	case 5:
		ScheduleAckFlush(rxQp);
		break;
	default:
		break;
	}
	return 0;
}

void RdmaHw::ScheduleAckFlush(Ptr<RdmaRxQueuePair> q){
	if (m_ack_interval == 0){
		return;
	}
	if (q->ReceiverNextExpectedSeq == q->m_lastAckedSeq){
		return;
	}
	if (q->m_ackFlushEvent.IsRunning()){
		Simulator::Cancel(q->m_ackFlushEvent);
	}
	q->m_ackFlushEvent = Simulator::Schedule(m_ackFlushTimeout, &RdmaHw::HandleAckFlushTimeout, this, q);
}

void RdmaHw::HandleAckFlushTimeout(Ptr<RdmaRxQueuePair> q){
	// Timeout ensures the final bytes are acknowledged even when the interval threshold is not met.
	q->m_ackFlushEvent = EventId();
	if (q->ReceiverNextExpectedSeq == q->m_lastAckedSeq){
		return;
	}
	IntHeader ih = q->m_hasLastIntHeader ? q->m_lastIntHeader : IntHeader();
	SendReceiverFeedback(q, q->ReceiverNextExpectedSeq, true, q->m_pendingEcnBits != 0, ih);
}

void RdmaHw::SendReceiverFeedback(Ptr<RdmaRxQueuePair> q, uint32_t seq, bool isAck, bool setCnp, const IntHeader &ih){
	// Helper emits ACK/NACK packets while resetting receiver bookkeeping for the next aggregation window.
	if (q->m_ackFlushEvent.IsRunning()){
		Simulator::Cancel(q->m_ackFlushEvent);
	}
	q->m_ackFlushEvent = EventId();

	qbbHeader seqh;
	seqh.SetSeq(seq);
	seqh.SetPG(q->m_ecn_source.qIndex);
	seqh.SetSport(q->sport);
	seqh.SetDport(q->dport);
	seqh.SetIntHeader(ih);
	if (setCnp){
		seqh.SetCnp();
	}

	Ptr<Packet> newp = Create<Packet>(std::max(60-14-20-(int)seqh.GetSerializedSize(), 0));
	newp->AddHeader(seqh);

	Ipv4Header head;
	head.SetDestination(Ipv4Address(q->dip));
	head.SetSource(Ipv4Address(q->sip));
	head.SetProtocol(isAck ? 0xFC : 0xFD);
	head.SetTtl(64);
	head.SetPayloadSize(newp->GetSize());
	head.SetIdentification(q->m_ipid++);

	newp->AddHeader(head);
	AddHeader(newp, 0x800);
	uint32_t nic_idx = GetNicIdxOfRxQp(q);
	m_nic[nic_idx].dev->RdmaEnqueueHighPrioQ(newp);
	m_nic[nic_idx].dev->TriggerTransmit();

	if (isAck){
		q->m_lastAckedSeq = seq;
	}
	q->m_pendingEcnBits = 0;
	q->m_hasLastIntHeader = false;
}

int RdmaHw::ReceiveCnp(Ptr<Packet> p, CustomHeader &ch){
	// QCN on NIC
	// This is a Congestion signal
	// Then, extract data from the congestion packet.
	// We assume, without verify, the packet is destinated to me
	uint32_t qIndex = ch.cnp.qIndex;
	if (qIndex == 1){		//DCTCP
		std::cout << "TCP--ignore\n";
		return 0;
	}
	uint16_t udpport = ch.cnp.fid; // corresponds to the sport
	uint8_t ecnbits = ch.cnp.ecnBits;
	uint16_t qfb = ch.cnp.qfb;
	uint16_t total = ch.cnp.total;

	uint32_t i;
	// get qp
	Ptr<RdmaQueuePair> qp = GetQp(ch.sip, udpport, qIndex);
	if (qp == NULL)
		std::cout << "ERROR: QCN NIC cannot find the flow\n";
	// get nic
	uint32_t nic_idx = GetNicIdxOfQp(qp);
	Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;

	if (qp->m_rate == 0)			//lazy initialization	
	{
		qp->m_rate = dev->GetDataRate();
		if (m_cc_mode == 1){
			qp->mlx.m_targetRate = dev->GetDataRate();
		}else if (m_cc_mode == 3){
			qp->hp.m_curRate = dev->GetDataRate();
			if (m_multipleRate){
				for (uint32_t i = 0; i < IntHeader::maxHop; i++)
					qp->hp.hopState[i].Rc = dev->GetDataRate();
			}
		}else if (m_cc_mode == 7){
			qp->tmly.m_curRate = dev->GetDataRate();
		}else if (m_cc_mode == 10){
			qp->hpccPint.m_curRate = dev->GetDataRate();
		}
	}
	return 0;
}

int RdmaHw::ReceiveAck(Ptr<Packet> p, CustomHeader &ch){
	uint16_t qIndex = ch.ack.pg;
	uint16_t port = ch.ack.dport;
	uint32_t seq = ch.ack.seq;
	uint8_t cnp = (ch.ack.flags >> qbbHeader::FLAG_CNP) & 1;
	int i;
	Ptr<RdmaQueuePair> qp = GetQp(ch.sip, port, qIndex);
	if (qp == NULL){
		std::cout << "ERROR: " << "node:" << m_node->GetId() << ' ' << (ch.l3Prot == 0xFC ? "ACK" : "NACK") << " NIC cannot find the flow\n";
		return 0;
	}
	if (kEnableRetransLogging) {
		std::cout << "[Retrans][ReceiveAck] time=" << Simulator::Now().GetTimeStep()
		          << " node=" << m_node->GetId()
		          << " flow=" << ch.sip << "->" << ch.dip
		          << " type=" << (ch.l3Prot == 0xFD ? "NACK" : "ACK")	//确认类型
		          << " seq=" << seq	//确认序号
		          << " snd_una_before=" << qp->snd_una	//发送未确认序号
		          << std::endl;
	}

	uint32_t nic_idx = GetNicIdxOfQp(qp);
	Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;
	if (m_ack_interval == 0)
		std::cout << "ERROR: shouldn't receive ack\n";
	else {
		if (!m_backto0){
			qp->Acknowledge(seq);
		}else {
			uint32_t goback_seq = seq / m_chunk * m_chunk;
			qp->Acknowledge(goback_seq);
		}
		if (kEnableRetransLogging) {
			std::cout << "[Retrans][ReceiveAck] time=" << Simulator::Now().GetTimeStep()
			          << " node=" << m_node->GetId()
			          << " flow=" << ch.sip << "->" << ch.dip
			          << " snd_una_after=" << qp->snd_una	//发送未确认序号
			          << std::endl;
		}
		if (qp->IsFinished()){
			QpComplete(qp);
		}
	}
	if (ch.l3Prot == 0xFD) // NACK
	{
		if (kEnableRetransLogging) {
			std::cout << "[Retrans][ReceiveAck] time=" << Simulator::Now().GetTimeStep()
			          << " node=" << m_node->GetId()
			          << " flow=" << ch.sip << "->" << ch.dip
			          << " trigger=RECOVER_QUEUE" << std::endl;
		}
		RecoverQueue(qp);	//进入重传逻辑
	}

	// handle cnp
	if (cnp){
		if (m_cc_mode == 1){ // mlx version
			cnp_received_mlx(qp);
		} 
	}

	if (m_cc_mode == 3){
		HandleAckHp(qp, p, ch);
	}else if (m_cc_mode == 7){
		HandleAckTimely(qp, p, ch);
	}else if (m_cc_mode == 8){
		HandleAckDctcp(qp, p, ch);
	}else if (m_cc_mode == 10){
		HandleAckHpPint(qp, p, ch);
	}else if (m_cc_mode == 16){//lty
		HandleAckMySelf(qp, p, ch);
	}
	if (m_cc_mode == 1){
		// DCQCN路径在ACK处理后统一记录速率
		TraceFlowRate(qp, "DCQCN");
	}
	// ACK may advance the on-the-fly window, allowing more packets to send
	dev->TriggerTransmit();
	return 0;
}

int RdmaHw::Receive(Ptr<Packet> p, CustomHeader &ch){
	if (ch.l3Prot == 0x11){ // UDP
		ReceiveUdp(p, ch);
	}else if (ch.l3Prot == 0xFF){ // CNP
		ReceiveCnp(p, ch);
	}else if (ch.l3Prot == 0xFD){ // NACK
		ReceiveAck(p, ch);
	}else if (ch.l3Prot == 0xFC){ // ACK
		ReceiveAck(p, ch);
	}
	return 0;
}

int RdmaHw::ReceiverCheckSeq(uint32_t seq, Ptr<RdmaRxQueuePair> q, uint32_t size){
	uint32_t expected = q->ReceiverNextExpectedSeq;
	if (seq == expected){
		q->ReceiverNextExpectedSeq = expected + size;
		uint32_t bytesSinceAck = q->ReceiverNextExpectedSeq - q->m_lastAckedSeq;
		if (m_ack_interval == 0 || bytesSinceAck >= m_ack_interval){
			return 1;
		}
		return 5;
	} else if (seq > expected) {
		if (Simulator::Now() >= q->m_nackTimer || q->m_lastNACK != expected){
			q->m_nackTimer = Simulator::Now() + MicroSeconds(m_nack_interval);
			q->m_lastNACK = expected;
			if (m_backto0 && m_chunk != 0){
				q->ReceiverNextExpectedSeq = (q->ReceiverNextExpectedSeq / m_chunk) * m_chunk;
			}
			return 2;
		}
		return 4;
	}else {
		return 3;
	}
}
void RdmaHw::AddHeader (Ptr<Packet> p, uint16_t protocolNumber){
	PppHeader ppp;
	ppp.SetProtocol (EtherToPpp (protocolNumber));
	p->AddHeader (ppp);
}
uint16_t RdmaHw::EtherToPpp (uint16_t proto){
	switch(proto){
		case 0x0800: return 0x0021;   //IPv4
		case 0x86DD: return 0x0057;   //IPv6
		default: NS_ASSERT_MSG (false, "PPP Protocol number not defined!");
	}
	return 0;
}

void RdmaHw::RecoverQueue(Ptr<RdmaQueuePair> qp){
	if (kEnableRetransLogging) {
		std::cout << "[Retrans][RecoverQueue] time=" << Simulator::Now().GetTimeStep()
		          << " node=" << m_node->GetId()
		          << " flow=" << qp->sip << "->" << qp->dip
		          << " snd_una=" << qp->snd_una
		          << " snd_nxt_before=" << qp->snd_nxt
		          << " -> reset" << std::endl;
	}
	qp->snd_nxt = qp->snd_una;
}

void RdmaHw::QpComplete(Ptr<RdmaQueuePair> qp){
	NS_ASSERT(!m_qpCompleteCallback.IsNull());
	if (m_cc_mode == 1){
		Simulator::Cancel(qp->mlx.m_eventUpdateAlpha);
		Simulator::Cancel(qp->mlx.m_eventDecreaseRate);
		Simulator::Cancel(qp->mlx.m_rpTimer);
	}

	// This callback will log info
	// It may also delete the rxQp on the receiver
	m_qpCompleteCallback(qp);

	qp->m_notifyAppFinish();

	// delete the qp
	DeleteQueuePair(qp);
}

void RdmaHw::SetLinkDown(Ptr<QbbNetDevice> dev){
	printf("RdmaHw: node:%u a link down\n", m_node->GetId());
}

void RdmaHw::AddTableEntry(Ipv4Address &dstAddr, uint32_t intf_idx){
	uint32_t dip = dstAddr.Get();
	m_rtTable[dip].push_back(intf_idx);
}

void RdmaHw::ClearTable(){
	m_rtTable.clear();
}

void RdmaHw::RedistributeQp(){
	// clear old qpGrp
	for (uint32_t i = 0; i < m_nic.size(); i++){
		if (m_nic[i].dev == NULL)
			continue;
		m_nic[i].qpGrp->Clear();
	}

	// redistribute qp
	for (auto &it : m_qpMap){
		Ptr<RdmaQueuePair> qp = it.second;
		uint32_t nic_idx = GetNicIdxOfQp(qp);
		m_nic[nic_idx].qpGrp->AddQp(qp);
		// Notify Nic
		m_nic[nic_idx].dev->ReassignedQp(qp);
	}
}

Ptr<Packet> RdmaHw::GetNxtPacket(Ptr<RdmaQueuePair> qp){
	uint32_t payload_size = qp->GetBytesLeft();
	if (m_mtu < payload_size)
		payload_size = m_mtu;
	Ptr<Packet> p = Create<Packet> (payload_size);
	// add SeqTsHeader
	SeqTsHeader seqTs;
	seqTs.SetSeq (qp->snd_nxt);
	seqTs.SetPG (qp->m_pg);
	p->AddHeader (seqTs);
	// add udp header
	UdpHeader udpHeader;
	udpHeader.SetDestinationPort (qp->dport);
	udpHeader.SetSourcePort (qp->sport);
	p->AddHeader (udpHeader);
	// add ipv4 header
	Ipv4Header ipHeader;
	ipHeader.SetSource (qp->sip);
	ipHeader.SetDestination (qp->dip);
	ipHeader.SetProtocol (0x11);
	ipHeader.SetPayloadSize (p->GetSize());
	ipHeader.SetTtl (64);
	ipHeader.SetTos (0);
	ipHeader.SetIdentification (qp->m_ipid);
	p->AddHeader(ipHeader);
	// add ppp header
	PppHeader ppp;
	ppp.SetProtocol (0x0021); // EtherToPpp(0x800), see point-to-point-net-device.cc
	p->AddHeader (ppp);

	// update state
	qp->snd_nxt += payload_size;
	qp->m_ipid++;

	// return
	return p;
}

void RdmaHw::PktSent(Ptr<RdmaQueuePair> qp, Ptr<Packet> pkt, Time interframeGap){
	qp->lastPktSize = pkt->GetSize();
	UpdateNextAvail(qp, interframeGap, pkt->GetSize());
}

void RdmaHw::UpdateNextAvail(Ptr<RdmaQueuePair> qp, Time interframeGap, uint32_t pkt_size){
	Time sendingTime;
	if (m_rateBound)
		sendingTime = interframeGap + Seconds(qp->m_rate.CalculateTxTime(pkt_size));
	else
		sendingTime = interframeGap + Seconds(qp->m_max_rate.CalculateTxTime(pkt_size));
	qp->m_nextAvail = Simulator::Now() + sendingTime;
}

void RdmaHw::ChangeRate(Ptr<RdmaQueuePair> qp, DataRate new_rate){
	#if 1
	Time sendingTime = Seconds(qp->m_rate.CalculateTxTime(qp->lastPktSize));
	Time new_sendintTime = Seconds(new_rate.CalculateTxTime(qp->lastPktSize));
	qp->m_nextAvail = qp->m_nextAvail + new_sendintTime - sendingTime;
	// update nic's next avail event
	uint32_t nic_idx = GetNicIdxOfQp(qp);
	m_nic[nic_idx].dev->UpdateNextAvail(qp->m_nextAvail);
	#endif

	// change to new rate
	qp->m_rate = new_rate;
}

#define PRINT_LOG 0
/******************************
 * Mellanox's version of DCQCN
 *****************************/
void RdmaHw::UpdateAlphaMlx(Ptr<RdmaQueuePair> q){
	#if PRINT_LOG
	//std::cout << Simulator::Now() << " alpha update:" << m_node->GetId() << ' ' << q->mlx.m_alpha << ' ' << (int)q->mlx.m_alpha_cnp_arrived << '\n';
	//printf("%lu alpha update: %08x %08x %u %u %.6lf->", Simulator::Now().GetTimeStep(), q->sip.Get(), q->dip.Get(), q->sport, q->dport, q->mlx.m_alpha);
	#endif
	if (q->mlx.m_alpha_cnp_arrived){
		q->mlx.m_alpha = (1 - m_g)*q->mlx.m_alpha + m_g; 	//binary feedback
	}else {
		q->mlx.m_alpha = (1 - m_g)*q->mlx.m_alpha; 	//binary feedback
	}
	#if PRINT_LOG
	//printf("%.6lf\n", q->mlx.m_alpha);
	#endif
	q->mlx.m_alpha_cnp_arrived = false; // clear the CNP_arrived bit
	ScheduleUpdateAlphaMlx(q);
}
void RdmaHw::ScheduleUpdateAlphaMlx(Ptr<RdmaQueuePair> q){
	q->mlx.m_eventUpdateAlpha = Simulator::Schedule(MicroSeconds(m_alpha_resume_interval), &RdmaHw::UpdateAlphaMlx, this, q);
}

void RdmaHw::cnp_received_mlx(Ptr<RdmaQueuePair> q){
	q->mlx.m_alpha_cnp_arrived = true; // set CNP_arrived bit for alpha update
	q->mlx.m_decrease_cnp_arrived = true; // set CNP_arrived bit for rate decrease
	if (q->mlx.m_first_cnp){
		// init alpha
		q->mlx.m_alpha = 1;
		q->mlx.m_alpha_cnp_arrived = false;
		// schedule alpha update
		ScheduleUpdateAlphaMlx(q);
		// schedule rate decrease
		ScheduleDecreaseRateMlx(q, 1); // add 1 ns to make sure rate decrease is after alpha update
		// set rate on first CNP
		q->mlx.m_targetRate = q->m_rate = m_rateOnFirstCNP * q->m_rate;
		q->mlx.m_first_cnp = false;
	}
	// 记录CNP响应后的速率，用于DCQCN曲线
	TraceFlowRate(q, "DCQCN");
}

void RdmaHw::CheckRateDecreaseMlx(Ptr<RdmaQueuePair> q){
	ScheduleDecreaseRateMlx(q, 0);
	if (q->mlx.m_decrease_cnp_arrived){
		#if PRINT_LOG
		printf("%lu rate dec: %08x %08x %u %u (%0.3lf %.3lf)->", Simulator::Now().GetTimeStep(), q->sip.Get(), q->dip.Get(), q->sport, q->dport, q->mlx.m_targetRate.GetBitRate() * 1e-9, q->m_rate.GetBitRate() * 1e-9);
		#endif
		bool clamp = true;
		if (!m_EcnClampTgtRate){
			if (q->mlx.m_rpTimeStage == 0)
				clamp = false;
		}
		if (clamp)
			q->mlx.m_targetRate = q->m_rate;
		q->m_rate = std::max(m_minRate, q->m_rate * (1 - q->mlx.m_alpha / 2));
		// reset rate increase related things
		q->mlx.m_rpTimeStage = 0;
		q->mlx.m_decrease_cnp_arrived = false;
		Simulator::Cancel(q->mlx.m_rpTimer);
		q->mlx.m_rpTimer = Simulator::Schedule(MicroSeconds(m_rpgTimeReset), &RdmaHw::RateIncEventTimerMlx, this, q);
		#if PRINT_LOG
		printf("(%.3lf %.3lf)\n", q->mlx.m_targetRate.GetBitRate() * 1e-9, q->m_rate.GetBitRate() * 1e-9);
		#endif
		TraceFlowRate(q, "DCQCN");
	}
}
void RdmaHw::ScheduleDecreaseRateMlx(Ptr<RdmaQueuePair> q, uint32_t delta){
	q->mlx.m_eventDecreaseRate = Simulator::Schedule(MicroSeconds(m_rateDecreaseInterval) + NanoSeconds(delta), &RdmaHw::CheckRateDecreaseMlx, this, q);
}

void RdmaHw::RateIncEventTimerMlx(Ptr<RdmaQueuePair> q){
	q->mlx.m_rpTimer = Simulator::Schedule(MicroSeconds(m_rpgTimeReset), &RdmaHw::RateIncEventTimerMlx, this, q);
	RateIncEventMlx(q);
	q->mlx.m_rpTimeStage++;
}
void RdmaHw::RateIncEventMlx(Ptr<RdmaQueuePair> q){
	// check which increase phase: fast recovery, active increase, hyper increase
	if (q->mlx.m_rpTimeStage < m_rpgThreshold){ // fast recovery
		FastRecoveryMlx(q);
	}else if (q->mlx.m_rpTimeStage == m_rpgThreshold){ // active increase
		ActiveIncreaseMlx(q);
	}else { // hyper increase
		HyperIncreaseMlx(q);
	}
}

void RdmaHw::FastRecoveryMlx(Ptr<RdmaQueuePair> q){
	#if PRINT_LOG
	printf("%lu fast recovery: %08x %08x %u %u (%0.3lf %.3lf)->", Simulator::Now().GetTimeStep(), q->sip.Get(), q->dip.Get(), q->sport, q->dport, q->mlx.m_targetRate.GetBitRate() * 1e-9, q->m_rate.GetBitRate() * 1e-9);
	#endif
	q->m_rate = (q->m_rate / 2) + (q->mlx.m_targetRate / 2);
	#if PRINT_LOG
	printf("(%.3lf %.3lf)\n", q->mlx.m_targetRate.GetBitRate() * 1e-9, q->m_rate.GetBitRate() * 1e-9);
	#endif
	TraceFlowRate(q, "DCQCN");
}
void RdmaHw::ActiveIncreaseMlx(Ptr<RdmaQueuePair> q){
	#if PRINT_LOG
	printf("%lu active inc: %08x %08x %u %u (%0.3lf %.3lf)->", Simulator::Now().GetTimeStep(), q->sip.Get(), q->dip.Get(), q->sport, q->dport, q->mlx.m_targetRate.GetBitRate() * 1e-9, q->m_rate.GetBitRate() * 1e-9);
	#endif
	// get NIC
	uint32_t nic_idx = GetNicIdxOfQp(q);
	Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;
	// increate rate
	q->mlx.m_targetRate += m_rai;
	if (q->mlx.m_targetRate > dev->GetDataRate())
		q->mlx.m_targetRate = dev->GetDataRate();
	q->m_rate = (q->m_rate / 2) + (q->mlx.m_targetRate / 2);
	#if PRINT_LOG
	printf("(%.3lf %.3lf)\n", q->mlx.m_targetRate.GetBitRate() * 1e-9, q->m_rate.GetBitRate() * 1e-9);
	#endif
	TraceFlowRate(q, "DCQCN");
}
void RdmaHw::HyperIncreaseMlx(Ptr<RdmaQueuePair> q){
	#if PRINT_LOG
	printf("%lu hyper inc: %08x %08x %u %u (%0.3lf %.3lf)->", Simulator::Now().GetTimeStep(), q->sip.Get(), q->dip.Get(), q->sport, q->dport, q->mlx.m_targetRate.GetBitRate() * 1e-9, q->m_rate.GetBitRate() * 1e-9);
	#endif
	// get NIC
	uint32_t nic_idx = GetNicIdxOfQp(q);
	Ptr<QbbNetDevice> dev = m_nic[nic_idx].dev;
	// increate rate
	q->mlx.m_targetRate += m_rhai;
	if (q->mlx.m_targetRate > dev->GetDataRate())
		q->mlx.m_targetRate = dev->GetDataRate();
	q->m_rate = (q->m_rate / 2) + (q->mlx.m_targetRate / 2);
	#if PRINT_LOG
	printf("(%.3lf %.3lf)\n", q->mlx.m_targetRate.GetBitRate() * 1e-9, q->m_rate.GetBitRate() * 1e-9);
	#endif
	TraceFlowRate(q, "DCQCN");
}

/***********************
 * High Precision CC
 ***********************/
void RdmaHw::HandleAckHp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch){
	uint32_t ack_seq = ch.ack.seq;
	// update rate
	if (ack_seq > qp->hp.m_lastUpdateSeq){ // if full RTT feedback is ready, do full update
		UpdateRateHp(qp, p, ch, false);
	}else{ // do fast react
		FastReactHp(qp, p, ch);
	}
	// 新增速率跟踪接口，记录HPCC路径上的速率演化
	TraceFlowRate(qp, "HPCC");
}

void RdmaHw::UpdateRateHp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch, bool fast_react){
	uint32_t next_seq = qp->snd_nxt;
	bool print = !fast_react || true;
	if (qp->hp.m_lastUpdateSeq == 0){ // first RTT
		qp->hp.m_lastUpdateSeq = next_seq;
		// store INT
		IntHeader &ih = ch.ack.ih;
		NS_ASSERT(ih.nhop <= IntHeader::maxHop);
		for (uint32_t i = 0; i < ih.nhop; i++)
			qp->hp.hop[i] = ih.hop[i];
		#if PRINT_LOG
		if (print){
			printf("%lu %s %08x %08x %u %u [%u,%u,%u]", Simulator::Now().GetTimeStep(), fast_react? "fast" : "update", qp->sip.Get(), qp->dip.Get(), qp->sport, qp->dport, qp->hp.m_lastUpdateSeq, ch.ack.seq, next_seq);
			for (uint32_t i = 0; i < ih.nhop; i++)
				printf(" %u %lu %lu", ih.hop[i].GetQlen(), ih.hop[i].GetBytes(), ih.hop[i].GetTime());
			printf("\n");
		}
		#endif
	}else {
		// check packet INT
		IntHeader &ih = ch.ack.ih;
		if (ih.nhop <= IntHeader::maxHop){
			double max_c = 0;
			bool inStable = false;
			#if PRINT_LOG
			if (print)
				printf("%lu %s %08x %08x %u %u [%u,%u,%u]", Simulator::Now().GetTimeStep(), fast_react? "fast" : "update", qp->sip.Get(), qp->dip.Get(), qp->sport, qp->dport, qp->hp.m_lastUpdateSeq, ch.ack.seq, next_seq);
			#endif
			// check each hop
			double U = 0;
			uint64_t dt = 0;
			bool updated[IntHeader::maxHop] = {false}, updated_any = false;
			NS_ASSERT(ih.nhop <= IntHeader::maxHop);
			for (uint32_t i = 0; i < ih.nhop; i++){
				if (m_sampleFeedback){
					if (ih.hop[i].GetQlen() == 0 && fast_react)
						continue;
				}
				updated[i] = updated_any = true;
				#if PRINT_LOG
				if (print)
					printf(" %u(%u) %lu(%lu) %lu(%lu)", ih.hop[i].GetQlen(), qp->hp.hop[i].GetQlen(), ih.hop[i].GetBytes(), qp->hp.hop[i].GetBytes(), ih.hop[i].GetTime(), qp->hp.hop[i].GetTime());
				#endif
				uint64_t tau = ih.hop[i].GetTimeDelta(qp->hp.hop[i]);;
				double duration = tau * 1e-9;
				double txRate = (ih.hop[i].GetBytesDelta(qp->hp.hop[i])) * 8 / duration;
				double u = txRate / ih.hop[i].GetLineRate() + (double)std::min(ih.hop[i].GetQlen(), qp->hp.hop[i].GetQlen()) * qp->m_max_rate.GetBitRate() / ih.hop[i].GetLineRate() /qp->m_win;
				#if PRINT_LOG
				if (print)
					printf(" %.3lf %.3lf", txRate, u);
				#endif
				if (!m_multipleRate){
					// for aggregate (single R)
					if (u > U){
						U = u;
						dt = tau;
					}
				}else {
					// for per hop (per hop R)
					if (tau > qp->m_baseRtt)
						tau = qp->m_baseRtt;
					qp->hp.hopState[i].u = (qp->hp.hopState[i].u * (qp->m_baseRtt - tau) + u * tau) / double(qp->m_baseRtt);
				}
				qp->hp.hop[i] = ih.hop[i];
			}

			DataRate new_rate;
			int32_t new_incStage;
			DataRate new_rate_per_hop[IntHeader::maxHop];
			int32_t new_incStage_per_hop[IntHeader::maxHop];
			if (!m_multipleRate){
				// for aggregate (single R)
				if (updated_any){
					if (dt > qp->m_baseRtt)
						dt = qp->m_baseRtt;
					qp->hp.u = (qp->hp.u * (qp->m_baseRtt - dt) + U * dt) / double(qp->m_baseRtt);
					max_c = qp->hp.u / m_targetUtil;

					if (max_c >= 1 || qp->hp.m_incStage >= m_miThresh){
						new_rate = qp->hp.m_curRate / max_c + m_rai;
						new_incStage = 0;
					}else{
						new_rate = qp->hp.m_curRate + m_rai;
						new_incStage = qp->hp.m_incStage+1;
					}
					if (new_rate < m_minRate)
						new_rate = m_minRate;
					if (new_rate > qp->m_max_rate)
						new_rate = qp->m_max_rate;
					#if PRINT_LOG
					if (print)
						printf(" u=%.6lf U=%.3lf dt=%u max_c=%.3lf", qp->hp.u, U, dt, max_c);
					#endif
					#if PRINT_LOG
					if (print)
						printf(" rate:%.3lf->%.3lf\n", qp->hp.m_curRate.GetBitRate()*1e-9, new_rate.GetBitRate()*1e-9);
					#endif
				}
			}else{
				// for per hop (per hop R)
				new_rate = qp->m_max_rate;
				for (uint32_t i = 0; i < ih.nhop; i++){
					if (updated[i]){
						double c = qp->hp.hopState[i].u / m_targetUtil;
						if (c >= 1 || qp->hp.hopState[i].incStage >= m_miThresh){
							new_rate_per_hop[i] = qp->hp.hopState[i].Rc / c + m_rai;
							new_incStage_per_hop[i] = 0;
						}else{
							new_rate_per_hop[i] = qp->hp.hopState[i].Rc + m_rai;
							new_incStage_per_hop[i] = qp->hp.hopState[i].incStage+1;
						}
						// bound rate
						if (new_rate_per_hop[i] < m_minRate)
							new_rate_per_hop[i] = m_minRate;
						if (new_rate_per_hop[i] > qp->m_max_rate)
							new_rate_per_hop[i] = qp->m_max_rate;
						// find min new_rate
						if (new_rate_per_hop[i] < new_rate)
							new_rate = new_rate_per_hop[i];
						#if PRINT_LOG
						if (print)
							printf(" [%u]u=%.6lf c=%.3lf", i, qp->hp.hopState[i].u, c);
						#endif
						#if PRINT_LOG
						if (print)
							printf(" %.3lf->%.3lf", qp->hp.hopState[i].Rc.GetBitRate()*1e-9, new_rate.GetBitRate()*1e-9);
						#endif
					}else{
						if (qp->hp.hopState[i].Rc < new_rate)
							new_rate = qp->hp.hopState[i].Rc;
					}
				}
				#if PRINT_LOG
				printf("\n");
				#endif
			}
			if (updated_any)
				ChangeRate(qp, new_rate);
			if (!fast_react){
				if (updated_any){
					qp->hp.m_curRate = new_rate;
					qp->hp.m_incStage = new_incStage;
				}
				if (m_multipleRate){
					// for per hop (per hop R)
					for (uint32_t i = 0; i < ih.nhop; i++){
						if (updated[i]){
							qp->hp.hopState[i].Rc = new_rate_per_hop[i];
							qp->hp.hopState[i].incStage = new_incStage_per_hop[i];
						}
					}
				}
			}
		}
		if (!fast_react){
			if (next_seq > qp->hp.m_lastUpdateSeq)
				qp->hp.m_lastUpdateSeq = next_seq; //+ rand() % 2 * m_mtu;
		}
	}
}

void RdmaHw::FastReactHp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch){
	if (m_fast_react)
		UpdateRateHp(qp, p, ch, true);
}

/**********************
 * TIMELY
 *********************/
void RdmaHw::HandleAckTimely(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch){
	uint32_t ack_seq = ch.ack.seq;
	// update rate
	if (ack_seq > qp->tmly.m_lastUpdateSeq){ // if full RTT feedback is ready, do full update
		UpdateRateTimely(qp, p, ch, false);
	}else{ // do fast react
		FastReactTimely(qp, p, ch);
	}
	// 记录TIMELY算法当前速率，便于离线绘图
	TraceFlowRate(qp, "TIMELY");
}
void RdmaHw::UpdateRateTimely(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch, bool us){
	uint32_t next_seq = qp->snd_nxt;
	uint64_t rtt = Simulator::Now().GetTimeStep() - ch.ack.ih.ts;
	bool print = !us;
	if (qp->tmly.m_lastUpdateSeq != 0){ // not first RTT
		int64_t new_rtt_diff = (int64_t)rtt - (int64_t)qp->tmly.lastRtt;
		double rtt_diff = (1 - m_tmly_alpha) * qp->tmly.rttDiff + m_tmly_alpha * new_rtt_diff;
		double gradient = rtt_diff / m_tmly_minRtt;
		bool inc = false;
		double c = 0;
		#if PRINT_LOG
		if (print)
			printf("%lu node:%u rtt:%lu rttDiff:%.0lf gradient:%.3lf rate:%.3lf", Simulator::Now().GetTimeStep(), m_node->GetId(), rtt, rtt_diff, gradient, qp->tmly.m_curRate.GetBitRate() * 1e-9);
		#endif
		if (rtt < m_tmly_TLow){
			inc = true;
		}else if (rtt > m_tmly_THigh){
			c = 1 - m_tmly_beta * (1 - (double)m_tmly_THigh / rtt);
			inc = false;
		}else if (gradient <= 0){
			inc = true;
		}else{
			c = 1 - m_tmly_beta * gradient;
			if (c < 0)
				c = 0;
			inc = false;
		}
		if (inc){
			if (qp->tmly.m_incStage < 5){
				qp->m_rate = qp->tmly.m_curRate + m_rai;
			}else{
				qp->m_rate = qp->tmly.m_curRate + m_rhai;
			}
			if (qp->m_rate > qp->m_max_rate)
				qp->m_rate = qp->m_max_rate;
			if (!us){
				qp->tmly.m_curRate = qp->m_rate;
				qp->tmly.m_incStage++;
				qp->tmly.rttDiff = rtt_diff;
			}
		}else{
			qp->m_rate = std::max(m_minRate, qp->tmly.m_curRate * c); 
			if (!us){
				qp->tmly.m_curRate = qp->m_rate;
				qp->tmly.m_incStage = 0;
				qp->tmly.rttDiff = rtt_diff;
			}
		}
		#if PRINT_LOG
		if (print){
			printf(" %c %.3lf\n", inc? '^':'v', qp->m_rate.GetBitRate() * 1e-9);
		}
		#endif
	}
	if (!us && next_seq > qp->tmly.m_lastUpdateSeq){
		qp->tmly.m_lastUpdateSeq = next_seq;
		// update
		qp->tmly.lastRtt = rtt;
	}
}
void RdmaHw::FastReactTimely(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch){
}

/**********************
 * DCTCP
 *********************/
void RdmaHw::HandleAckDctcp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch){
	uint32_t ack_seq = ch.ack.seq;
	uint8_t cnp = (ch.ack.flags >> qbbHeader::FLAG_CNP) & 1;
	bool new_batch = false;

	// update alpha
	qp->dctcp.m_ecnCnt += (cnp > 0);
	if (ack_seq > qp->dctcp.m_lastUpdateSeq){ // if full RTT feedback is ready, do alpha update
		#if PRINT_LOG
		printf("%lu %s %08x %08x %u %u [%u,%u,%u] %.3lf->", Simulator::Now().GetTimeStep(), "alpha", qp->sip.Get(), qp->dip.Get(), qp->sport, qp->dport, qp->dctcp.m_lastUpdateSeq, ch.ack.seq, qp->snd_nxt, qp->dctcp.m_alpha);
		#endif
		new_batch = true;
		if (qp->dctcp.m_lastUpdateSeq == 0){ // first RTT
			qp->dctcp.m_lastUpdateSeq = qp->snd_nxt;
			qp->dctcp.m_batchSizeOfAlpha = qp->snd_nxt / m_mtu + 1;
		}else {
			double frac = std::min(1.0, double(qp->dctcp.m_ecnCnt) / qp->dctcp.m_batchSizeOfAlpha);
			qp->dctcp.m_alpha = (1 - m_g) * qp->dctcp.m_alpha + m_g * frac;
			qp->dctcp.m_lastUpdateSeq = qp->snd_nxt;
			qp->dctcp.m_ecnCnt = 0;
			qp->dctcp.m_batchSizeOfAlpha = (qp->snd_nxt - ack_seq) / m_mtu + 1;
			#if PRINT_LOG
			printf("%.3lf F:%.3lf", qp->dctcp.m_alpha, frac);
			#endif
		}
		#if PRINT_LOG
		printf("\n");
		#endif
	}

	// check cwr exit
	if (qp->dctcp.m_caState == 1){
		if (ack_seq > qp->dctcp.m_highSeq)
			qp->dctcp.m_caState = 0;
	}

	// check if need to reduce rate: ECN and not in CWR
	if (cnp && qp->dctcp.m_caState == 0){
		#if PRINT_LOG
		printf("%lu %s %08x %08x %u %u %.3lf->", Simulator::Now().GetTimeStep(), "rate", qp->sip.Get(), qp->dip.Get(), qp->sport, qp->dport, qp->m_rate.GetBitRate()*1e-9);
		#endif
		qp->m_rate = std::max(m_minRate, qp->m_rate * (1 - qp->dctcp.m_alpha / 2));
		#if PRINT_LOG
		printf("%.3lf\n", qp->m_rate.GetBitRate() * 1e-9);
		#endif
		qp->dctcp.m_caState = 1;
		qp->dctcp.m_highSeq = qp->snd_nxt;
	}

	// additive inc
	if (qp->dctcp.m_caState == 0 && new_batch)
		qp->m_rate = std::min(qp->m_max_rate, qp->m_rate + m_dctcp_rai);

	// DCTCP路径也输出日志，捕获速率与状态
	TraceFlowRate(qp, "DCTCP");
}

/*********************
 * HPCC-PINT
 ********************/
void RdmaHw::SetPintSmplThresh(double p){
       pint_smpl_thresh = (uint32_t)(65536 * p);
}
void RdmaHw::HandleAckHpPint(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch){
       uint32_t ack_seq = ch.ack.seq;
       if (rand() % 65536 >= pint_smpl_thresh){
	       // 采样被跳过时也记录速率，方便分析数据空洞
	       TraceFlowRate(qp, "HPCC-PINT_SKIP");
	       return;
       }
       // update rate
       if (ack_seq > qp->hpccPint.m_lastUpdateSeq){ // if full RTT feedback is ready, do full update
               UpdateRateHpPint(qp, p, ch, false);
       }else{ // do fast react
               UpdateRateHpPint(qp, p, ch, true);
       }
	// HPCC-PINT 生效时记录当前速率
	TraceFlowRate(qp, "HPCC-PINT");
}

void RdmaHw::UpdateRateHpPint(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch, bool fast_react){
       uint32_t next_seq = qp->snd_nxt;
       if (qp->hpccPint.m_lastUpdateSeq == 0){ // first RTT
               qp->hpccPint.m_lastUpdateSeq = next_seq;
       }else {
               // check packet INT
               IntHeader &ih = ch.ack.ih;
               double U = Pint::decode_u(ih.GetPower());

               DataRate new_rate;
               int32_t new_incStage;
               double max_c = U / m_targetUtil;

               if (max_c >= 1 || qp->hpccPint.m_incStage >= m_miThresh){
                       new_rate = qp->hpccPint.m_curRate / max_c + m_rai;
                       new_incStage = 0;
               }else{
                       new_rate = qp->hpccPint.m_curRate + m_rai;
                       new_incStage = qp->hpccPint.m_incStage+1;
               }
               if (new_rate < m_minRate)
                       new_rate = m_minRate;
               if (new_rate > qp->m_max_rate)
                       new_rate = qp->m_max_rate;
               ChangeRate(qp, new_rate);
               if (!fast_react){
                       qp->hpccPint.m_curRate = new_rate;
                       qp->hpccPint.m_incStage = new_incStage;
               }
               if (!fast_react){
                       if (next_seq > qp->hpccPint.m_lastUpdateSeq)
                               qp->hpccPint.m_lastUpdateSeq = next_seq; //+ rand() % 2 * m_mtu;
               }
       }
}

/*********************
 * lty's AICC 
 ********************/
void RdmaHw::ReadRate(){
       // 读取共享内存中的速率信息并打印，读取后将速率重置为-1
       RttShmData* data = ShmManager::GetShm();
       if (data == nullptr || data == MAP_FAILED) {
               std::cout << "ReadRate: shared memory unavailable" << std::endl;
               return;
       }

       // 读取padding区域中Python写入的float类型发送速率（单位：Mbps）
       float rate_mbps = -1.0f;
       static_assert(sizeof(data->padding) >= sizeof(float), "padding too small for rate");
       std::memcpy(&rate_mbps, data->padding, sizeof(float));

       // 如果速率是-1，说明还没有更新，直接返回
       if (rate_mbps == -1.0f) {
               return;
       }

       double rtt_ms = data->rtt_ns / 1e6;
       // double timestamp_ms = data->timestamp_ns / 1e6;
       auto seq = data->sequence.load(std::memory_order_acquire);
       std::cout << "[序列号: " << seq << "] "
                 << "节点ID: " << data->node_id << " | "
                 << "QP: [" << Ipv4Address(data->sip) << ":" << data->sport
                 << " -> " << Ipv4Address(data->dip) << ":" << data->dport << "] | "
                 << "ACK序列: " << data->ack_seq << " | "
                 << "RTT: " << data->rtt_ns << " ns (" << rtt_ms << " ms) | "
                 << "CNP: " << static_cast<uint32_t>(data->cnp) << " | "
                 << "时间戳: " << data->timestamp_ns << " ns | "
                 << "发送速率: " << rate_mbps << " Mbps"
                 << std::endl;
       
       // 读取后将速率重置为-1，便于下一轮检测
       float reset_rate = -1.0f;
       std::memcpy(data->padding, &reset_rate, sizeof(float));
}


void RdmaHw::HandleAckMySelf(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch){
	uint32_t ack_seq = ch.ack.seq;

	// lty 打印一下当前qp的发送速率
	std::cout<<"当前qp的发送速率数值是"<<qp->m_rate.GetBitRate()*1e-9 <<"Gb"<<std::endl;

	// 从ACK中提取RTT信息（需要IntHeader::mode == TS模式）
	if (IntHeader::mode == IntHeader::TS){
		uint64_t tx_timestamp = ch.ack.ih.GetTs();
		if (tx_timestamp > 0){
			uint64_t current_time = Simulator::Now().GetTimeStep();
			uint64_t rtt_ns = current_time - tx_timestamp;
				
			// 输出RTT信息（可选，用于调试）
			std::cout << "My CC: node=" << m_node->GetId() 
						<< " qp=[" << qp->sip << ":" << qp->sport << " -> " 
						<< qp->dip << ":" << qp->dport << "] seq=" << ack_seq 
						<< " RTT=" << rtt_ns << " ns (" 
						<< rtt_ns / 1000000.0 << " ms)" << std::endl;

			//lty 打印cnp标志位
			uint8_t cnp=(ch.ack.flags >> qbbHeader::FLAG_CNP) & 1;	
			if(cnp==1)
			    std::cout<<"this ACK pkt's CNP flag=="<<int(cnp)<<std::endl;
			
			// lty: 将RTT信息和CNP标记位写入共享内存
			ShmManager::WriteRtt(m_node->GetId(), 
			                     qp->sip.Get(), qp->sport,
			                     qp->dip.Get(), qp->dport,
			                     ack_seq, rtt_ns, current_time, cnp);

			// lty: 同步阻塞式等待 Python 写入速率（方案A）
			std::cout << "My CC: 等待Python端写入速率..." << std::endl; // lty

			RttShmData* data = ShmManager::GetShm(); // lty
			if (data == nullptr || data == MAP_FAILED) { // lty
				std::cout << "My CC: shared memory unavailable when waiting for rate" << std::endl; // lty
				TraceFlowRate(qp, "AICC"); // 记录异常场景下的速率
				return; // lty
			}

			float rate_mbps = -1.0f;
			while (true) { // lty: 轮询直到rate被写入
				std::memcpy(&rate_mbps, data->padding, sizeof(float));
				if (rate_mbps != -1.0f) {
					break; // lty: rate已更新
				}
				std::this_thread::sleep_for(std::chrono::milliseconds(1)); // lty: 1ms 间隔轮询
			}

			// lty: 读取并打印速率信息，同时将速率重置为-1，方便下一轮检测
			ReadRate();

			// lty: 将Python写入的速率（Gbps）转换为DataRate并作用到当前QP
			if (rate_mbps > 0.0f) {
				uint64_t rate_bps = static_cast<uint64_t>(rate_mbps * 1e9); // Gbps -> bps
				DataRate new_rate(rate_bps);
				if (new_rate > qp->m_max_rate) {
					new_rate = qp->m_max_rate;
				}
				if (new_rate < m_minRate) {
					new_rate = m_minRate;
				}
				std::cout << "My CC: 将速率更新为 " << new_rate.GetBitRate() * 1e-9 << " Gb/s" << std::endl;
				ChangeRate(qp, new_rate);
				std::cout<<"执行速率变更,更新后的速率为:"<<qp->m_rate.GetBitRate()*1e-9 <<"Gb"<<std::endl;

				uint64_t currentRateBps = qp->m_rate.GetBitRate();	//当前QP的速率
				uint64_t minRateBps = m_minRate.GetBitRate();		//系统配置的最小速率
				//if (currentRateBps > 0 && currentRateBps <= minRateBps && minRateBps > 0) {
				if (currentRateBps > 0 && currentRateBps*1e-9 <= 1) {
					uint64_t bytesLeft = qp->GetBytesLeft();	//当前QP剩余待发送的字节数
					if (bytesLeft > 0) {
						double simSec = Simulator::Now().GetSeconds();	//当前仿真时间（秒）
						double stopSec = 16;	//配置的仿真停止时间（秒）
						double estimatedFinishSec = simSec + (static_cast<double>(bytesLeft) * 8.0) / static_cast<double>(currentRateBps);	//预计完成时间（秒）
						std::cout << "[AICC][诊断] 调试参数: currentRateBps=" << currentRateBps
							  << " bps, minRateBps=" << minRateBps
							  << " bps, bytesLeft=" << bytesLeft
							  << " B, simSec=" << simSec
							  << " s, stopSec=" << stopSec
							  << " s, estimatedFinishSec=" << estimatedFinishSec
							  << " s" << std::endl;
						uint32_t qpHash = qp->GetHash();
						// if (estimatedFinishSec > stopSec && g_minRateWarningIssued.insert(qpHash).second) {
						if (estimatedFinishSec > stopSec ) {
							std::cout << "[AICC][诊断] QP [" << qp->sip << ":" << qp->sport
									<< " -> " << qp->dip << ":" << qp->dport << "] 仍有 " << bytesLeft
									<< " 字节未发送，在最小速率 " << static_cast<double>(currentRateBps) / 1e9
									<< " Gb/s 下预计完成时间为 " << estimatedFinishSec
									<< " s，超过 SIMULATOR_STOP_TIME 配置的 " << stopSec
									<< " s。" << std::endl;
						}
					}
				}
			} else {
				std::cout << "My CC: 收到无效速率 " << rate_mbps << "，保持原速率" << std::endl;
			}
		}
	}
	
	// 你也可以从ACK中提取其他信息，例如：
	// - CNP标志（拥塞通知）：uint8_t cnp = (ch.ack.flags >> qbbHeader::FLAG_CNP) & 1;
	// - INT header中的队列长度信息（如果使用NORMAL模式）
	// - 序列号用于判断是否完成了一个RTT
	TraceFlowRate(qp, "AICC");
}

// lty: ShmManager静态成员定义
const char* ShmManager::SHM_NAME = "/rtt_shm_lty";
const size_t ShmManager::SHM_SIZE = sizeof(RttShmData);
RttShmData* ShmManager::rtt_data = nullptr;
int ShmManager::shm_fd = -1;
std::once_flag ShmManager::init_flag;
std::unordered_map<uint32_t, uint64_t> ShmManager::node_sequence_map;
std::mutex ShmManager::sequence_map_mutex;

//lty 初始化共享内存函数的实现
void ShmManager::InitShm() {
	
	shm_fd = shm_open(SHM_NAME, O_CREAT | O_RDWR, 0666);
	if (shm_fd == -1) {
		perror("shm_open failed");
		return;
	}
	
	if (ftruncate(shm_fd, SHM_SIZE) == -1) {
		perror("ftruncate failed");
		close(shm_fd);
		return;
	}
	
	rtt_data = (RttShmData*)mmap(NULL, SHM_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, shm_fd, 0);
	if (rtt_data == MAP_FAILED) {
		perror("mmap failed");
		close(shm_fd);
		return;
	}
	
	// 初始化共享内存
	memset(rtt_data, 0, SHM_SIZE);
	rtt_data->sequence.store(0);
	
	// 初始化速率为-1，表示尚未更新
	float init_rate = -1.0f;
	std::memcpy(rtt_data->padding, &init_rate, sizeof(float));
}

//lty 写RTT信息和CNP标记位的函数实现
void ShmManager::WriteRtt(uint32_t node_id, uint32_t sip, uint16_t sport, 
	uint32_t dip, uint16_t dport, uint32_t ack_seq, 
	uint64_t rtt_ns, uint64_t timestamp_ns, uint8_t cnp) {
		
	RttShmData* data = GetShm();
	if (data == nullptr || data == MAP_FAILED) {
		return;
	}

	// 写入数据
	data->node_id = node_id;
	data->sip = sip;
	data->sport = sport;
	data->dip = dip;
	data->dport = dport;
	data->ack_seq = ack_seq;
	data->rtt_ns = rtt_ns;
	data->timestamp_ns = timestamp_ns;
	data->cnp = cnp;

	// lty: 更新序列号（针对每个node_id单独计数）
	// 获取或创建该node_id的计数器，然后递增
	uint64_t seq;
	{
		std::lock_guard<std::mutex> lock(sequence_map_mutex);
		// 如果该node_id不存在，创建并初始化为0
		if (node_sequence_map.find(node_id) == node_sequence_map.end()) {
			node_sequence_map[node_id] = 0;
		}
		// 递增该node_id的计数器
		seq = ++node_sequence_map[node_id];
	}
	// 将计数器值写入共享内存（最后更新，确保数据一致性）
	data->sequence.store(seq, std::memory_order_release);
}
}
