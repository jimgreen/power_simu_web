<PowerBase>
@ p_base  u_scale  p_scale  i_scale
# 100     1000     1        1000
</PowerBase>
<ACNode>
@ idx  name            vbase  voltage  angle  isl  run_stat
# 1    wt01_src        300    300      0      0    1
# 2    wt01_rect       300    300      0      0    1
# 3    diesel_node     380    380      0      0    1
# 4    ac_bus          380    380      0      0    1
# 5    grid_inv_ac     380    380      0      0    1
# 6    load_ac_1_node  380    380      0      0    1
</ACNode>
<ACBranch>
@ idx  name         i_node  j_node  r      x      b  run_stat
# 1    wt01_cable   1       2       0.005  0.03   0  1
# 2    diesel_line  3       4       0.001  0.005  0  1
# 3    inv_ac_line  5       4       0.001  0.005  0  1
# 4    load1_line   6       4       0.001  0.005  0  1
</ACBranch>
<ACLoad>
@ idx  name       node  pbase  pv0  pv1  pv2  qbase  qv0  qv1  qv2  run_stat
# 1    load_ac_1  6     1      90   0    0    1      30   0    0    1
</ACLoad>
<ACGenerator>
@ idx  name          node  control_type  p_set  q_set  v_set  alpha  run_stat
# 1    wt01_10kw     1     V             0      0      300    1      1
# 2    diesel_300kw  3     V             80     0      380    1      1
</ACGenerator>
<DCNode>
@ idx  name         vbase  voltage  isl  run_stat
# 1    dc_bus_720v  720    720      0    1
# 2    wt01_dc      720    720      0    1
# 3    pv01_300v    300    300      0    1
# 4    pv01_720v    720    720      0    1
# 5    ess01_300v   300    300      0    1
# 6    ess01_720v   720    720      0    1
# 7    grid_inv_dc  720    720      0    1
</DCNode>
<DCBranch>
@ idx  name           i_node  j_node  r      run_stat
# 1    wt01_dc_line   2       1       0.001  1
# 2    pv01_dc_line   4       1       0.001  1
# 3    ess01_dc_line  6       1       0.001  1
# 4    inv_dc_line    7       1       0.001  1
</DCBranch>
<DCGenerator>
@ idx  name          node  control_type  v_set  p_set  i_set  run_stat
# 1    dc_bus_vctrl  1     V             720    0      0      1
# 2    pv01_vsrc     3     V             300    0      0      1
# 3    ess01_vsrc    5     V             300    0      0      1
</DCGenerator>
<DCDCConverter>
@ idx  name        i_node  j_node  r1     r2     control_type  p_set  i_set  v_set  run_stat
# 1    pv01_dcdc   3       4       0.005  0.005  P             25     0      0      1
# 2    ess01_dcdc  5       6       0.005  0.005  P             10     0      0      1
</DCDCConverter>
<DCACConverter>
@ idx  name          ac_node  dc_node  r1     r2     control_type  p_ac_set  q_ac_set  v_ac_set  v_dc_set  run_stat
# 1    wt01_rect     2        2        0.005  0.005  ACP           8         0         0         0         1
# 2    grid_inv_acp  5        7        0.005  0.005  ACP           -45       0         0         0         1
</DCACConverter>
