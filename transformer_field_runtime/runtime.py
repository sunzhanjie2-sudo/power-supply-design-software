from __future__ import annotations
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import struct
import subprocess
import time

from .storage import app_home,read,sha,write


def prepare_solver(elmer_home):
    root=Path(elmer_home).resolve();source=root/'bin/ElmerSolver.exe';source_sha=sha(source)
    data=bytearray(source.read_bytes())
    if data[:2]!=b'MZ':raise ValueError('ElmerSolver不是Windows PE文件。')
    pe=struct.unpack_from('<I',data,0x3c)[0];optional=pe+24
    if data[pe:pe+4]!=b'PE\0\0' or struct.unpack_from('<H',data,optional)[0]!=0x20b:
        raise ValueError('首版需要Windows x64 Elmer。')
    reserve=struct.unpack_from('<Q',data,optional+72)[0]
    if reserve>=128*1024**2:return source,dict(path=str(source),sha256=source_sha,stack_reserve_bytes=reserve)
    folder=app_home()/'data/runtime'/source_sha[:16]
    target=folder/'ElmerSolver.exe';provenance=folder/'provenance.json'
    if target.is_file() and provenance.is_file():
        previous=read(provenance)
        if previous['source_sha256']==source_sha and previous['sha256']==sha(target):return target,previous
    folder.mkdir(parents=True,exist_ok=True)
    struct.pack_into('<Q',data,optional+72,128*1024**2)
    struct.pack_into('<I',data,optional+64,0);target.write_bytes(data)
    checksum=ctypes.WinDLL('imagehlp').MapFileAndCheckSumW
    checksum.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(wintypes.DWORD),ctypes.POINTER(wintypes.DWORD)]
    checksum.restype=wintypes.DWORD
    header=wintypes.DWORD();computed=wintypes.DWORD()
    if checksum(str(target),ctypes.byref(header),ctypes.byref(computed))!=0:raise RuntimeError('无法校验Elmer启动副本。')
    struct.pack_into('<I',data,optional+64,computed.value);target.write_bytes(data)
    provenance_data=dict(path=str(target),source_path=str(source),source_sha256=source_sha,sha256=sha(target),
                         stack_reserve_before_bytes=reserve,stack_reserve_bytes=128*1024**2,
                         change='PE stack reserve and checksum only; code and installed executable unchanged')
    write(provenance,provenance_data)
    return target,provenance_data


def environment(elmer_home):
    root=Path(elmer_home).resolve();env=os.environ.copy()
    env.update(PYTHONUTF8='1',OMP_NUM_THREADS='1',ELMER_HOME=str(root),
               ELMER_LIB=str(root/'share/elmersolver/lib'),ELMERGUI_HOME=str(root/'share/ElmerGUI'))
    env['PATH']=os.pathsep.join([str(root/'bin'),str(root/'lib'),env.get('PATH','')])
    return env


def run_logged(arguments,directory,log_name,elmer_home,timeout):
    directory=Path(directory);started=time.monotonic()
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    old=ctypes.create_unicode_buffer(32768);kernel.GetDllDirectoryW(len(old),old)
    with (directory/log_name).open('wb') as log:
        try:
            kernel.SetDllDirectoryW(None)
            process=subprocess.Popen([str(a) for a in arguments],cwd=directory,env=environment(elmer_home),
                                     stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        finally:kernel.SetDllDirectoryW(old.value or None)
        try:code=process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill.exe','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            raise RuntimeError('求解超过设定时间；本次子进程已停止。')
    text=(directory/log_name).read_text(encoding='utf-8',errors='replace')
    if code:raise RuntimeError(f'{Path(arguments[0]).name}退出码{code}；请查看{log_name}。')
    return text,time.monotonic()-started
