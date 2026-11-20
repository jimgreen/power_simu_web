<Model>
@ path      name     p_base  u_unit  p_unit  i_unit
# IEEE标准算例  qinling  100     V       kW      A
</Model>
<basevoltage>
@ idx  name  vltp
# 1    0     0
# 2    0.4   0.4
# 3    6     6
# 4    10    10
# 5    10.5  10.5
# 6    35    35
# 7    66    66
# 8    110   110
# 9    220   220
# 10   330   330
# 11   500   500
# 12   750   750
# 13   800   800
# 14   0     0
# 15   0.4   0.4
# 16   6     6
# 17   10    10
# 18   10.5  10.5
# 19   35    35
# 20   66    66
# 21   110   110
# 22   220   220
# 23   330   330
# 24   500   500
# 25   750   750
# 26   800   800
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
# 11   风机变流器-1       380    1
# 12   风机变流器-2       380    1
# 13   风机变流器-3       380    1
# 14   风机变流器-4       380    1
# 15   风机变流器-5       380    1
# 16   风机变流器-6       380    1
# 17   风机变流器-7       380    1
# 18   风机变流器-8       380    1
# 19   风机变流器-9       380    1
# 20   风机变流器-10      380    1
# 21   交流线路（自适应）-30  380    1
# 22   交流线路（自适应）-30  380    1
# 23   DCAC变流器-1     380    1
# 24   交流母线（竖向）-1    380    1
# 25   DCAC变流器-2     380    1
# 26   交流柴油发电机-27    380    1
# 27   交流柴油发电机-28    380    1
# 28   交流柴油发电机-29    380    1
# 29   交流柴油发电机-30    380    1
# 30   盒型开关-7        380    1
# 31   盒型开关-9        380    1
# 32   交流负荷-1        380    1
# 33   交流电化学储能-23    380    1
# 34   交流风力发电机-24    380    1
# 35   交流光伏发电机-25    380    1
# 36   交流电化学储能-26    380    1
</ACNode>
<ACRealBs>
@ idx  name        parent  dev_type  node  run_stat  v_max  v_min  rated_voltage  f   u
# 1    交流母线（竖向）-1  0       ACRealBs  24    1         456    304    380            50  380
</ACRealBs>
<ACBranch>
@ idx  name          parent  dev_type  i_node  j_node  run_stat  rated_capacity  i_max          r    x    b    i_p  i_q  i_u  i_i  j_p  j_q  j_u  j_i  rated_voltage  i  p  q
# 20   交流线路（自适应）-20  0       ACBranch  1       11      1         10              15.1938738301  0.1  1.0  0.0  0    0    0    0    0    0    0    0    380            0  0  0
# 21   交流线路（自适应）-21  0       ACBranch  2       12      1         10              15.1938738301  0.1  1.0  0.0  0    0    0    0    0    0    0    0    380            0  0  0
# 22   交流线路（自适应）-22  0       ACBranch  3       13      1         10              15.1938738301  0.1  1.0  0.0  0    0    0    0    0    0    0    0    380            0  0  0
# 23   交流线路（自适应）-23  0       ACBranch  4       14      1         10              15.1938738301  0.1  1.0  0.0  0    0    0    0    0    0    0    0    380            0  0  0
# 24   交流线路（自适应）-24  0       ACBranch  5       15      1         10              15.1938738301  0.1  1.0  0.0  0    0    0    0    0    0    0    0    380            0  0  0
# 25   交流线路（自适应）-25  0       ACBranch  6       16      1         10              15.1938738301  0.1  1.0  0.0  0    0    0    0    0    0    0    0    380            0  0  0
# 26   交流线路（自适应）-26  0       ACBranch  7       17      1         10              15.1938738301  0.1  1.0  0.0  0    0    0    0    0    0    0    0    380            0  0  0
# 27   交流线路（自适应）-27  0       ACBranch  8       18      1         10              15.1938738301  0.1  1.0  0.0  0    0    0    0    0    0    0    0    380            0  0  0
# 28   交流线路（自适应）-28  0       ACBranch  9       19      1         10              15.1938738301  0.1  1.0  0.0  0    0    0    0    0    0    0    0    380            0  0  0
# 29   交流线路（自适应）-29  0       ACBranch  10      20      1         10              15.1938738301  0.1  1.0  0.0  0    0    0    0    0    0    0    0    380            0  0  0
# 30   交流线路（自适应）-30  0       ACBranch  21      22      1         200             303.877476601  0.1  1.0  0.0  0    0    0    0    0    0    0    0    380            0  0  0
</ACBranch>
<ACLoad>
@ idx  name                parent  dev_type  node  p_set  p_max  p_min  q_set  q_max  q_min  run_stat  rated_capacity  pbase  pv0  pv1  pv2  qbase  qv0  qv1  qv2  v_max  v_min  rated_voltage  i  p  q  u
# 1    交流负荷-1              0       ACLoad    32    0      300    0      0      1.2    0      1         300             0.0    1.0  0.0  0.0  50     1.0  0.0  0.0  456    304    380            0  0  0  380
# 2    交流电制氢-1_交流设备端交流电负荷  0       ACLoad    31    0      80     0      0      80     -60    1         100             0      1.0  0.0  0.0  0      1.0  0.0  0.0  456    304    0              0  0  0  380
</ACLoad>
<ACGenerator>
@ idx  name        parent  dev_type      node  control_type  p_set  p_max  p_min  q_set  q_max  q_min  v_set  alpha  run_stat  rated_capacity  rated_voltage  v_max  v_min  regable  p  q  u  f  i
# 23   交流电化学储能-23  0       ACStorageGen  33    PQ            0.0    100    -100   0.0    100    -100   380    1.0    1         100             380            456    304    1        0  0  0  0  0
# 25   交流光伏发电机-25  0       ACPVGen       35    PQ            0      20     0      0      20     -20    380    1.0    1         20              380            456    304    1        0  0  0  0  0
# 26   交流电化学储能-26  0       ACStorageGen  36    PH            0.0    5      -5     0.0    5      -5     380    1.0    1         5               380            456    304    1        0  0  0  0  0
# 27   交流柴油发电机-27  0       ACDieselGen   26    PH            70     300    70     0      300    -300   380    1.0    1         300             380            456    304    1        0  0  0  0  0
# 28   交流柴油发电机-28  0       ACDieselGen   27    PH            70     300    70     0      300    -300   380    1.0    1         300             380            456    304    1        0  0  0  0  0
# 29   交流柴油发电机-29  0       ACDieselGen   28    PH            70     300    70     0      300    -300   380    1.0    1         300             380            456    304    1        0  0  0  0  0
# 30   交流柴油发电机-30  0       ACDieselGen   29    PH            70     300    70     0      300    -300   380    1.0    1         300             380            456    304    1        0  0  0  0  0
# 31   交流风电-1      0       ACWindGen     1     PQ            0      10.1   0      0      10.1   -10.1  380    1.0    1         10.1            380            456    304    1        0  0  0  0  0
# 32   交流风电-2      0       ACWindGen     2     PQ            0      10.1   0      0      10.1   -10.1  380    1.0    1         10.1            380            456    304    1        0  0  0  0  0
# 33   交流风电-3      0       ACWindGen     3     PQ            0      10.1   0      0      10.1   -10.1  380    1.0    1         10.1            380            456    304    1        0  0  0  0  0
# 34   交流风电-4      0       ACWindGen     4     PQ            0      10.1   0      0      10.1   -10.1  380    1.0    1         10.1            380            456    304    1        0  0  0  0  0
# 35   交流风电-5      0       ACWindGen     5     PQ            0      10.1   0      0      10.1   -10.1  380    1.0    1         10.1            380            456    304    1        0  0  0  0  0
# 36   交流风电-6      0       ACWindGen     6     PQ            0      10.1   0      0      10.1   -10.1  380    1.0    1         10.1            380            456    304    1        0  0  0  0  0
# 37   交流风电-7      0       ACWindGen     7     PQ            0      10.1   0      0      10.1   -10.1  380    1.0    1         10.1            380            456    304    1        0  0  0  0  0
# 38   交流风电-8      0       ACWindGen     8     PQ            0      10.1   0      0      10.1   -10.1  380    1.0    1         10.1            380            456    304    1        0  0  0  0  0
# 39   交流风电-9      0       ACWindGen     9     PQ            0      10.1   0      0      10.1   -10.1  380    1.0    1         10.1            380            456    304    1        0  0  0  0  0
# 40   交流风电-10     0       ACWindGen     10    PQ            0      10.1   0      0      10.1   -10.1  380    1.0    1         10.1            380            456    304    1        0  0  0  0  0
# 41   交流风力发电机-24  0       ACWindGen     34    PQ            0      50     0      0      50     -50    380    1.0    1         50              380            456    304    1        0  0  0  0  0
</ACGenerator>
<ACZeroBranch>
@ idx  name            parent  dev_type      i_node  j_node  run_stat  rated_voltage  i  p  q
# 1    交流零阻抗支路（自适应）-1  0       ACZeroBranch  30      32      1         380            0  0  0
</ACZeroBranch>
<ACBreak>
@ idx  name     parent  dev_type  i_node  j_node  status  closed_status_set  run_stat  i  rated_capacity  i_max          closed_status  p  q  u  rated_voltage
# 1    交流断路器-1  0       ACBreak   23      24      1       1                  1         0  300             455.816214902  1              0  0  0  380
# 2    交流断路器-2  0       ACBreak   25      24      1       1                  1         0  300             455.816214902  1              0  0  0  380
# 3    盒型开关-3   0       ACBreak   24      26      1       1                  1         0  300             455.816214902  1              0  0  0  380
# 4    盒型开关-4   0       ACBreak   24      27      1       1                  1         0  300             455.816214902  1              0  0  0  380
# 5    盒型开关-5   0       ACBreak   24      28      1       1                  1         0  300             455.816214902  1              0  0  0  380
# 6    盒型开关-6   0       ACBreak   24      29      1       1                  1         0  300             455.816214902  1              0  0  0  380
# 7    盒型开关-7   0       ACBreak   24      30      1       1                  1         0  300             455.816214902  1              0  0  0  380
# 8    盒型开关-8   0       ACBreak   24      21      1       1                  1         0  300             455.816214902  1              0  0  0  380
# 9    盒型开关-9   0       ACBreak   31      22      1       1                  1         0  300             455.816214902  1              0  0  0  380
# 10   盒型开关-10  0       ACBreak   24      33      1       1                  1         0  300             455.816214902  1              0  0  0  380
# 11   盒型开关-11  0       ACBreak   24      34      1       1                  1         0  300             455.816214902  1              0  0  0  380
# 12   盒型开关-12  0       ACBreak   24      35      1       1                  1         0  300             455.816214902  1              0  0  0  380
# 13   盒型开关-13  0       ACBreak   36      24      1       1                  1         0  300             455.816214902  1              0  0  0  380
</ACBreak>
<DCNode>
@ idx  name        vbase  run_stat
# 1    风机变流器-1     750    1
# 2    风机变流器-2     750    1
# 3    风机变流器-3     750    1
# 4    风机变流器-4     750    1
# 5    风机变流器-5     750    1
# 6    风机变流器-6     750    1
# 7    风机变流器-7     750    1
# 8    风机变流器-8     750    1
# 9    风机变流器-9     750    1
# 10   风机变流器-10    750    1
# 11   直流母线（竖向）-1  750    1
# 12   光伏变流器-1     750    1
# 13   光伏变流器-2     750    1
# 14   光伏变流器-3     750    1
# 15   储能变流器-1     750    1
# 16   储能变流器-2     750    1
# 17   储能变流器-3     750    1
# 18   储能变流器-4     750    1
# 19   储能变流器-5     750    1
# 20   储能变流器-6     750    1
# 21   DCAC变流器-1   750    1
# 22   DCAC变流器-2   750    1
# 23   直流断路器-31    750    1
# 24   直流断路器-32    750    1
# 25   直流断路器-32    750    1
# 26   直流光伏-1      400    1
# 27   直流光伏-2      400    1
# 28   直流光伏-3      400    1
# 29   电化学储能-1     500    1
# 30   电化学储能-2     500    1
# 31   电化学储能-3     500    1
# 32   电化学储能-4     500    1
# 33   电化学储能-5     500    1
# 34   电化学储能-6     500    1
# 35   光伏变流器-1     400    1
# 36   光伏变流器-2     400    1
# 37   光伏变流器-3     400    1
# 38   直流负荷-1      750    1
</DCNode>
<DCRealBs>
@ idx  name        parent  dev_type  node  run_stat  v_max  v_min  rated_voltage  i  u
# 1    直流母线（竖向）-1  0       DCRealBs  11    1         900    600    750            0  750
</DCRealBs>
<DCBranch>
@ idx  name        parent  dev_type  i_node  j_node  run_stat  rated_capacity  i_max          r    i_p  i_u  i_i  j_p  j_u  j_i  rated_voltage  i  p  u
# 1    光伏直流线路-1    0       DCBranch  26      35      1         100             144.341801386  1.0  0    0    0    0    0    0    400            0  0  400
# 2    光伏直流线路-2    0       DCBranch  27      36      1         100             144.341801386  1.0  0    0    0    0    0    0    400            0  0  400
# 3    光伏直流线路-3    0       DCBranch  28      37      1         100             144.341801386  1.0  0    0    0    0    0    0    400            0  0  400
# 4    燃料电池直流线路-1  0       DCBranch  23      24      1         100             76.9822940724  1.0  0    0    0    0    0    0    750            0  0  750
</DCBranch>
<DCLoad>
@ idx  name    parent  dev_type  node  p_set  p_max  p_min  run_stat  rated_capacity  pbase  pv0  pv1  pv2  v_max  v_min  rated_voltage  i  p  u
# 1    直流负荷-1  0       DCLoad    38    0      300    0      1         300             0      1.0  0.0  0.0  900    600    750            0  0  750
</DCLoad>
<DCGenerator>
@ idx  name                parent  dev_type      node  control_type  v_set  p_set  p_max  p_min  i_set  run_stat  rated_capacity  rated_voltage  v_max  v_min  p  u  i
# 1    直流光伏-1              0       DCPVGen       26    P             400    5.0    50     0      0.0    1         50              400            480    320    0  0  0
# 2    直流光伏-2              0       DCPVGen       27    P             400    5.0    50     0      0.0    1         50              400            480    320    0  0  0
# 3    直流光伏-3              0       DCPVGen       28    P             400    5.0    50     0      0.0    1         50              400            480    320    0  0  0
# 4    电化学储能-1             0       DCStorageGen  29    P             500    0.0    60     -60    0.0    1         60              500            600    400    0  0  0
# 5    电化学储能-2             0       DCStorageGen  30    P             500    0.0    60     -60    0.0    1         60              500            600    400    0  0  0
# 6    电化学储能-3             0       DCStorageGen  31    V             500    0.0    60     -60    0.0    1         60              500            600    400    0  0  0
# 7    电化学储能-4             0       DCStorageGen  32    V             500    0.0    60     -60    0.0    1         60              500            600    400    0  0  0
# 8    电化学储能-5             0       DCStorageGen  33    V             500    0.0    60     -60    0.0    1         60              500            600    400    0  0  0
# 9    电化学储能-6             0       DCStorageGen  34    V             500    0.0    60     -60    0.0    1         60              500            600    400    0  0  0
# 14   直流燃料电池-1_直流设备端直流电源  0       DCGenerator   25    P             750    0      30     0      0      1         30              750            900    600    0  0  0
</DCGenerator>
<DCBreak>
@ idx  name      parent  dev_type  i_node  j_node  status  closed_status_set  run_stat  i  rated_capacity  i_max          closed_status  p  u  rated_voltage
# 1    直流断路器-1   0       DCBreak   1       11      1       1                  1         0  300             230.946882217  1              0  0  750
# 2    直流断路器-2   0       DCBreak   2       11      1       1                  1         0  300             230.946882217  1              0  0  750
# 3    直流断路器-3   0       DCBreak   3       11      1       1                  1         0  300             230.946882217  1              0  0  750
# 4    直流断路器-4   0       DCBreak   4       11      1       1                  1         0  300             230.946882217  1              0  0  750
# 5    直流断路器-5   0       DCBreak   5       11      1       1                  1         0  300             230.946882217  1              0  0  750
# 6    直流断路器-6   0       DCBreak   6       11      1       1                  1         0  300             230.946882217  1              0  0  750
# 7    直流断路器-7   0       DCBreak   7       11      1       1                  1         0  300             230.946882217  1              0  0  750
# 8    直流断路器-8   0       DCBreak   8       11      1       1                  1         0  300             230.946882217  1              0  0  750
# 9    直流断路器-9   0       DCBreak   9       11      1       1                  1         0  300             230.946882217  1              0  0  750
# 11   直流断路器-11  0       DCBreak   10      11      1       1                  1         0  300             230.946882217  1              0  0  750
# 12   直流断路器-12  0       DCBreak   12      11      1       1                  1         0  300             230.946882217  1              0  0  750
# 13   直流断路器-13  0       DCBreak   13      11      1       1                  1         0  300             230.946882217  1              0  0  750
# 14   直流断路器-14  0       DCBreak   14      11      1       1                  1         0  300             230.946882217  1              0  0  750
# 15   直流断路器-15  0       DCBreak   11      15      1       1                  1         0  300             230.946882217  1              0  0  750
# 16   直流断路器-16  0       DCBreak   11      16      1       1                  1         0  300             230.946882217  1              0  0  750
# 17   直流断路器-17  0       DCBreak   11      17      1       1                  1         0  300             230.946882217  1              0  0  750
# 18   直流断路器-18  0       DCBreak   11      18      1       1                  1         0  300             230.946882217  1              0  0  750
# 20   直流断路器-20  0       DCBreak   11      19      1       1                  1         0  300             230.946882217  1              0  0  750
# 21   直流断路器-21  0       DCBreak   11      20      1       1                  1         0  300             230.946882217  1              0  0  750
# 29   直流断路器-29  0       DCBreak   11      21      1       1                  1         0  300             230.946882217  1              0  0  750
# 30   直流断路器-30  0       DCBreak   11      22      1       1                  1         0  300             230.946882217  1              0  0  750
# 31   直流断路器-31  0       DCBreak   11      23      1       1                  1         0  300             230.946882217  1              0  0  750
# 32   直流断路器-32  0       DCBreak   24      25      1       1                  1         0  300             230.946882217  1              0  0  750
# 33   直流断路器-33  0       DCBreak   11      38      1       1                  1         0  300             230.946882217  1              0  0  750
</DCBreak>
<DCDCConverter>
@ idx  name     parent  dev_type       i_node  j_node  i_control_type  j_control_type  run_stat  rated_capacity  i_p_max  i_p_min  i_i_max        i_v_max  i_v_min  j_p_max  j_p_min  j_i_max        j_v_max  j_v_min  r1  r2  i_set  p_set  v_set
# 1    光伏变流器-1  0       DCDCConverter  35      12      V               NONE            1         5               5        -5       7.21709006928  480      320      5        -5       3.84911470362  900      600      0   0   0      0      400
# 2    光伏变流器-2  0       DCDCConverter  36      13      V               NONE            1         5               5        -5       7.21709006928  480      320      5        -5       3.84911470362  900      600      0   0   0      0      400
# 3    光伏变流器-3  0       DCDCConverter  37      14      V               NONE            1         5               5        -5       7.21709006928  480      320      5        -5       3.84911470362  900      600      0   0   0      0      400
# 4    储能变流器-1  0       DCDCConverter  15      29      NONE            V               1         5               5        -5       3.84911470362  900      600      5        -5       5.77367205543  600      400      0   0   0      0      500
# 5    储能变流器-2  0       DCDCConverter  16      30      NONE            V               1         5               5        -5       3.84911470362  900      600      5        -5       5.77367205543  600      400      0   0   0      0      500
# 6    储能变流器-3  0       DCDCConverter  17      31      V               NONE            1         5               5        -5       3.84911470362  900      600      5        -5       5.77367205543  600      400      0   0   0      0      750
# 7    储能变流器-4  0       DCDCConverter  18      32      V               NONE            1         5               5        -5       3.84911470362  900      600      5        -5       5.77367205543  600      400      0   0   0      0      750
# 8    储能变流器-5  0       DCDCConverter  19      33      V               NONE            1         5               5        -5       3.84911470362  900      600      5        -5       5.77367205543  600      400      0   0   0      0      750
# 9    储能变流器-6  0       DCDCConverter  20      34      V               NONE            1         5               5        -5       3.84911470362  900      600      5        -5       5.77367205543  600      400      0   0   0      0      750
</DCDCConverter>
<DCACConverter>
@ idx  name       parent  dev_type       ac_node  dc_node  ac_control_type  dc_control_type  p_ac_set  q_ac_set  v_ac_set  p_dc_set  i_dc_set  v_dc_set  run_stat  rated_capacity  ac_p_max  ac_p_min  ac_q_max  ac_q_min  ac_i_max       ac_v_max  ac_v_min  dc_p_max  dc_p_min  dc_i_max       dc_v_max  dc_v_min  r1  r2
# 1    风机变流器-1    0       DCACConverter  11       1        PH               NONE             0         0         380       0         0         750       1         10              10        -10       10        -10       15.1938738301  456       304       10        -10       7.69822940724  900       600       0   0
# 2    风机变流器-2    0       DCACConverter  12       2        PH               NONE             0         0         380       0         0         750       1         10              10        -10       10        -10       15.1938738301  456       304       10        -10       7.69822940724  900       600       0   0
# 3    风机变流器-3    0       DCACConverter  13       3        PH               NONE             0         0         380       0         0         750       1         10              10        -10       10        -10       15.1938738301  456       304       10        -10       7.69822940724  900       600       0   0
# 4    风机变流器-4    0       DCACConverter  14       4        PH               NONE             0         0         380       0         0         750       1         10              10        -10       10        -10       15.1938738301  456       304       10        -10       7.69822940724  900       600       0   0
# 5    风机变流器-5    0       DCACConverter  15       5        PH               NONE             0         0         380       0         0         750       1         10              10        -10       10        -10       15.1938738301  456       304       10        -10       7.69822940724  900       600       0   0
# 6    风机变流器-6    0       DCACConverter  16       6        PH               NONE             0         0         380       0         0         750       1         10              10        -10       10        -10       15.1938738301  456       304       10        -10       7.69822940724  900       600       0   0
# 7    风机变流器-7    0       DCACConverter  17       7        PH               NONE             0         0         380       0         0         750       1         10              10        -10       10        -10       15.1938738301  456       304       10        -10       7.69822940724  900       600       0   0
# 8    风机变流器-8    0       DCACConverter  18       8        PH               NONE             0         0         380       0         0         750       1         10              10        -10       10        -10       15.1938738301  456       304       10        -10       7.69822940724  900       600       0   0
# 9    风机变流器-9    0       DCACConverter  19       9        PH               NONE             0         0         380       0         0         750       1         10              10        -10       10        -10       15.1938738301  456       304       10        -10       7.69822940724  900       600       0   0
# 10   风机变流器-10   0       DCACConverter  20       10       PH               NONE             0         0         380       0         0         750       1         10              10        -10       10        -10       15.1938738301  456       304       10        -10       7.69822940724  900       600       0   0
# 13   DCAC变流器-1  0       DCACConverter  23       21       PQ               NONE             0         0         380       0         0         750       1         300             300       -300      10        -10       455.816214902  456       304       300       -300      230.946882217  900       600       0   0
# 14   DCAC变流器-2  0       DCACConverter  25       22       PQ               NONE             0         0         380       0         0         750       1         300             300       -300      10        -10       455.816214902  456       304       300       -300      230.946882217  900       600       0   0
</DCACConverter>
<HydroNode>
@ idx  name       pressure  run_stat
# 1    集装格式储氢罐-3  1         1
</HydroNode>
<HydroSource>
@ idx  name             parent  dev_type     node  control_type  pressure_set  flow_set  run_stat  rated_capacity  pressure_max  pressure_min  flow_max  flow_min
# 1    交流电制氢-1_氢能设备端氢源  0       HydroSource  1     FLOW          20            10        1         10              25            1             10        0
</HydroSource>
<HydroLoad>
@ idx  name              parent  dev_type   node  control_type  pressure_set  flow_set  run_stat  rated_capacity  pressure_max  pressure_min  flow_max  flow_min
# 2    直流燃料电池-1_氢能设备端氢荷  0       HydroLoad  1     FLOW          2             10        1         30              5             0.1           30        0
</HydroLoad>
<HydroStorage>
@ idx  name       parent  dev_type      node  control_type  pressure_set  flow_set  alpha  run_stat  flow_min  flow_max  pressure  rated_capacity  water_volume  initial_soc  pressure_max  pressure_min  soc  soc_upper_limit  soc_lower_limit
# 4    集装格式储氢罐-3  0       HydroStorage  1     PRESSURE      1             0         1      1         -20       20        1         1000            10            0.5          10            1             0.5  0.9              0.1
</HydroStorage>
<AcE2Hydro>
@ idx  name     parent  dev_type   control_type  run_stat  e2h_coeff  idx_ac_load_t1  idx_h2_unit_t2
# 1    交流电制氢-1  0       AcE2Hydro  P             1         0.15       2               1
</AcE2Hydro>
<Hydro2DcE>
@ idx  name      parent  dev_type   control_type  run_stat  h2e_coeff  idx_dc_unit_t1  idx_h2_load_t2
# 2    直流燃料电池-1  0       Hydro2DcE  P             1         1.5        14              2
</Hydro2DcE>
<ACWindGen>
@ idx  idx_acgenerator  wind_turbine_model  cut_in_wind_speed  rated_wind_speed  cut_out_wind_speed  rotor_diameter  hub_height
# 1    31               WT-5MW              3                  12                35                  6               10
# 2    32               WT-5MW              3                  12                35                  6               10
# 3    33               WT-5MW              3                  12                35                  6               10
# 4    34               WT-5MW              3                  12                35                  6               10
# 5    35               WT-5MW              3                  12                35                  6               10
# 6    36               WT-5MW              3                  12                35                  6               10
# 7    37               WT-5MW              3                  12                35                  6               10
# 8    38               WT-5MW              3                  12                35                  6               10
# 9    39               WT-5MW              3                  12                35                  6               10
# 10   40               WT-5MW              3                  12                35                  6               10
# 11   41               WT-5MW              3                  12                25                  170             110
</ACWindGen>
<DCPVGen>
@ idx  idx_dcgenerator  pv_module_model  module_efficiency  array_area  mppt_count  reference_irradiance  reference_temperature  temperature_coefficient
# 1    1                Mono-550W        0.25               200         25          1000                  25                     -0.004
# 2    2                Mono-550W        0.25               200         25          1000                  25                     -0.004
# 3    3                Mono-550W        0.25               200         25          1000                  25                     -0.004
</DCPVGen>
<DCStorageGen>
@ idx  idx_dcgenerator  storage_technology  battery_rack_count  energy_capacity  charge_discharge_efficiency  max_charge_power  max_discharge_power  soc  soc_upper_limit  soc_lower_limit
# 1    4                lithium             20                  60               0.95                         60                60                   0.5  0.9              0.1
# 2    5                lithium             20                  60               0.95                         60                60                   0.5  0.9              0.1
# 3    6                lithium             20                  60               0.95                         60                60                   0.5  0.9              0.1
# 4    7                lithium             20                  60               0.95                         60                60                   0.5  0.9              0.1
# 5    8                lithium             20                  60               0.95                         60                60                   0.5  0.9              0.1
# 6    9                lithium             20                  60               0.95                         60                60                   0.5  0.9              0.1
</DCStorageGen>
<ACStorageGen>
@ idx  idx_acgenerator  storage_technology  battery_rack_count  energy_capacity  charge_discharge_efficiency  max_charge_power  max_discharge_power  soc  soc_upper_limit  soc_lower_limit
# 1    23               lithium             20                  200              0.9                          100               100                  0.5  0.9              0.1
# 2    26               lithium             20                  100              0.9                          100               100                  0.5  0.9              0.1
</ACStorageGen>
<ACPVGen>
@ idx  idx_acgenerator  pv_module_model  module_efficiency  array_area  mppt_count  reference_irradiance  reference_temperature  temperature_coefficient
# 1    25               Mono-550W        0.213              100000      100         1000                  25                     -0.004
</ACPVGen>
<ACDieselGen>
@ idx  idx_acgenerator  diesel_unit_model  fuel_grade  specific_fuel_consumption  fuel_tank_capacity  rated_speed  start_time
# 1    27               DG-2500            0#柴油        200                        20                  1500         10
# 2    28               DG-2500            0#柴油        200                        20                  1500         10
# 3    29               DG-2500            0#柴油        200                        20                  1500         10
# 4    30               DG-2500            0#柴油        200                        20                  1500         10
</ACDieselGen>
