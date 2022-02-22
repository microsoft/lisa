#!/bin/bash

CORE_ID_S=${1:-0}
NUM_QP=${2:-4}


function get_device() {
   IFS=$'\n'
   LINES=( $(ibdev2netdev) )
   for ((i=0; i<${#LINES[*]}; i++)); do
      if [[ "${LINES[$i]//"ib0"}" != "${LINES[$i]}" ]]; then
         IFS=$' \t\n'
         LINE=( ${LINES[$i]} )
         echo "${LINE[4]}"
      fi
   done
   IFS=$' \t\n'
}


function get_irq_indices
{
   cnt=0
   irq_index=()
   for irq in `ls /sys/class/net/$DEVICE/device/msi_irqs`
   do
      if [ $cnt -gt 0 ]; then
         irq_index+=($irq)
      fi
      cnt=$((cnt+1))
   done
}


function calc_core_id_e
{
   CORE_ID_E=$((CORE_ID_S + NUM_QP - 1))
}


function get_core_indices
{
   core_index=()
   for core_id in $(seq $CORE_ID_S $CORE_ID_E)
   do
      core_index+=($core_id)
   done
}


function set_num_qp
{
ethtool -l $DEVICE
ethtool -L $DEVICE combined $NUM_QP
ethtool -l $DEVICE
}


function calc_irq_index_e
{
  IRQ_INDEX_E=${#irq_index[@]}
  IRQ_INDEX_E=$((IRQ_INDEX_E<NUM_QP ? IRQ_INDEX_E : NUM_QP))
}


function map_numa_to_irq
{
   for ((i=0;i<$IRQ_INDEX_E;i++));
   do
      echo "----"
      cat /proc/irq/${irq_index[i]}/smp_affinity_list
      echo "${core_index[i]}, ${irq_index[i]}"
      echo "${core_index[i]}" > /proc/irq/${irq_index[i]}/smp_affinity_list
      cat /proc/irq/${irq_index[i]}/smp_affinity_list
   done
}

echo "-------------------------------------------------------------"
echo "executing map_irq_to_numa.sh" 
echo "-------------------------------------------------------------" 
DEVICE=$(get_device)
#DEVICE=eth2
get_irq_indices
calc_core_id_e
get_core_indices
set_num_qp
calc_irq_index_e
map_numa_to_irq
