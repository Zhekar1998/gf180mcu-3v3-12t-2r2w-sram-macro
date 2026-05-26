crashbackups stop
drc off
set topcell $::env(MAGIC_TOPCELL)
load $topcell
select top cell
expand
extract style ngspice()
extract unique
extract path $::env(EXT_DIR)
extract no all
extract all
ext2sim labels on
ext2sim -p $::env(EXT_DIR) $topcell
ext2spice lvs
ext2spice blackbox on
ext2spice -p $::env(EXT_DIR) -o $::env(PEX_LVS_SPICE)
quit -noprompt
