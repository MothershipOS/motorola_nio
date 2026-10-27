/* Link the C shim into QHEE's code cave. _stub (.text.stub) must be first so the
 * handoff branch (b _stub) lands on it; the C policy (shim_decide) follows. The base
 * address is supplied with -Ttext (the cave VA), so this script only fixes ordering.
 * Flat binary (objcopy -O binary .text); no data/bss expected (leaf, register-only). */
SECTIONS
{
  .text : {
    *(.text.stub)
    *(.text .text.*)
    *(.rodata .rodata.*)
  }
  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
