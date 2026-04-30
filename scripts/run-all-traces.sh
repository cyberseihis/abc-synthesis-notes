#!/usr/bin/env bash
# Reproduces every trace embedded in abc-synthesis-walkthroughs.md.
# Requires: ABC built with patches/abc-trace.diff applied.
set -e
ABC=${ABC:-/work/abc/abc}
EX=$(cd "$(dirname "$0")/../examples" && pwd)
LIB=$EX/tiny.genlib

run() { echo "============ $1 ============"; shift; "$@"; }

run "§0.1 strash" \
    $ABC -c "read $EX/aoi3.blif; strash; print_stats; write_blif /tmp/aoi3_strashed.blif" \
    && cat /tmp/aoi3_strashed.blif

run "§2 balance" \
    $ABC -c "read $EX/chain.blif; strash; ps; balance; ps; write_blif /tmp/chain_post.blif" \
    && cat /tmp/chain_post.blif

run "§3 rewrite" \
    env ABC_TRACE=1 $ABC -c "read $EX/aoi3.blif; strash; ps; rewrite; ps"

run "§4 refactor" \
    env ABC_TRACE=1 $ABC -c "read $EX/refactor_win.blif; strash; ps; refactor -N 6; ps"

run "§5 resub" \
    env ABC_TRACE=1 $ABC -c "read $EX/resub_win.blif; strash; ps; resub -K 6; ps"

run "§7 dc2" \
    $ABC -c "read $EX/aoi3.blif; strash; ps; dc2 -v; ps"

run "§8 fraig" \
    $ABC -c "read $EX/fraig_eq.blif; strash; ps; fraig -v; ps"

run "§9 dch" \
    $ABC -c "read $EX/aoi3.blif; strash; ps; dch -v; ps"

run "§10 retime" \
    $ABC -c "read $EX/retime_demo.blif; strash; ps; retime -M 3 -v; ps"

run "§11 if (K=4 on MAJ4)" \
    $ABC -c "read $EX/maj4.blif; strash; ps; if -K 4 -v; ps"

run "§12 map" \
    $ABC -c "read_library $LIB; read $EX/aoi3.blif; strash; map -v; ps"

run "§13 amap" \
    $ABC -c "read_library $LIB; read $EX/aoi3.blif; strash; amap -v; ps"

run "§14 mfs" \
    $ABC -c "read $EX/maj4.blif; strash; if -K 3; ps; mfs -v -w; ps"
