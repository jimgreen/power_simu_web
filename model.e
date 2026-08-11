<Model>
@ path      name     p_base  u_unit  p_unit  i_unit
# IEEE标准算例  qinling  100     V       kW      A
</Model>
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
</ACNode>
<ACRealBs>
@ idx  name        dev_type         node  run_stat
# 1    交流母线（竖向）-1  ac-bus-vertical  29    1
</ACRealBs>
<ACBranch>
@ idx  name          dev_type          i_node  j_node  r    x    b    run_stat
# 20   交流线路（自适应）-20  ac-routable-line  1       15      0.1  1.0  0.0  1
# 21   交流线路（自适应）-21  ac-routable-line  2       16      0.1  1.0  0.0  1
# 22   交流线路（自适应）-22  ac-routable-line  3       17      0.1  1.0  0.0  1
# 23   交流线路（自适应）-23  ac-routable-line  4       18      0.1  1.0  0.0  1
# 24   交流线路（自适应）-24  ac-routable-line  5       19      0.1  1.0  0.0  1
# 25   交流线路（自适应）-25  ac-routable-line  6       20      0.1  1.0  0.0  1
# 26   交流线路（自适应）-26  ac-routable-line  7       21      0.1  1.0  0.0  1
# 27   交流线路（自适应）-27  ac-routable-line  8       22      0.1  1.0  0.0  1
# 28   交流线路（自适应）-28  ac-routable-line  9       23      0.1  1.0  0.0  1
# 29   交流线路（自适应）-29  ac-routable-line  10      24      0.1  1.0  0.0  1
# 30   交流线路（自适应）-30  ac-routable-line  27      28      0.1  1.0  0.0  1
</ACBranch>
<ACLoad>
@ idx  name                dev_type         node  pbase  pv0  pv1  pv2  qbase  qv0  qv1  qv2  run_stat
# 1    交流负荷-1              ac-load          32    0      1.0  0.0  0.0  0      1.0  0.0  0.0  1
# 2    交流电制氢-1_交流设备端交流电负荷  ac-electrolyzer  31    0      1.0  0.0  0.0  0      1.0  0.0  0.0  1
</ACLoad>
<ACGenerator>
@ idx  name     dev_type        node  control_type  p_set  q_set  v_set  alpha  run_stat
# 1    交流风电-1   ac-wind-source  1     PV            0      0      380    1.0    1
# 2    交流风电-2   ac-wind-source  2     PV            0      0      380    1.0    1
# 3    交流风电-3   ac-wind-source  3     PV            0      0      380    1.0    1
# 4    交流风电-4   ac-wind-source  4     PV            0      0      380    1.0    1
# 5    交流风电-5   ac-wind-source  5     PV            0      0      380    1.0    1
# 6    交流风电-6   ac-wind-source  6     PV            0      0      380    1.0    1
# 7    交流风电-7   ac-wind-source  7     PV            0      0      380    1.0    1
# 8    交流风电-8   ac-wind-source  8     PV            0      0      380    1.0    1
# 9    交流风电-9   ac-wind-source  9     PV            0      0      380    1.0    1
# 10   交流风电-10  ac-wind-source  10    PV            0      0      380    1.0    1
# 11   柴油发电机-1  ac-source       11    PV            0      0      380    1.0    1
# 12   柴油发电机-2  ac-source       12    PV            0      0      380    1.0    1
# 13   柴油发电机-3  ac-source       13    PV            0      0      380    1.0    1
# 14   柴油发电机-4  ac-source       14    PV            0      0      380    1.0    1
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
</DCNode>
<DCRealBs>
@ idx  name        dev_type         node  run_stat
# 1    直流母线（竖向）-1  dc-bus-vertical  13    1
</DCRealBs>
<DCBranch>
@ idx  name        dev_type          i_node  j_node  r    run_stat
# 1    光伏直流线路-1    dc-routable-line  26      35      1.0  1
# 2    光伏直流线路-2    dc-routable-line  27      36      1.0  1
# 3    光伏直流线路-3    dc-routable-line  28      37      1.0  1
# 4    燃料电池直流线路-1  dc-routable-line  23      24      1.0  1
</DCBranch>
<DCGenerator>
@ idx  name                dev_type      node  control_type  v_set  p_set  i_set  run_stat
# 1    直流光伏-1              dc-pv-source  26    P             400    0      0      1
# 2    直流光伏-2              dc-pv-source  27    P             400    0      0      1
# 3    直流光伏-3              dc-pv-source  28    P             400    0      0      1
# 4    电化学储能-1             dc-storage    29    P             500    0.0    0.0    1
# 5    电化学储能-2             dc-storage    30    P             500    0.0    0.0    1
# 6    电化学储能-3             dc-storage    31    P             500    0.0    0.0    1
# 7    电化学储能-4             dc-storage    32    P             500    0.0    0.0    1
# 8    电化学储能-5             dc-storage    33    P             500    0.0    0.0    1
# 9    电化学储能-6             dc-storage    34    P             500    0.0    0.0    1
# 10   直流燃料电池-1_直流设备端直流电源  dc-fuel-cell  25    P             750    0      0      1
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
</DCBreak>
<DCDCConverter>
@ idx  name     dev_type        i_node  j_node  r1  r2  i_control_type  j_control_type  p_set  i_set  v_set  run_stat
# 1    光伏变流器-1  dcdc-converter  35      14      0   0   CTRL_V          SLACK           0      0      400    1
# 2    光伏变流器-2  dcdc-converter  36      15      0   0   CTRL_V          SLACK           0      0      400    1
# 3    光伏变流器-3  dcdc-converter  37      16      0   0   CTRL_V          SLACK           0      0      400    1
# 4    储能变流器-1  dcdc-converter  17      29      0   0   CTRL_V          SLACK           0      0      750    1
# 5    储能变流器-2  dcdc-converter  18      30      0   0   SLACK           CTRL_V          0      0      500    1
# 6    储能变流器-3  dcdc-converter  19      31      0   0   SLACK           CTRL_V          0      0      500    1
# 7    储能变流器-4  dcdc-converter  20      32      0   0   SLACK           CTRL_V          0      0      500    1
# 8    储能变流器-5  dcdc-converter  21      33      0   0   SLACK           CTRL_V          0      0      500    1
# 9    储能变流器-6  dcdc-converter  22      34      0   0   SLACK           CTRL_V          0      0      500    1
</DCDCConverter>
<DCACConverter>
@ idx  name       dev_type        ac_node  dc_node  r1  r2  control_type  p_ac_set  q_ac_set  v_ac_set  v_dc_set  run_stat
# 1    风机变流器-1    acdc-converter  15       1        0   0   ACP           0         0         380       750       1
# 2    风机变流器-2    acdc-converter  16       2        0   0   ACP           0         0         380       750       1
# 3    风机变流器-3    acdc-converter  17       3        0   0   ACP           0         0         380       750       1
# 4    风机变流器-4    acdc-converter  18       4        0   0   ACP           0         0         380       750       1
# 5    风机变流器-5    acdc-converter  19       5        0   0   ACP           0         0         380       750       1
# 6    风机变流器-6    acdc-converter  20       6        0   0   ACP           0         0         380       750       1
# 7    风机变流器-7    acdc-converter  21       7        0   0   ACP           0         0         380       750       1
# 8    风机变流器-8    acdc-converter  22       8        0   0   ACP           0         0         380       750       1
# 9    风机变流器-9    acdc-converter  23       9        0   0   ACP           0         0         380       750       1
# 10   风机变流器-10   acdc-converter  24       10       0   0   ACP           0         0         380       750       1
# 11   ACDC变流器-1  acdc-converter  25       11       0   0   ACP           0         0         380       750       1
# 12   ACDC变流器-2  acdc-converter  26       12       0   0   ACP           0         0         380       750       1
</DCACConverter>
<HydroNode>
@ idx  name    pressure  run_stat
# 1    氢气节点-1  1         1
</HydroNode>
<HydroSource>
@ idx  name             run_stat  node  dev_type
# 1    交流电制氢-1_氢能设备端氢源  1         1     ac-electrolyzer
</HydroSource>
<HydroLoad>
@ idx  name              dev_type      node  run_stat
# 1    直流燃料电池-1_氢能设备端氢荷  dc-fuel-cell  1     1
</HydroLoad>
<HydroStorage>
@ idx  name       dev_type                 node  press  flow  gas_quantity  water_volume  press_max  press_min  run_stat
# 1    集装格式储氢罐-1  hydrogen-tank-container  1     35     0     17500         50            45         2          1
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
</ACWindGen>
<DCPVGen>
@ idx  idx_dcgenerator  pv_module_model  module_efficiency  array_area  mppt_count
# 1    1                Mono-550W        0.213              250_m2      25
# 2    2                Mono-550W        0.213              250_m2      25
# 3    3                Mono-550W        0.213              250_m2      25
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
