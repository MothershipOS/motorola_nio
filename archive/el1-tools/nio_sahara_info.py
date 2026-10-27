#!/usr/bin/env python3
"""Bounded Sahara command-mode identification only; no loader/storage writes.

Wire protocol reference: Bjoern Kerler edl, GPLv3, sahara.py/sahara_defs.py,
commit 1cda1a616748d608667b2d13b73a28d3197ceb45. Independent bounded client.
"""
import argparse
import datetime
import json
from pathlib import Path
import struct
import time
import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(exist_ok=True, parents=True)
    transcript=[]
    def record(direction,data):
        transcript.append({'direction':direction,'hex':data.hex()})
        (args.out/'sahara-transcript.json').write_text(json.dumps(transcript,indent=2)+'\n')
    # Do not discard an initial hello queued by the serial kernel driver.
    port=serial.Serial(port=None,baudrate=115200,timeout=2,write_timeout=2)
    port._reset_input_buffer=lambda:None
    port.port=args.port;port.open()
    def send(*words):
        data=struct.pack('<'+'I'*len(words),*words);record('host',data);port.write(data)
    def receive(length):
        data=port.read(length);record('device',data)
        if len(data)!=length:raise RuntimeError(f'Short Sahara response: wanted {length}, got {len(data)}')
        return data
    def packet():
        header=receive(8);cmd,length=struct.unpack('<II',header)
        if not 8<=length<=4096:raise RuntimeError(f'Unexpected Sahara packet length {length}')
        return cmd,header+receive(length-8)
    facts={'scope':'Command mode plus bounded read-only identification; no loader upload, memory or storage write',
           'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'port':args.port}
    try:
        initial=port.read(48);record('device',initial)
        if len(initial)!=48 or struct.unpack_from('<I',initial)[0]!=1:
            send(0xc,12,3)
            cmd,initial=packet()
            if cmd!=1 or len(initial)!=48:raise RuntimeError('Expected Sahara HELLO after command-mode switch')
        words=struct.unpack('<12I',initial)
        version=words[2];facts['hello_words']=list(words)
        if version not in (1,2,3):raise RuntimeError(f'Unsupported Sahara version {version}')
        send(2,48,version,1,0,3,0,0,0,0,0,0)
        cmd,data=packet()
        if cmd!=0xb:raise RuntimeError(f'Expected COMMAND_READY, got {cmd:#x}: {data.hex()}')
        facts['responses']={}
        for command,name in [(1,'serial'),(2,'hwid'),(3,'public_key_hash'),(7,'sbl_version'),(8,'command_list'),(6,'debug_data')]:
            send(0xd,12,command);cmd,data=packet()
            if cmd!=0xe or len(data)!=16:raise RuntimeError(f'Expected EXECUTE_RSP for {name}, got {cmd:#x}: {data.hex()}')
            _,_,echo,size=struct.unpack('<4I',data)
            if echo!=command or size>65536:raise RuntimeError(f'Unexpected response for {name}')
            send(0xf,12,command);body=receive(size)
            facts['responses'][name]={'hex':body.hex(),'bytes':len(body)}
            if name in ('serial','hwid','sbl_version'):facts['responses'][name]['little_endian_value']=hex(int.from_bytes(body,'little'))
            (args.out/('sahara-'+name+'.bin')).write_bytes(body)
            print(name,facts['responses'][name],flush=True)
    except Exception as error:
        facts['error']=str(error);print('Sahara identification:',error,flush=True)
    finally:
        port.close();(args.out/'sahara-info.json').write_text(json.dumps(facts,indent=2)+'\n')
    if 'error' in facts:raise SystemExit(1)


if __name__=='__main__':main()
