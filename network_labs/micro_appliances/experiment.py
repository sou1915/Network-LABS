"""Functional probe and reproducible measurements of the optional prototype."""
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys
import time
from .runtime import Fabric, make_lab
from .packets import describe


def memory_sample():
    """Linux resident/proportional memory; virtual address reservations are separate."""
    out={}
    try:
        for line in Path('/proc/self/smaps_rollup').read_text().splitlines():
            fields=line.split()
            if fields and fields[0] in ('Rss:','Pss:','Private_Clean:','Private_Dirty:'):
                out[fields[0][:-1].lower()+'_bytes']=int(fields[1])*1024
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith(('VmSize:','Threads:')):
                key,value,*_=line.split()
                out['virtual_address_bytes' if key=='VmSize:' else 'threads']=int(value)*(1024 if key=='VmSize:' else 1)
    except OSError:
        out['available']=False
    return out


def echo_ping(fabric,source,target,payload=b'Network-LABS ICMP',attempts=3):
    node=fabric.nodes[source]
    for attempt in range(1,attempts+1):
        count=node.ping(target,payload)
        if fabric.run_until(lambda:node.call('ping_count')>count,1000):
            return {'ok':node.reply('icmp')==payload,'attempts':attempt,'payload_hex':node.reply('icmp').hex()}
    return {'ok':False,'attempts':attempts,'payload_hex':''}


def functional_demo():
    fabric=make_lab()
    start=time.perf_counter();cpu=time.process_time()
    ping=echo_ping(fabric,'PC1','10.0.0.2')
    payload=b'Hello from an independent Wasm TCP stack!'
    fabric.nodes['PC1'].connect('10.0.0.2',8080,payload)
    tcp=fabric.run_until(lambda:fabric.nodes['PC1'].reply()==payload)
    frames=[describe(x) for x in fabric.frames]
    valid=all(x.get('checksum_ok',True) and x.get('ip_checksum_ok',True) for x in frames)
    flags=[x.get('flags',[]) for x in frames if x['protocol']=='TCP']
    handshake=any(x==['SYN'] for x in flags) and any(x==['SYN','ACK'] for x in flags) and any(x==['ACK'] for x in flags)
    report={'prototype':'Wasm micro-appliances / smoltcp; no guest OS',
            'ping':ping,'tcp_echo_ok':tcp,'tcp_payload_hex':fabric.nodes['PC1'].reply().hex(),
            'tcp_handshake_observed':handshake,'packet_checksums_ok':valid,
            'wall_seconds':time.perf_counter()-start,'cpu_seconds':time.process_time()-cpu,
            'process_memory':memory_sample(),'runtime':fabric.stats(),'frames':frames}
    report['ok']=ping['ok'] and tcp and valid and handshake
    return fabric,report


def benchmark_worker(hosts):
    baseline=memory_sample();start=time.perf_counter();cpu=time.process_time()
    fabric=Fabric(capture=False)
    compiled=memory_sample();compile_seconds=time.perf_counter()-start
    build=time.perf_counter()
    fabric.add('SW1',1,'0.0.0.0',65535,hosts)
    for index in range(1,hosts+1):
        fabric.add('PC'+str(index),2 if index==hosts else 0,'10.0.0.'+str(index),index)
        fabric.connect('PC'+str(index),0,'SW1',index-1)
    instantiated=memory_sample();instantiate_seconds=time.perf_counter()-build
    traffic=time.perf_counter();traffic_cpu=time.process_time()
    results=[echo_ping(fabric,'PC'+str(i),'10.0.0.'+str(hosts),b'benchmark') for i in range(1,hosts)]
    payload=b'TCP benchmark'
    fabric.nodes['PC1'].connect('10.0.0.'+str(hosts),8080,payload)
    tcp=fabric.run_until(lambda:fabric.nodes['PC1'].reply()==payload)
    traffic_cpu=time.process_time()-traffic_cpu;traffic_seconds=time.perf_counter()-traffic
    after=memory_sample()
    paused_cpu=time.process_time();paused_wall=time.perf_counter();time.sleep(.2)
    paused_percent=100*(time.process_time()-paused_cpu)/(time.perf_counter()-paused_wall)
    artifact=Path(__file__).with_name('device.wasm')
    report={'hosts':hosts,'switches':1,'instances':hosts+1,'ok':all(x['ok'] for x in results) and tcp,
            'ping_success':sum(x['ok'] for x in results),'ping_total':len(results),'tcp_echo_ok':tcp,
            'compile_seconds':compile_seconds,'instantiate_seconds':instantiate_seconds,
            'traffic_wall_seconds':traffic_seconds,'traffic_cpu_seconds':traffic_cpu,
            'total_wall_seconds':time.perf_counter()-start,'total_cpu_seconds':time.process_time()-cpu,
            'paused_idle_cpu_percent':paused_percent,
            'memory_before_engine':baseline,'memory_after_compile':compiled,
            'memory_after_instantiation':instantiated,'memory_after_traffic':after,
            'runtime':fabric.stats(),
            'environment':{'python':sys.version.split()[0],'wasmtime':version('wasmtime'),
                           'machine':platform.machine(),'system':platform.system(),
                           'guest_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}}
    if 'rss_bytes' in after and 'rss_bytes' in compiled:
        report['resident_delta_after_compile_bytes']=after['rss_bytes']-compiled['rss_bytes']
    fabric.close()
    return report


def isolation_demo():
    from .runtime import ApplianceFault, MEMORY_LIMIT
    f=make_lab(3)
    a,b=f.nodes['PC1'],f.nodes['PC2']
    original=bytes(b.memory.read(b.store,b.input_pointer,b.input_pointer+8))
    a.write_input(b'ISOLATED')
    separate=bytes(b.memory.read(b.store,b.input_pointer,b.input_pointer+8))==original
    try:
        a.memory.grow(a.store,MEMORY_LIMIT//65536)
        limited=False
    except Exception:
        limited=True
    before=time.perf_counter()
    try:a.call('spin')
    except ApplianceFault:pass
    interrupted=bool(a.fault);elapsed=time.perf_counter()-before
    # PC2 can still exchange traffic with PC3 through the unaffected switch.
    survives=echo_ping(f,'PC2','10.0.0.3')['ok']
    result={'separate_linear_memory':separate,'memory_growth_limited':limited,
            'infinite_loop_interrupted':interrupted,'interruption_wall_seconds':elapsed,
            'other_nodes_still_communicate':survives,'faulted_node':'PC1','hardware_vm':False}
    result['ok']=separate and limited and interrupted and survives
    f.close();return result
