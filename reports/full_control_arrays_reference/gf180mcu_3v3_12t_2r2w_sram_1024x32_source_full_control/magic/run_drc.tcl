crashbackups stop
set topcell $::env(MAGIC_TOPCELL)
load $topcell
select top cell
expand
drc on
drc style drc(full)
drc check
drc count total
drc listall why
quit -noprompt
