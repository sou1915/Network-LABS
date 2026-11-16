//! Experimental autonomous Ethernet appliances. No WASI, host sockets or host clock.
//! All traffic decisions, ARP/ICMP/TCP state and FDB entries live in guest memory.
use std::cell::RefCell;
use std::collections::{BTreeMap, VecDeque};
use smoltcp::iface::{Config, Interface, SocketHandle, SocketSet};
use smoltcp::phy::{Device, DeviceCapabilities, Medium, RxToken, TxToken};
use smoltcp::socket::{icmp, tcp};
use smoltcp::time::Instant;
use smoltcp::wire::{EthernetAddress, HardwareAddress, Icmpv4Packet, Icmpv4Repr, IpAddress, IpCidr, Ipv4Address};

const MTU: usize = 1514;
const PAYLOAD_LIMIT: usize = 512;
const QUEUE_LIMIT: usize = 32;

#[link(wasm_import_module = "lab")]
extern "C" {
    fn emit(port: u32, pointer: *const u8, length: usize);
}

struct Nic {
    rx: VecDeque<Vec<u8>>,
    tx: VecDeque<Vec<u8>>,
}
struct Rx(Vec<u8>);
struct Tx<'a>(&'a mut VecDeque<Vec<u8>>);
impl RxToken for Rx {
    fn consume<R, F>(self, f: F) -> R where F: FnOnce(&[u8]) -> R { f(&self.0) }
}
impl TxToken for Tx<'_> {
    fn consume<R, F>(self, len: usize, f: F) -> R where F: FnOnce(&mut [u8]) -> R {
        assert!(len <= MTU && self.0.len() < QUEUE_LIMIT);
        let mut frame = vec![0; len];
        let result = f(&mut frame);
        self.0.push_back(frame);
        result
    }
}
impl Device for Nic {
    type RxToken<'a> = Rx where Self: 'a;
    type TxToken<'a> = Tx<'a> where Self: 'a;
    fn receive(&mut self, _now: Instant) -> Option<(Rx, Tx<'_>)> {
        self.rx.pop_front().map(|frame| (Rx(frame), Tx(&mut self.tx)))
    }
    fn transmit(&mut self, _now: Instant) -> Option<Tx<'_>> {
        if self.tx.len() < QUEUE_LIMIT { Some(Tx(&mut self.tx)) } else { None }
    }
    fn capabilities(&self) -> DeviceCapabilities {
        let mut c = DeviceCapabilities::default();
        c.medium = Medium::Ethernet;
        c.max_transmission_unit = MTU;
        c.max_burst_size = Some(1);
        c
    }
}

struct Endpoint {
    nic: Nic,
    iface: Interface,
    sockets: SocketSet<'static>,
    icmp: SocketHandle,
    tcp: SocketHandle,
    id: u16,
    server: bool,
    pending: Vec<u8>,
    reply: Vec<u8>,
    ping_reply: Vec<u8>,
    expected_ping: Option<(Ipv4Address, u16, Vec<u8>)>,
    ping_count: u32,
    rx_count: u32,
    tx_count: u32,
}
impl Endpoint {
    fn new(ip: u32, id: u32, server: bool) -> Self {
        let mut nic = Nic { rx: VecDeque::new(), tx: VecDeque::new() };
        let mac = EthernetAddress([2, 0, (id >> 24) as u8, (id >> 16) as u8, (id >> 8) as u8, id as u8]);
        let mut config = Config::new(HardwareAddress::Ethernet(mac));
        config.random_seed = id as u64 + 1;
        let mut iface = Interface::new(config, &mut nic, Instant::from_millis(0));
        iface.update_ip_addrs(|addrs| { addrs.push(IpCidr::new(IpAddress::Ipv4(ipv4(ip)), 24)).unwrap(); });
        let mut sockets = SocketSet::new(Vec::new());
        let mut ping = icmp::Socket::new(
            icmp::PacketBuffer::new(vec![icmp::PacketMetadata::EMPTY; 4], vec![0; 2048]),
            icmp::PacketBuffer::new(vec![icmp::PacketMetadata::EMPTY; 4], vec![0; 2048]),
        );
        ping.bind(icmp::Endpoint::Ident(id as u16)).unwrap();
        let icmp = sockets.add(ping);
        let mut connection = tcp::Socket::new(tcp::SocketBuffer::new(vec![0; 4096]), tcp::SocketBuffer::new(vec![0; 4096]));
        connection.set_ack_delay(None);
        connection.set_timeout(Some(smoltcp::time::Duration::from_secs(3)));
        if server { connection.listen(8080).unwrap(); }
        let tcp = sockets.add(connection);
        Self { nic, iface, sockets, icmp, tcp, id: id as u16, server, pending: Vec::new(), reply: Vec::new(), ping_reply: Vec::new(), expected_ping: None, ping_count: 0, rx_count: 0, tx_count: 0 }
    }
    fn poll(&mut self, now: i64) {
        self.iface.poll(Instant::from_millis(now), &mut self.nic, &mut self.sockets);
        {
            let socket = self.sockets.get_mut::<icmp::Socket>(self.icmp);
            while socket.can_recv() {
                if let Ok((packet, address)) = socket.recv() {
                    if let Ok(p) = Icmpv4Packet::new_checked(packet) {
                        if let Ok(Icmpv4Repr::EchoReply { ident, seq_no, data }) = Icmpv4Repr::parse(&p, &smoltcp::phy::ChecksumCapabilities::default()) {
                            if ident == self.id && self.expected_ping.as_ref().map(|(ip, sequence, expected)| address == IpAddress::Ipv4(*ip) && seq_no == *sequence && data == expected.as_slice()).unwrap_or(false) {
                                self.ping_reply = data.to_vec();
                                self.ping_count += 1;
                            }
                        }
                    }
                }
            }
        }
        {
            let socket = self.sockets.get_mut::<tcp::Socket>(self.tcp);
            if socket.can_recv() {
                let mut buffer = [0; PAYLOAD_LIMIT];
                if let Ok(len) = socket.recv_slice(&mut buffer) {
                    if self.server { self.pending.extend_from_slice(&buffer[..len]); }
                    else { self.reply.extend_from_slice(&buffer[..len]); }
                }
            }
            if socket.can_send() && !self.pending.is_empty() {
                if let Ok(n) = socket.send_slice(&self.pending) { self.pending.drain(..n); }
            }
        }
        self.iface.poll(Instant::from_millis(now), &mut self.nic, &mut self.sockets);
        while let Some(frame) = self.nic.tx.pop_front() {
            self.tx_count += 1;
            unsafe { emit(0, frame.as_ptr(), frame.len()); }
        }
    }
}

