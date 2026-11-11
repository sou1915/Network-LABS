"""Allowlisted, dated desktop inspection snapshots; never execute backend work."""
import hashlib
import json


def revision(spec):
    return hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()


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
    for key in ('port_security','dhcp_snooping','arp_inspection','ip_source_guard'):
        policy=data.get(key)
        if not isinstance(policy,dict):continue
        policies.append({'module':key,'verified':policy.get('policy_verified') if type(policy.get('policy_verified')) is bool else None,
                         'counters':rows(policy.get('counters'),('rule','packets','bytes'))})
    return {'captured_at':getattr(window,'web_inspection_time',None),
            'links':rows(data.get('links'),('ifname','operstate','mtu','address')),
            'routes':rows(data.get('routes'),('dst','gateway','dev','protocol','scope','type')),
            'policies':policies}
