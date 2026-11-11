"""Allowlisted, dated desktop inspection snapshots; never execute backend work."""
import hashlib
import json


def revision(spec):
    return hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def count(value):
    return value if type(value) is int and value>=0 else None


def firewall_snapshot(value):
    """Expose only managed IPv4 table counters, never raw nft expressions."""
    if not isinstance(value,dict):return None
    from .firewall import TABLE
    chains=[];counters=[]
    entries=value.get('nftables')
    for entry in entries if isinstance(entries,list) else []:
        if not isinstance(entry,dict):continue
        chain=entry.get('chain',{})
        if isinstance(chain,dict) and chain.get('family')=='ip' and chain.get('table')==TABLE:
            chains.append({key:chain.get(key) if isinstance(chain.get(key),str) else None for key in ('name','hook','policy')})
        rule=entry.get('rule',{})
        if not isinstance(rule,dict) or rule.get('family')!='ip' or rule.get('table')!=TABLE:continue
        expressions=rule.get('expr')
        for expr in expressions if isinstance(expressions,list) else []:
            metric=expr.get('counter') if isinstance(expr,dict) else None
            if not isinstance(metric,dict):continue
            counters.append({'chain':rule.get('chain') if isinstance(rule.get('chain'),str) else None,
                             'rule':rule.get('comment') if isinstance(rule.get('comment'),str) else None,
                             'packets':count(metric.get('packets')),'bytes':count(metric.get('bytes'))})
    return {'chains':chains,'counters':counters}


def snapshot(window,spec,name):
    response=getattr(window,'last_response',None) or {}
    if (getattr(window,'pending',None) or not response.get('ok') or response.get('action')!='inspect'
            or response.get('lab')!=spec['name'] or getattr(window,'view_lab',None)!=spec['name']
            or getattr(window,'web_inspection_revision',None)!=revision(spec)):
        return None
    data=response.get('data',{})
    if data.get('name')!=name:return None
    def rows(values,fields):
        return [{key:value for key,value in row.items() if key in fields and type(value) in (str,int,bool,type(None))}
                for row in (values if isinstance(values,list) else []) if isinstance(row,dict)]
    policies=[]
    for key in ('dhcp_snooping','arp_inspection','ip_source_guard'):
        policy=data.get(key)
        if not isinstance(policy,dict):continue
        policies.append({'module':key,'verified':policy.get('policy_verified') if type(policy.get('policy_verified')) is bool else None,
                         'counters':rows(policy.get('counters'),('rule','packets','bytes'))})
    mac=data.get('port_security')
    if isinstance(mac,dict):
        counters=[]
        ports=mac.get('ports')
        for port,metrics in ports.items() if isinstance(ports,dict) else []:
            if not isinstance(port,str) or not isinstance(metrics,dict):continue
            for action,prefix in (('allow','accepted_'),('deny','dropped_')):
                counters.append({'rule':action+':'+port,'packets':count(metrics.get(prefix+'packets')),'bytes':count(metrics.get(prefix+'bytes'))})
        verified=mac.get('fingerprint_matches') if mac.get('available') is True else None
        policies.insert(0,{'module':'port_security','verified':verified if type(verified) is bool else None,'counters':counters})
    for policy in policies:
        for counter in policy['counters']:
            for field in ('packets','bytes'):
                if field in counter:counter[field]=count(counter[field])
    return {'firewall':firewall_snapshot(data.get('firewall')),'captured_at':getattr(window,'web_inspection_time',None),
            'links':rows(data.get('links'),('ifname','operstate','mtu','address')),
            'routes':rows(data.get('routes'),('dst','gateway','dev','protocol','scope','type')),
            'policies':policies}
