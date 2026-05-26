crashbackups stop
drc off
set topcell $::env(MAGIC_TOPCELL)
load $topcell
select top cell
gds write ../layout/$topcell.gds
quit -noprompt
