"""A virtual Ethernet fabric joining independent, bounded Wasm instances.

The host transports bytes and schedules clocks. It does NOT answer ARP/ICMP,
terminate TCP, learn MAC addresses or calculate an end-to-end reachability result.
No WASI, host socket, subprocess, filesystem or clock imports are given to guests.
"""
from dataclasses import dataclass
import hashlib
import heapq
from ipaddress import IPv4Address
from pathlib import Path
import struct

FRAME_LIMIT = 1514
MEMORY_LIMIT = 2 * 1024 * 1024
FUEL_PER_CALL = 2_000_000
EVENT_LIMIT = 100_000
CAPTURE_LIMIT = 20_000

class DependencyMissing(RuntimeError):
    pass

class ApplianceFault(RuntimeError):
    pass

@dataclass(frozen=True)
class Frame:
    time_ms: int
    source: str
    source_port: int
    destination: str
    destination_port: int
    data: bytes

class Appliance:
    def __init__(self, runtime, name, role, address, identity, ports):
        w = runtime.wasm
        self.runtime, self.name, self.role = runtime, name, role
        self.address, self.ports, self.identity, self.fault = address, ports, identity, None
        self.ping_sequence = 0
        self.store = w.Store(runtime.engine)
        self.store.set_limits(memory_size=MEMORY_LIMIT, instances=1, memories=1, tables=2, table_elements=4096)
        self.store.set_fuel(FUEL_PER_CALL)
        linker = w.Linker(runtime.engine)
        def emit(caller, port, pointer, length):
            if not 0 <= port < ports or not 14 <= length <= FRAME_LIMIT:
                raise w.Trap('Invalid virtual NIC output.')
            memory = caller.get('memory')
            if pointer < 0 or pointer + length > memory.data_len(caller):
                raise w.Trap('Guest frame is outside its linear memory.')
            runtime.transmit(self.name, port, bytes(memory.read(caller, pointer, pointer + length)))
        linker.define_func('lab', 'emit', w.FuncType([w.ValType.i32()] * 3, []), emit, access_caller=True)
        self.instance = linker.instantiate(self.store, runtime.module)
        self.exports = self.instance.exports(self.store)
        self.memory = self.exports['memory']
        if self.call('abi_version') != 1:
            raise ValueError('Unsupported guest ABI.')
        self.call('init', role, int(IPv4Address(address)), identity, ports)
        self.input_pointer = self.call('input_ptr')

    def call(self, function, *args):
        if self.fault:
            raise ApplianceFault(self.name + ': appliance is quarantined; reset the lab.')
        self.store.set_fuel(FUEL_PER_CALL)
        try:
            result = self.exports[function](self.store, *args)
        except Exception as error:
            self.fault = str(error)[:1000]
            raise ApplianceFault(self.name + ': ' + self.fault) from error
        if isinstance(result, int) and result < 0 and function not in ('poll_delay',):
            raise ValueError(f'{self.name}: {function} rejected (code {result}).')
        return result

    def write_input(self, data, limit=FRAME_LIMIT):
        if len(data) > limit:
            raise ValueError('Input exceeds the appliance buffer.')
        self.memory.write(self.store, data, self.input_pointer)

    def receive(self, port, frame):
        self.write_input(frame)
        self.call('receive', port, len(frame))

    def ping(self, target, payload=b'Network-LABS ping', sequence=None):
        if self.role == 1:
            raise ValueError('This switch has no IP endpoint.')
        self.write_input(payload, 512)
        if sequence is None:
            self.ping_sequence = (self.ping_sequence + 1) % 65536
            sequence = self.ping_sequence
        before = self.call('ping_count')
        self.call('ping', int(IPv4Address(target)), sequence, len(payload))
        self.runtime.wake(self.name)
        return before

    def connect(self, target, port=8080, payload=b'Network-LABS TCP echo'):
        if self.role != 0:
            raise ValueError('Select a client endpoint.')
        self.write_input(payload, 512)
        self.call('connect', int(IPv4Address(target)), port, len(payload))
        self.runtime.wake(self.name)

    def reply(self, protocol='tcp'):
        prefix = 'ping_data' if protocol == 'icmp' else 'reply'
        length = self.call(prefix + '_len')
        pointer = self.call(prefix + '_ptr')
        if not 0 <= length <= 8192 or not 0 <= pointer <= pointer + length <= self.memory.data_len(self.store):
            raise ApplianceFault('Invalid guest reply buffer.')
        return bytes(self.memory.read(self.store, pointer, pointer + length))

    def stats(self):
        return {'name':self.name, 'role':('client','switch','server')[self.role],
                'address':self.address, 'fault':self.fault,
                'linear_memory_bytes':self.memory.data_len(self.store),
                'rx_frames':self.call('rx_count') if not self.fault else None,
                'tx_frames':self.call('tx_count') if not self.fault else None,
                'learned_macs':self.call('fdb_size') if self.role == 1 and not self.fault else None}

