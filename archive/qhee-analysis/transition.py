"""Build the bounded emulator-only diagnostic terminal transition."""
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile

SOURCE=Path(__file__).with_name('emulator')/'el2_diag_transition.S'
START=0x800402b0
END=0x8004032c
ORIGINAL=b''.join(struct.pack('<I',0xaa1f03e0|i) for i in range(1,31))+struct.pack('<I',0xd69f03e0)


def build(variant='diagnostic'):
    if variant not in ('diagnostic','xbl-prefix','diagnostic-masked','xbl-prefix-masked'):raise ValueError('Unknown terminal transition variant')
    with tempfile.TemporaryDirectory(prefix='nio-el2-transition-') as tmp:
        obj=Path(tmp)/'transition.o';binary=Path(tmp)/'transition.bin'
        subprocess.run(['aarch64-linux-gnu-as','--defsym',f'XBL_PREFIX={int(variant.startswith("xbl-prefix"))}','--defsym',f'MASK_ENTRY={int(variant.endswith("-masked"))}','-o',str(obj),str(SOURCE)],check=True)
        subprocess.run(['aarch64-linux-gnu-objcopy','-O','binary','-j','.text',str(obj),str(binary)],check=True)
        code=binary.read_bytes()
    if len(code)!=END-START or code[-4:]!=struct.pack('<I',0xd69f03e0):
        raise ValueError('Diagnostic transition must fit exactly and preserve ERET address')
    return code,{'address':hex(START),'end_exclusive':hex(END),
        'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'code_sha256':hashlib.sha256(code).hexdigest(),
        'clean_ranges':[['0x80040000','0x8028b000'],['0x9fc00000','0x9ff00000'] if variant.startswith('xbl-prefix') else ['0x90000000','0x90001000']],
        'mask_daif_before_clean':variant.endswith('-masked'),'sctlr_clear_mask':'0x1005','entry_constraints':('Synthetic CPU0 cold AArch64 path; DAIF masked by first instruction; identity Normal-memory mappings; no stack access' if variant.endswith('-masked') else 'Synthetic CPU0 cold AArch64 path; DAIF masked; identity Normal-memory mappings; no stack access'),
        'limitations':'TCG does not model physical dirty caches/system-cache coherency. No full boot-chain allocation clean, DTB, timer/GIC/PSCI takeover, complete UEFI/ABL execution or physical handoff validation.'}