struct Switch {
    ports: u32,
    fdb: BTreeMap<[u8; 6], u32>,
    rx_count: u32,
    tx_count: u32,
}
impl Switch {
    fn receive(&mut self, ingress: u32, frame: &[u8]) -> i32 {
        if ingress >= self.ports || frame.len() < 14 { return -1; }
        let dst: [u8; 6] = frame[..6].try_into().unwrap();
        let src: [u8; 6] = frame[6..12].try_into().unwrap();
        self.rx_count += 1;
        if src[0] & 1 == 0 {
            if self.fdb.len() >= 256 && !self.fdb.contains_key(&src) { return -2; }
            self.fdb.insert(src, ingress);
        }
        let known = if dst[0] & 1 == 0 { self.fdb.get(&dst).copied() } else { None };
        for port in 0..self.ports {
            if port != ingress && (known.is_none() || known == Some(port)) {
                self.tx_count += 1;
                unsafe { emit(port, frame.as_ptr(), frame.len()); }
            }
        }
        0
    }
}

enum Appliance { Host(Endpoint), Switch(Switch) }
thread_local! {
    static NODE: RefCell<Option<Appliance>> = const { RefCell::new(None) };
    static INPUT: RefCell<[u8; MTU]> = const { RefCell::new([0; MTU]) };
}
fn ipv4(n: u32) -> Ipv4Address { let b = n.to_be_bytes(); Ipv4Address::new(b[0], b[1], b[2], b[3]) }

