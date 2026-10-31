"""Bounded-memory QA reader for LTspice's *real, forward binary* RAW only.

Never used to claim arbitrary RAW/step/complex compatibility in the product.
It verifies file length and final time even when an MCP parser's byte cap is
smaller than a high-frequency switching capture. Scalars come from .meas logs.
"""
from pathlib import Path
import re
import numpy as np


def real_forward_raw(path):
    path=Path(path)
    with path.open('rb') as stream:
        data=stream.read(65536)
    marker='Binary:\n'.encode('utf-16-le')
    where=data.find(marker)
    if where<0:raise ValueError('Only UTF16 real binary RAW is supported by this QA helper')
    offset=where+len(marker)
    header=data[:where].decode('utf-16-le')
    flags=re.search(r'^Flags:\s*(.*)$',header,re.M).group(1).strip().split()
    if 'real' not in flags or 'forward' not in flags or 'double' in flags or 'FastAccess' in flags:
        raise ValueError('Unexpected RAW format: '+str(flags))
    count=int(re.search(r'No\. Variables:\s*(\d+)',header).group(1))
    points=int(re.search(r'No\. Points:\s*(\d+)',header).group(1))
    names=[m.group(1) for m in re.finditer(r'^\s*\d+\s+(\S+)\s+\S+\s*$',header.rsplit('Variables:',1)[1],re.M)]
    dtype=np.dtype([('time','<f8'),('values','<f4',(count-1,))])
    if path.stat().st_size!=offset+points*dtype.itemsize or len(names)!=count:
        raise ValueError('RAW length/header mismatch or partial capture')
    records=np.memmap(path,mode='r',dtype=dtype,offset=offset,shape=(points,))
    return records,{name.casefold():i-1 for i,name in enumerate(names) if i}


def log_measurements(path):
    text=Path(path).read_text(encoding='utf-8',errors='replace')
    if 'Total elapsed time:' not in text or 'timestep too small' in text.lower() or 'Measurement "' in text:
        raise ValueError('Incomplete or failed simulation log')
    measured={m.group(1):float(m.group(2)) for m in re.finditer(r'^(\w+):\s+.*?=([-+\d.eE]+)\s+FROM',text,re.M)}
    return measured,text
