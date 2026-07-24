<RunStat>
@ dev_type       dev_name        run_stat
# ACNode         wt01_src        1
# ACNode         wt01_rect       1
# ACNode         diesel_node     1
# ACNode         ac_bus          1
# ACNode         grid_inv_ac     1
# ACNode         load_ac_1_node  1
# ACBranch       wt01_cable      1
# ACBranch       diesel_line     1
# ACBranch       inv_ac_line     1
# ACBranch       load1_line      1
# ACLoad         load_ac_1       1
# ACGenerator    wt01_10kw       1
# ACGenerator    diesel_300kw    1
# DCNode         dc_bus_720v     1
# DCNode         wt01_dc         1
# DCNode         pv01_300v       1
# DCNode         pv01_720v       1
# DCNode         ess01_300v      1
# DCNode         ess01_720v      1
# DCNode         grid_inv_dc     1
# DCBranch       wt01_dc_line    1
# DCBranch       pv01_dc_line    1
# DCBranch       ess01_dc_line   1
# DCBranch       inv_dc_line     1
# DCGenerator    dc_bus_vctrl    1
# DCGenerator    pv01_vsrc       1
# DCGenerator    ess01_vsrc      1
# DCDCConverter  pv01_dcdc       1
# DCDCConverter  ess01_dcdc      1
# DCACConverter  wt01_rect       1
# DCACConverter  grid_inv_acp    1
# ESS            ess01           1
</RunStat>
<SetValue>
@ dev_type       dev_name      set_type  set_value
# ACGenerator    wt01_10kw     p_set     0
# ACGenerator    wt01_10kw     q_set     0
# ACGenerator    wt01_10kw     v_set     300
# ACGenerator    diesel_300kw  p_set     80
# ACGenerator    diesel_300kw  q_set     0
# ACGenerator    diesel_300kw  v_set     380
# DCGenerator    dc_bus_vctrl  v_set     720
# DCGenerator    pv01_vsrc     v_set     300
# DCGenerator    ess01_vsrc    v_set     300
# DCDCConverter  pv01_dcdc     p_set     25
# DCDCConverter  pv01_dcdc     v_set     0
# DCDCConverter  ess01_dcdc    p_set     10
# DCDCConverter  ess01_dcdc    v_set     0
# DCACConverter  wt01_rect     p_set     8
# DCACConverter  wt01_rect     q_set     0
# DCACConverter  grid_inv_acp  p_set     -45
# DCACConverter  grid_inv_acp  q_set     0
# ACLoad         load_ac_1     p_set     90
# ACLoad         load_ac_1     q_set     30
</SetValue>
<StorageSoc>
@ dev_type  idx  name   soc_curr
# ESS       1    ess01  0.55
</StorageSoc>