#[no_mangle] pub extern "C" fn abi_version() -> u32 { 1 }
#[no_mangle] pub extern "C" fn init(role: u32, ip: u32, id: u32, ports: u32) -> i32 {
    if role > 2 || id == 0 || id > 65535 || ports == 0 || ports > 256 { return -1; }
    NODE.with(|s| *s.borrow_mut() = Some(if role == 1 {
        Appliance::Switch(Switch { ports, fdb: BTreeMap::new(), rx_count: 0, tx_count: 0 })
    } else { Appliance::Host(Endpoint::new(ip, id, role == 2)) }));
    0
}
#[no_mangle] pub extern "C" fn input_ptr() -> *mut u8 { INPUT.with(|s| s.borrow_mut().as_mut_ptr()) }
#[no_mangle] pub extern "C" fn receive(port: u32, len: usize) -> i32 {
    if len > MTU || len < 14 { return -1; }
    INPUT.with(|input| NODE.with(|state| match state.borrow_mut().as_mut() {
        Some(Appliance::Switch(s)) => s.receive(port, &input.borrow()[..len]),
        Some(Appliance::Host(h)) => {
            if port != 0 || h.nic.rx.len() >= QUEUE_LIMIT { return -2; }
            h.nic.rx.push_back(input.borrow()[..len].to_vec()); h.rx_count += 1; 0
        },
        None => -3,
    }))
}
#[no_mangle] pub extern "C" fn poll(now_ms: i64) {
    NODE.with(|s| if let Some(Appliance::Host(h)) = s.borrow_mut().as_mut() { h.poll(now_ms); });
}
#[no_mangle] pub extern "C" fn poll_delay(now_ms: i64) -> i32 {
    NODE.with(|s| match s.borrow_mut().as_mut() {
        Some(Appliance::Host(h)) => h.iface.poll_delay(Instant::from_millis(now_ms), &h.sockets).map(|d| d.total_millis().min(60000) as i32).unwrap_or(-1),
        _ => -1,
    })
}
#[no_mangle] pub extern "C" fn ping(ip: u32, sequence: u32, len: usize) -> i32 {
    if len > PAYLOAD_LIMIT { return -1; }
    NODE.with(|s| match s.borrow_mut().as_mut() {
        Some(Appliance::Host(h)) => {
            let data = INPUT.with(|input| input.borrow()[..len].to_vec());
            let repr = Icmpv4Repr::EchoRequest { ident: h.id, seq_no: sequence as u16, data: &data };
            let mut packet = vec![0; repr.buffer_len()];
            repr.emit(&mut Icmpv4Packet::new_unchecked(&mut packet), &smoltcp::phy::ChecksumCapabilities::default());
            let result = h.sockets.get_mut::<icmp::Socket>(h.icmp).send_slice(&packet, IpAddress::Ipv4(ipv4(ip)));
            if result.is_ok() { h.expected_ping = Some((ipv4(ip), sequence as u16, data)); 0 } else { -2 }
        },
        _ => -3,
    })
}
#[no_mangle] pub extern "C" fn connect(ip: u32, port: u32, len: usize) -> i32 {
    if len > PAYLOAD_LIMIT || port == 0 || port > 65535 { return -1; }
    NODE.with(|s| match s.borrow_mut().as_mut() {
        Some(Appliance::Host(h)) if !h.server => {
            let socket = h.sockets.get_mut::<tcp::Socket>(h.tcp);
            if socket.is_open() { return -2; }
            if socket.connect(h.iface.context(), (IpAddress::Ipv4(ipv4(ip)), port as u16), 49152).is_err() { return -3; }
            h.pending = INPUT.with(|input| input.borrow()[..len].to_vec()); h.reply.clear(); 0
        },
        _ => -4,
    })
}
#[no_mangle] pub extern "C" fn ping_count() -> u32 { NODE.with(|s| match s.borrow().as_ref() { Some(Appliance::Host(h)) => h.ping_count, _ => 0 }) }
#[no_mangle] pub extern "C" fn reply_len() -> usize { NODE.with(|s| match s.borrow().as_ref() { Some(Appliance::Host(h)) => h.reply.len(), _ => 0 }) }
#[no_mangle] pub extern "C" fn reply_ptr() -> *const u8 { NODE.with(|s| match s.borrow().as_ref() { Some(Appliance::Host(h)) => h.reply.as_ptr(), _ => std::ptr::null() }) }
#[no_mangle] pub extern "C" fn ping_data_len() -> usize { NODE.with(|s| match s.borrow().as_ref() { Some(Appliance::Host(h)) => h.ping_reply.len(), _ => 0 }) }
#[no_mangle] pub extern "C" fn ping_data_ptr() -> *const u8 { NODE.with(|s| match s.borrow().as_ref() { Some(Appliance::Host(h)) => h.ping_reply.as_ptr(), _ => std::ptr::null() }) }
#[no_mangle] pub extern "C" fn fdb_size() -> usize { NODE.with(|s| match s.borrow().as_ref() { Some(Appliance::Switch(h)) => h.fdb.len(), _ => 0 }) }
#[no_mangle] pub extern "C" fn rx_count() -> u32 { NODE.with(|s| match s.borrow().as_ref() { Some(Appliance::Host(h)) => h.rx_count, Some(Appliance::Switch(h)) => h.rx_count, _ => 0 }) }
#[no_mangle] pub extern "C" fn tx_count() -> u32 { NODE.with(|s| match s.borrow().as_ref() { Some(Appliance::Host(h)) => h.tx_count, Some(Appliance::Switch(h)) => h.tx_count, _ => 0 }) }
#[no_mangle] pub extern "C" fn spin() { loop { std::hint::black_box(1); } }
#[no_mangle] pub extern "C" fn crash() { std::arch::wasm32::unreachable() }
