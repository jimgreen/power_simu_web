<Model>
@ path      name     p_base  u_unit  p_unit  i_unit
# IEEE标准算例  qinling  100     V       kW      A
</Model>
<basevoltage>
@ idx  name  vltp  type
# 1    0     0     ac
# 2    0.4   0.4   ac
# 3    6     6     ac
# 4    10    10    ac
# 5    10.5  10.5  ac
# 6    35    35    ac
# 7    66    66    ac
# 8    110   110   ac
# 9    220   220   ac
# 10   330   330   ac
# 11   500   500   ac
# 12   750   750   ac
# 13   800   800   ac
# 14   0     0     dc
# 15   0.4   0.4   dc
# 16   6     6     dc
# 17   10    10    dc
# 18   10.5  10.5  dc
# 19   35    35    dc
# 20   66    66    dc
# 21   110   110   dc
# 22   220   220   dc
# 23   330   330   dc
# 24   500   500   dc
# 25   750   750   dc
# 26   800   800   dc
</basevoltage>
<ACNode>
@ idx  name          vbase  run_stat
# 1    交流风电-1        380    1
# 2    交流风电-2        380    1
# 3    交流风电-3        380    1
# 4    交流风电-4        380    1
# 5    交流风电-5        380    1
# 6    交流风电-6        380    1
# 7    交流风电-7        380    1
# 8    交流风电-8        380    1
# 9    交流风电-9        380    1
# 10   交流风电-10       380    1
# 11   柴油发电机-1       380    1
# 12   柴油发电机-2       380    1
# 13   柴油发电机-3       380    1
# 14   柴油发电机-4       380    1
# 15   风机变流器-1       380    1
# 16   风机变流器-2       380    1
# 17   风机变流器-3       380    1
# 18   风机变流器-4       380    1
# 19   风机变流器-5       380    1
# 20   风机变流器-6       380    1
# 21   风机变流器-7       380    1
# 22   风机变流器-8       380    1
# 23   风机变流器-9       380    1
# 24   风机变流器-10      380    1
# 25   ACDC变流器-1     380    1
# 26   ACDC变流器-2     380    1
# 27   交流线路（自适应）-30  380    1
# 28   交流线路（自适应）-30  380    1
# 29   交流母线（竖向）-1    380    1
# 30   盒型开关-7        380    1
# 31   盒型开关-9        380    1
# 32   交流负荷-1        380    1
# 33   交流电化学储能-23    380    1
# 34   交流风力发电机-24    380    1
# 35   交流光伏发电机-25    380    1
# 36   交流电化学储能-26    380    1
</ACNode>
<ACRealBs>
@ idx  name        dev_type         node  run_stat
# 1    交流母线（竖向）-1  ac-bus-vertical  29    1
</ACRealBs>
<ACBranch>
@ idx  name          dev_type          i_node  j_node  run_stat  r    x    b
# 20   交流线路（自适应）-20  ac-routable-line  1       15      1         0.1  1.0  0.0
# 21   交流线路（自适应）-21  ac-routable-line  2       16      1         0.1  1.0  0.0
# 22   交流线路（自适应）-22  ac-routable-line  3       17      1         0.1  1.0  0.0
# 23   交流线路（自适应）-23  ac-routable-line  4       18      1         0.1  1.0  0.0
# 24   交流线路（自适应）-24  ac-routable-line  5       19      1         0.1  1.0  0.0
# 25   交流线路（自适应）-25  ac-routable-line  6       20      1         0.1  1.0  0.0
# 26   交流线路（自适应）-26  ac-routable-line  7       21      1         0.1  1.0  0.0
# 27   交流线路（自适应）-27  ac-routable-line  8       22      1         0.1  1.0  0.0
# 28   交流线路（自适应）-28  ac-routable-line  9       23      1         0.1  1.0  0.0
# 29   交流线路（自适应）-29  ac-routable-line  10      24      1         0.1  1.0  0.0
# 30   交流线路（自适应）-30  ac-routable-line  27      28      1         0.1  1.0  0.0
</ACBranch>
<ACLoad>
@ idx  name                dev_type         node  run_stat  pbase  pv0  pv1  pv2  qbase  qv0  qv1  qv2
# 1    交流负荷-1              ac-load          32    1         150    1.0  0.0  0.0  50     1.0  0.0  0.0
# 2    交流电制氢-1_交流设备端交流电负荷  ac-electrolyzer  31    1         0      1.0  0.0  0.0  0      1.0  0.0  0.0
</ACLoad>
<ACGenerator>
@ idx  name        dev_type        node  control_type  p_set  p_max  p_min  q_set  q_max  q_min  v_set  alpha  run_stat  rated_capacity  rated_voltage
# 1    交流风电-1      ac-wind-source  1     PQ            3.0    0      0      0.5    0      0      380    0.5    1         10.1            380
# 2    交流风电-2      ac-wind-source  2     PQ            3.0    0      0      0.5    0      0      380    0.5    1         10.1            380
# 3    交流风电-3      ac-wind-source  3     PQ            3.0    0      0      0.5    0      0      380    0.5    1         10.1            380
# 4    交流风电-4      ac-wind-source  4     PQ            3.0    0      0      0.5    0      0      380    0.5    1         10.1            380
# 5    交流风电-5      ac-wind-source  5     PQ            3.0    0      0      0.5    0      0      380    0.5    1         10.1            380
# 6    交流风电-6      ac-wind-source  6     PQ            3.0    0      0      0.5    0      0      380    0.5    1         10.1            380
# 7    交流风电-7      ac-wind-source  7     PQ            3.0    0      0      0.5    0      0      380    0.5    1         10.1            380
# 8    交流风电-8      ac-wind-source  8     PQ            3.0    0      0      0.5    0      0      380    0.5    1         10.1            380
# 9    交流风电-9      ac-wind-source  9     PQ            3.0    0      0      0.5    0      0      380    0.5    1         10.1            380
# 10   交流风电-10     ac-wind-source  10    PQ            3.0    0      0      0.5    0      0      380    0.5    1         10.1            380
# 11   柴油发电机-1     ac-diesel-source  11    PH            0      300    0      0      0      0      380    1.0    1         300             380
# 12   柴油发电机-2     ac-diesel-source  12    PH            0      300    0      0      0      0      380    1.0    1         300             380
# 13   柴油发电机-3     ac-diesel-source  13    PH            0      300    0      0      0      0      380    1.0    1         300             380
# 14   柴油发电机-4     ac-diesel-source  14    PH            0      300    0      0      0      0      380    1.0    1         300             380
# 23   交流电化学储能-23  ac-storage      33    PQ            0.0    100    -100   0.0    0      0      380    1.0    1         100             380
# 24   交流风力发电机-24  ac-wind-source  34    PQ            0      50     0      0      0      0      380    1.0    1         50              380
# 25   交流光伏发电机-25  ac-pv-source    35    PV            0      0      0      0      0      0      380    1.0    1         20              10
# 26   交流电化学储能-26  ac-storage      36    PH            0.0    100    -100   0.0    0      0      380    1.0    1         5               380
</ACGenerator>
<ACZeroBranch>
@ idx  name            dev_type                 i_node  j_node  run_stat
# 1    交流零阻抗支路（自适应）-1  ac-zero-routable-branch  30      32      1
</ACZeroBranch>
<ACBreak>
@ idx  name     dev_type        i_node  j_node  status  run_stat
# 1    交流断路器-1  ac-breaker      25      29      1       1
# 2    交流断路器-2  ac-breaker      26      29      1       1
# 3    盒型开关-3   ac-box-breaker  29      11      1       1
# 4    盒型开关-4   ac-box-breaker  29      12      1       1
# 5    盒型开关-5   ac-box-breaker  29      13      1       1
# 6    盒型开关-6   ac-box-breaker  29      14      1       1
# 7    盒型开关-7   ac-box-breaker  29      30      1       1
# 8    盒型开关-8   ac-box-breaker  29      27      1       1
# 9    盒型开关-9   ac-box-breaker  31      28      1       1
# 10   盒型开关-10  ac-box-breaker  29      33      1       1
# 11   盒型开关-11  ac-box-breaker  29      34      1       1
# 12   盒型开关-12  ac-box-breaker  29      35      1       1
# 13   盒型开关-13  ac-box-breaker  36      29      1       1
</ACBreak>
<DCNode>
@ idx  name        vbase  voltage  isl  run_stat
# 1    风机变流器-1     750    750      0    1
# 2    风机变流器-2     750    750      0    1
# 3    风机变流器-3     750    750      0    1
# 4    风机变流器-4     750    750      0    1
# 5    风机变流器-5     750    750      0    1
# 6    风机变流器-6     750    750      0    1
# 7    风机变流器-7     750    750      0    1
# 8    风机变流器-8     750    750      0    1
# 9    风机变流器-9     750    750      0    1
# 10   风机变流器-10    750    750      0    1
# 11   ACDC变流器-1   750    750      0    1
# 12   ACDC变流器-2   750    750      0    1
# 13   直流母线（竖向）-1  750    750      0    1
# 14   光伏变流器-1     750    750      0    1
# 15   光伏变流器-2     750    750      0    1
# 16   光伏变流器-3     750    750      0    1
# 17   储能变流器-1     750    750      0    1
# 18   储能变流器-2     750    750      0    1
# 19   储能变流器-3     750    750      0    1
# 20   储能变流器-4     750    750      0    1
# 21   储能变流器-5     750    750      0    1
# 22   储能变流器-6     750    750      0    1
# 23   直流断路器-31    750    750      0    1
# 24   直流断路器-32    750    750      0    1
# 25   直流断路器-32    750    750      0    1
# 26   直流光伏-1      400    400      0    1
# 27   直流光伏-2      400    400      0    1
# 28   直流光伏-3      400    400      0    1
# 29   电化学储能-1     500    500      0    1
# 30   电化学储能-2     500    500      0    1
# 31   电化学储能-3     500    500      0    1
# 32   电化学储能-4     500    500      0    1
# 33   电化学储能-5     500    500      0    1
# 34   电化学储能-6     500    500      0    1
# 35   光伏变流器-1     400    400      0    1
# 36   光伏变流器-2     400    400      0    1
# 37   光伏变流器-3     400    400      0    1
# 38   直流负荷-1      750    750      0    1
</DCNode>
<DCRealBs>
@ idx  name        dev_type         node  run_stat
# 1    直流母线（竖向）-1  dc-bus-vertical  13    1
</DCRealBs>
<DCBranch>
@ idx  name        dev_type          i_node  j_node  run_stat  r
# 1    光伏直流线路-1    dc-routable-line  26      35      1         1.0
# 2    光伏直流线路-2    dc-routable-line  27      36      1         1.0
# 3    光伏直流线路-3    dc-routable-line  28      37      1         1.0
# 4    燃料电池直流线路-1  dc-routable-line  23      24      1         1.0
</DCBranch>
<DCLoad>
@ idx  name    dev_type  node  run_stat  pbase  pv0  pv1  pv2
# 1    直流负荷-1  dc-load   38    1         0      1.0  0.0  0.0
</DCLoad>
<DCGenerator>
@ idx  name                dev_type      node  control_type  v_set  p_set  p_max  p_min  i_set  run_stat  rated_capacity  rated_voltage
# 1    直流光伏-1              dc-pv-source  26    P             400    5.0    0      0      0.0    1         50              400
# 2    直流光伏-2              dc-pv-source  27    P             400    5.0    0      0      0.0    1         50              400
# 3    直流光伏-3              dc-pv-source  28    P             400    5.0    0      0      0.0    1         50              400
# 4    电化学储能-1             dc-storage    29    P             500    0.0    0      0      0.0    1         60              500
# 5    电化学储能-2             dc-storage    30    P             500    0.0    0      0      0.0    1         60              500
# 6    电化学储能-3             dc-storage    31    V             500    0.0    0      0      0.0    1         60              500
# 7    电化学储能-4             dc-storage    32    V             500    0.0    0      0      0.0    1         60              500
# 8    电化学储能-5             dc-storage    33    V             500    0.0    0      0      0.0    1         60              500
# 9    电化学储能-6             dc-storage    34    V             500    0.0    0      0      0.0    1         60              500
# 10   直流燃料电池-1_直流设备端直流电源  dc-fuel-cell  25    P             750    0      0      0      0      1         0               0
</DCGenerator>
<DCBreak>
@ idx  name      dev_type    i_node  j_node  status  run_stat
# 1    直流断路器-1   dc-breaker  1       13      1       1
# 2    直流断路器-2   dc-breaker  2       13      1       1
# 3    直流断路器-3   dc-breaker  3       13      1       1
# 4    直流断路器-4   dc-breaker  4       13      1       1
# 5    直流断路器-5   dc-breaker  5       13      1       1
# 6    直流断路器-6   dc-breaker  6       13      1       1
# 7    直流断路器-7   dc-breaker  7       13      1       1
# 8    直流断路器-8   dc-breaker  8       13      1       1
# 9    直流断路器-9   dc-breaker  9       13      1       1
# 11   直流断路器-11  dc-breaker  10      13      1       1
# 12   直流断路器-12  dc-breaker  14      13      1       1
# 13   直流断路器-13  dc-breaker  15      13      1       1
# 14   直流断路器-14  dc-breaker  16      13      1       1
# 15   直流断路器-15  dc-breaker  13      17      1       1
# 16   直流断路器-16  dc-breaker  13      18      1       1
# 17   直流断路器-17  dc-breaker  13      19      1       1
# 18   直流断路器-18  dc-breaker  13      20      1       1
# 20   直流断路器-20  dc-breaker  13      21      1       1
# 21   直流断路器-21  dc-breaker  13      22      1       1
# 29   直流断路器-29  dc-breaker  13      11      1       1
# 30   直流断路器-30  dc-breaker  13      12      1       1
# 31   直流断路器-31  dc-breaker  13      23      1       1
# 32   直流断路器-32  dc-breaker  24      25      1       1
# 33   直流断路器-33  dc-breaker  13      38      1       1
</DCBreak>
<DCDCConverter>
@ idx  name     dev_type        i_node  j_node  i_control_type  j_control_type  p_set  i_set  v_set  run_stat  r1  r2
# 1    光伏变流器-1  dcdc-converter  35      14      V               NONE            0      0      400    1         0   0
# 2    光伏变流器-2  dcdc-converter  36      15      V               NONE            0      0      400    1         0   0
# 3    光伏变流器-3  dcdc-converter  37      16      V               NONE            0      0      400    1         0   0
# 4    储能变流器-1  dcdc-converter  17      29      NONE            V               0      0      400    1         0   0
# 5    储能变流器-2  dcdc-converter  18      30      NONE            V               0      0      400    1         0   0
# 6    储能变流器-3  dcdc-converter  19      31      V               NONE            0      0      750    1         0   0
# 7    储能变流器-4  dcdc-converter  20      32      V               NONE            0      0      750    1         0   0
# 8    储能变流器-5  dcdc-converter  21      33      V               NONE            0      0      750    1         0   0
# 9    储能变流器-6  dcdc-converter  22      34      V               NONE            0      0      750    1         0   0
</DCDCConverter>
<DCACConverter>
@ idx  name       dev_type             ac_node  dc_node  ac_control_type  dc_control_type  p_ac_set  q_ac_set  v_ac_set  v_dc_set  run_stat  rated_capacity  ac_p_max  ac_p_min  ac_i_max  ac_v_max  ac_v_min  dc_p_max  dc_p_min  dc_i_max  dc_v_max  dc_v_min  r1  r2
# 1    风机变流器-1    wind-acdc-converter  15       1        PH               NONE             0         0         380       750       1         10              10        -10       0         1.1       0.9       10        -10       0         1.1       0.9       0   0
# 2    风机变流器-2    wind-acdc-converter  16       2        PH               NONE             0         0         380       750       1         10              10        -10       0         1.1       0.9       10        -10       0         1.1       0.9       0   0
# 3    风机变流器-3    wind-acdc-converter  17       3        PH               NONE             0         0         380       750       1         10              10        -10       0         1.1       0.9       10        -10       0         1.1       0.9       0   0
# 4    风机变流器-4    wind-acdc-converter  18       4        PH               NONE             0         0         380       750       1         10              10        -10       0         1.1       0.9       10        -10       0         1.1       0.9       0   0
# 5    风机变流器-5    wind-acdc-converter  19       5        PH               NONE             0         0         380       750       1         10              10        -10       0         1.1       0.9       10        -10       0         1.1       0.9       0   0
# 6    风机变流器-6    wind-acdc-converter  20       6        PH               NONE             0         0         380       750       1         10              10        -10       0         1.1       0.9       10        -10       0         1.1       0.9       0   0
# 7    风机变流器-7    wind-acdc-converter  21       7        PH               NONE             0         0         380       750       1         10              10        -10       0         1.1       0.9       10        -10       0         1.1       0.9       0   0
# 8    风机变流器-8    wind-acdc-converter  22       8        PH               NONE             0         0         380       750       1         10              10        -10       0         1.1       0.9       10        -10       0         1.1       0.9       0   0
# 9    风机变流器-9    wind-acdc-converter  23       9        PH               NONE             0         0         380       750       1         10              10        -10       0         1.1       0.9       10        -10       0         1.1       0.9       0   0
# 10   风机变流器-10   wind-acdc-converter  24       10       PH               NONE             0         0         380       750       1         10              10        -10       0         1.1       0.9       10        -10       0         1.1       0.9       0   0
# 11   ACDC变流器-1  grid-dcac-converter   25       11       PQ               NONE             0         0         380       750       1         300             300       -300      0         1.1       0.9       300       -300      0         1.1       0.9       0   0
# 12   ACDC变流器-2  grid-dcac-converter   26       12       PQ               NONE             0         0         380       750       1         300             300       -300      0         1.1       0.9       300       -300      0         1.1       0.9       0   0
</DCACConverter>
<HydroSource>
@ idx  name             dev_type         node  run_stat
# 1    交流电制氢-1_氢能设备端氢源  ac-electrolyzer  1     1
</HydroSource>
<HydroLoad>
@ idx  name              dev_type      node  run_stat
# 1    直流燃料电池-1_氢能设备端氢荷  dc-fuel-cell  1     1
</HydroLoad>
<HydroStorage>
@ idx  name       dev_type                 node  run_stat
# 1    集装格式储氢罐-1  hydrogen-tank-container  1     1
</HydroStorage>
<AcE2Hydro>
@ idx  name     run_stat  idx_ac_load_t1  idx_h2_unit_t2
# 1    交流电制氢-1  1         2               1
</AcE2Hydro>
<Hydro2DcE>
@ idx  name      run_stat  idx_dc_unit_t1  idx_h2_load_t2
# 1    直流燃料电池-1  1         10              1
</Hydro2DcE>
<ACWindGen>
@ idx  idx_acgenerator  wind_turbine_model  cut_in_wind_speed  rated_wind_speed  cut_out_wind_speed  rotor_diameter  hub_height
# 1    1                WT-5MW              3                  12                35                  6               10
# 2    2                WT-5MW              3                  12                35                  6               10
# 3    3                WT-5MW              3                  12                35                  6               10
# 4    4                WT-5MW              3                  12                35                  6               10
# 5    5                WT-5MW              3                  12                35                  6               10
# 6    6                WT-5MW              3                  12                35                  6               10
# 7    7                WT-5MW              3                  12                35                  6               10
# 8    8                WT-5MW              3                  12                35                  6               10
# 9    9                WT-5MW              3                  12                35                  6               10
# 10   10               WT-5MW              3                  12                35                  6               10
# 11   24               WT-5MW              3                  12                25                  170             110
</ACWindGen>
<DCPVGen>
@ idx  idx_dcgenerator  pv_module_model  module_efficiency  array_area  mppt_count
# 1    1                Mono-550W        0.25               200         25
# 2    2                Mono-550W        0.25               200         25
# 3    3                Mono-550W        0.25               200         25
</DCPVGen>
<DCStorageGen>
@ idx  idx_dcgenerator  storage_technology  battery_rack_count  energy_capacity  charge_discharge_efficiency  max_charge_power  max_discharge_power  state_of_charge  soc_upper_limit  soc_lower_limit
# 1    4                lithium             20                  60               0.95                         60                60                   0.5              0.9              0.1
# 2    5                lithium             20                  60               0.95                         60                60                   0.5              0.9              0.1
# 3    6                lithium             20                  60               0.95                         60                60                   0.5              0.9              0.1
# 4    7                lithium             20                  60               0.95                         60                60                   0.5              0.9              0.1
# 5    8                lithium             20                  60               0.95                         60                60                   0.5              0.9              0.1
# 6    9                lithium             20                  60               0.95                         60                60                   0.5              0.9              0.1
</DCStorageGen>
<ACStorageGen>
@ idx  idx_acgenerator  storage_technology  battery_rack_count  energy_capacity  charge_discharge_efficiency  max_charge_power  max_discharge_power  state_of_charge  soc_upper_limit  soc_lower_limit
# 1    23               lithium             20                  200              0.9                          100               100                  0.5              0.9              0.1
# 2    26               lithium             20                  100              0.9                          100               100                  0.5              0.9              0.1
</ACStorageGen>
<ACPVGen>
@ idx  idx_acgenerator  pv_module_model  module_efficiency  array_area  mppt_count
# 1    25               Mono-550W        0.213              100000      100
</ACPVGen>
