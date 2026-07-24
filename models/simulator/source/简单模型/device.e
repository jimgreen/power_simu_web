<pv_generator>
@ id  name       p_max  p_min  p_fur  rated_power  temp_coefficient  reference_irradiance  reference_temperature
# 1   pv01_dcdc  50     0      0      50           -0.004            1000                  25
</pv_generator>
<wind_generator>
@ id  name       p_max  p_min  p_fur  rated_power  rated_wind_speed  cut_in_speed  cut_out_speed
# 1   wt01_rect  10     0      0      10           15                5             50
</wind_generator>
<diesel_generator>
@ id  name          p_max  p_min
# 1   diesel_300kw  300    30
</diesel_generator>
<load_curve_96>
@ id  name       p001   p002   p003   p004   p005   p006   p007   p008   p009   p010   p011   p012   p013   p014   p015   p016   p017   p018   p019   p020   p021   p022   p023   p024   p025   p026   p027   p028   p029   p030   p031   p032   p033   p034   p035   p036   p037   p038   p039   p040   p041   p042   p043   p044   p045   p046   p047   p048   p049   p050   p051   p052   p053   p054   p055   p056   p057   p058   p059   p060   p061   p062   p063   p064   p065   p066   p067   p068   p069   p070   p071   p072   p073   p074   p075   p076   p077   p078   p079   p080   p081   p082   p083   p084   p085   p086   p087   p088   p089   p090   p091   p092   p093   p094   p095   p096
# 1   load_ac_1  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.720  0.850  0.850  0.850  0.850  0.850  0.850  0.850  0.850  0.850  0.850  0.850  0.850  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  0.950  1.080  1.080  1.080  1.080  1.080  1.080  1.080  1.080  1.080  1.080  1.080  1.080  1.080  1.080  1.080  1.080  1.080  1.080  1.080  1.080  0.820  0.820  0.820  0.820  0.820  0.820  0.820  0.820
</load_curve_96>
<load_temperature>
@ id  name       temp_base  temp_factor
# 1   load_ac_1  5          -0.005
</load_temperature>
<estorage>
@ id  name   emva  soc_max  soc_min  soc_cur  charge_p_max  dis_charge_p_max
# 1   ess01  100   0.9      0.2      0.55     40            40
</estorage>
