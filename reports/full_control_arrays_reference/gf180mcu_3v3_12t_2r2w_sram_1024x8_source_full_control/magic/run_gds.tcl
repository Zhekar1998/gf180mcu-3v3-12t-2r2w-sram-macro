crashbackups stop
drc off
set topcell $::env(MAGIC_TOPCELL)
load $topcell
select top cell
expand
gds write ../layout/$topcell.gds
quit -noprompt