class Fabric:
    def __init__(self, artifact=None, capture=True):
        try:
            import wasmtime
        except ImportError as error:
            raise DependencyMissing('Prototype facultatif : installer experiments/micro_appliances/requirements.txt dans un venv.') from error
        self.wasm = wasmtime
        config = wasmtime.Config()
        config.consume_fuel = True
        config.parallel_compilation = False
        self.engine = wasmtime.Engine(config)
        artifact = Path(artifact or Path(__file__).with_name('device.wasm'))
        raw = artifact.read_bytes()
        if artifact.name == 'device.wasm' and artifact.with_suffix('.wasm.sha256').exists():
            expected = artifact.with_suffix('.wasm.sha256').read_text().split()[0]
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError('Guest artifact checksum mismatch. Rebuild it from source.')
        self.module = wasmtime.Module(self.engine, raw)
        self.nodes, self.links, self.queue = {}, {}, []
        self.now_ms = self.serial = self.processed = self.dropped_captures = 0
        self.timer_generation, self.frames, self.faults = {}, [], []
        self.capture = capture
        self.disabled = set()

    def add(self, name, role=0, address='10.0.0.1', identity=1, ports=1):
        if name in self.nodes or not name or not 1 <= ports <= 256 or role not in (0,1,2):
            raise ValueError('Invalid appliance identity/role/ports.')
        if not 1 <= identity <= 65535:
            raise ValueError('Identity must fit 1..65535.')
        if role != 1 and ports != 1:raise ValueError('Endpoint appliances have one NIC in this prototype.')
        if role != 1 and any(n.role != 1 and n.identity == identity for n in self.nodes.values()):raise ValueError('Duplicate MAC identity.')
        if any(n.address == address for n in self.nodes.values() if n.role != 1) and role != 1:
            raise ValueError('Duplicate IPv4 endpoint.')
        node = Appliance(self, name, role, address, identity, ports)
        self.nodes[name] = node
        return node

    def connect(self, a, ap, b, bp):
        for name, port in ((a,ap),(b,bp)):
            if name not in self.nodes or not 0 <= port < self.nodes[name].ports:
                raise ValueError('Unknown appliance or virtual port.')
            if (name,port) in self.links:
                raise ValueError('Port is already connected.')
        if a == b:
            raise ValueError('Self links are not supported in this prototype.')
        self.links[a,ap] = (b,bp)
        self.links[b,bp] = (a,ap)

    def set_link_enabled(self, node, port, enabled):
        if (node,port) not in self.links:raise ValueError('Port is not connected.')
        ends={(node,port),self.links[node,port]}
        if enabled:self.disabled.difference_update(ends)
        else:self.disabled.update(ends)

    def enqueue(self, time_ms, kind, node, port=0, data=None):
        if len(self.queue) >= 8192:
            raise ApplianceFault('Virtual fabric queue limit reached.')
        self.serial += 1
        heapq.heappush(self.queue, (time_ms,self.serial,kind,node,port,data))

    def transmit(self, source, port, data):
        peer = self.links.get((source,port))
        if peer is None or (source,port) in self.disabled or peer in self.disabled:
            return
        destination, dp = peer
        if self.capture:
            if len(self.frames) < CAPTURE_LIMIT:
                self.frames.append(Frame(self.now_ms,source,port,destination,dp,data))
            else:
                self.dropped_captures += 1
        self.enqueue(self.now_ms + 1, 'frame', destination, dp, data)

    def wake(self, name):
        node = self.nodes[name]
        if node.fault:
            return
        try:
            node.call('poll', self.now_ms)
            delay = node.call('poll_delay', self.now_ms)
        except ApplianceFault as error:
            self.faults.append(str(error))
            return
        generation = self.timer_generation.get(name,0) + 1
        self.timer_generation[name] = generation
        if delay >= 0:
            self.enqueue(self.now_ms + max(1,delay), 'timer', name, data=generation)

    def run_until(self, predicate, timeout_ms=5000, max_events=EVENT_LIMIT):
        deadline = self.now_ms + timeout_ms
        count = 0
        while not predicate():
            if not self.queue or self.queue[0][0] > deadline:
                self.now_ms = deadline
                return False
            if count >= max_events:
                raise ApplianceFault('Virtual event budget exhausted (possible network loop).')
            when,_,kind,name,port,data = heapq.heappop(self.queue)
            self.now_ms = when
            count += 1; self.processed += 1
            node = self.nodes[name]
            if node.fault:
                continue
            if kind == 'timer' and self.timer_generation.get(name) != data:
                continue
            try:
                if kind == 'frame':
                    if (name,port) in self.disabled:continue
                    node.receive(port,data)
                self.wake(name)
            except ApplianceFault as error:
                self.faults.append(str(error))
        return True

    def write_pcap(self, path):
        # Capture all connected-port egress observations. No packet synthesis.
        with Path(path).open('wb') as stream:
            stream.write(struct.pack('<IHHIIII',0xa1b2c3d4,2,4,0,0,65535,1))
            for frame in self.frames:
                stream.write(struct.pack('<IIII',frame.time_ms // 1000,(frame.time_ms % 1000)*1000,len(frame.data),len(frame.data)))
                stream.write(frame.data)

    def close(self):
        # Explicitly release Store callbacks and their references to this fabric.
        for node in self.nodes.values():node.store.close()
        self.nodes.clear();self.links.clear();self.queue.clear();self.frames.clear();self.disabled.clear()
        self.module.close();self.engine.close()

    def stats(self):
        nodes = [n.stats() for n in self.nodes.values()]
        return {'virtual_time_ms':self.now_ms, 'events_processed':self.processed,
                'capture_frames':len(self.frames), 'capture_drops':self.dropped_captures,
                'linear_memory_bytes':sum(n['linear_memory_bytes'] for n in nodes),
                'faults':list(self.faults), 'nodes':nodes}


def make_lab(hosts=2, capture=True):
    if not 2 <= hosts <= 254:
        raise ValueError('Prototype: 2..254 endpoints on one /24 LAN.')
    fabric = Fabric(capture=capture)
    fabric.add('SW1',1,'0.0.0.0',65535,hosts)
    for index in range(1,hosts+1):
        fabric.add('PC'+str(index),2 if index == hosts else 0,'10.0.0.'+str(index),index)
        fabric.connect('PC'+str(index),0,'SW1',index-1)
    return fabric
