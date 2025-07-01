# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional, Type

from lisa.executable import Tool
from lisa.tools import Cat


class Interrupt:
    irq_number: str
    cpu_counter: List[int]
    metadata: str
    counter_sum: int

    def __init__(
        self,
        irq_number: str,
        cpu_counter: List[int],
        counter_sum: int,
        metadata: str = "",
    ) -> None:
        self.irq_number = irq_number
        self.cpu_counter = cpu_counter
        self.metadata = metadata
        self.counter_sum = counter_sum

    def __str__(self) -> str:
        return (
            f"irq_number : {self.irq_number}, "
            f"count : {self.cpu_counter}, "
            f"metadata : {self.metadata}"
            f"sum : {self.counter_sum}"
        )

    def __repr__(self) -> str:
        return self.__str__()


class InterruptInspector(Tool):
    # 0:         22          0  IR-IO-APIC   2-edge      timer
    _interrupt_regex = re.compile(
        r"^\s*(?P<irq_number>\S+):\s+(?P<cpu_counter>[\d+ ]+)\s*(?P<metadata>.*)$"
    )

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return InterruptInspectorBSD

    @property
    def command(self) -> str:
        return "cat /proc/interrupts"

    @property
    def can_install(self) -> bool:
        return False

    def _check_exists(self) -> bool:
        return True

    def get_interrupt_data(self) -> List[Interrupt]:
        # Run cat /proc/interrupts. The output is of the form :
        #          CPU0       CPU1
        # 0:         22          0  IR-IO-APIC   2-edge      timer
        # 1:          2          0  IR-IO-APIC   1-edge      i8042
        # ERR:        0
        # The first column refers to the IRQ number. The next column contains
        # number of interrupts per IRQ for each CPU in the system. The remaining
        # column report the metadata about interrupts, including type of interrupt,
        # device etc. This is variable for each distro.
        # Note : Some IRQ numbers have single entry because they're not actually
        # CPU stats, but events count belonging to the IO-APIC controller. For
        # example, `ERR` is incremented in the case of errors in the IO-APIC bus.
        result = self.node.tools[Cat].run("/proc/interrupts", sudo=True, force_run=True)
        mappings = result.stdout.splitlines(keepends=False)[1:]
        assert mappings

        interrupts = []
        for line in mappings:
            matched = self._interrupt_regex.fullmatch(line)
            assert matched
            cpu_counter = [int(count) for count in matched.group("cpu_counter").split()]
            counter_sum = sum(int(x) for x in cpu_counter)
            interrupts.append(
                Interrupt(
                    irq_number=matched.group("irq_number"),
                    cpu_counter=cpu_counter,
                    counter_sum=counter_sum,
                    metadata=matched.group("metadata"),
                )
            )

        return interrupts

    def sum_cpu_counter_by_irqs(
        self,
        pci_slot: str,
        exclude_key_words: Optional[List[str]] = None,
    ) -> List[Dict[str, int]]:
        interrupts_sum_by_irqs: List[Dict[str, int]] = []
        interrupts = self.get_interrupt_data()
        if exclude_key_words is None:
            exclude_key_words = []
        matched_interrupts = [
            x
            for x in interrupts
            if pci_slot in x.metadata
            and all(y not in x.metadata for y in exclude_key_words)
        ]
        interrupts_sum_by_irqs.extend(
            {interrupt.irq_number: interrupt.counter_sum}
            for interrupt in matched_interrupts
        )
        return interrupts_sum_by_irqs

    def sum_cpu_counter_by_index(self, pci_slot: str) -> Dict[int, int]:
        interrupts_by_cpu: Counter[int] = Counter()
        for interrupt in self.get_interrupt_data():
            # Ignore unrelated entries
            if pci_slot not in interrupt.metadata:
                continue

            # For each CPU, add count to totals
            for cpu_index, count in enumerate(interrupt.cpu_counter):
                interrupts_by_cpu[cpu_index] += count

        # Return a standard dictionary
        return dict(interrupts_by_cpu)


class InterruptInspectorBSD(InterruptInspector):
    # irq15: ata1                          585          1
    # cpu0:timer                          9154         12
    _interrupt_regex = re.compile(
        r"^\s*(?P<irq_name>\S+):\s?(?P<irq_type>\S+)\s*(?P<irq_count>\d+)\s*"
        r"(?P<irq_rate>\d+)$"
    )
    _cpu_number_regex = re.compile(r"cpu(?P<cpu_index>\d+)")

    @property
    def command(self) -> str:
        return "vmstat -i"

    def get_interrupt_data(self) -> List[Interrupt]:
        # Run vmstat -i. The output is of the form :
        # interrupt                          total       rate
        # irq1: atkbd0                           2          0
        # irq4: uart0                          842          1
        # irq6: fdc0                            11          0
        # irq14: ata0                            2          0
        # cpu0:timer                          9154         12
        # cpu1:timer                          4384          6
        # cpu2:timer                          4297          6
        # Total                              13950         25
        # The columns are in order: IRQ name, IRQ type, IRQ count, IRQ rate.
        result = self.run(force_run=True)
        mappings = result.stdout.splitlines(keepends=False)[1:-1]
        assert mappings
        interrupts: List[Interrupt] = []
        for line in mappings:
            matched = self._interrupt_regex.fullmatch(line)
            assert matched
            if matched.group("irq_name").startswith("cpu"):
                # cpu interrupts need to be organized by irq type not name
                output = self.node.execute("sysctl -n kern.smp.cpus")
                core_count = int(output.stdout.strip())
                exists = False
                num_result = self._cpu_number_regex.fullmatch(matched.group("irq_name"))
                assert num_result
                cpu_num = int(num_result.group("cpu_index"))
                for interrupt in interrupts:
                    if interrupt.irq_number == matched.group("irq_type"):
                        interrupt.cpu_counter[cpu_num] = int(matched.group("irq_count"))
                        interrupt.counter_sum += int(matched.group("irq_count"))
                        exists = True
                        break
                if not exists:
                    newinterrupt = Interrupt(
                        irq_number=matched.group("irq_type"),
                        cpu_counter=[0] * core_count,
                        counter_sum=int(matched.group("irq_count")),
                        metadata=matched.group("irq_type"),
                    )
                    newinterrupt.cpu_counter[cpu_num] = int(matched.group("irq_count"))
                    interrupts.append(newinterrupt)

            else:
                interrupts.append(
                    Interrupt(
                        irq_number=str(matched.group("irq_name")),
                        cpu_counter=[int(matched.group("irq_count"))],
                        counter_sum=int(matched.group("irq_count")),
                        metadata=str(matched.group("irq_type")),
                    )
                )
        result = self.node.execute("pciconf -l")
        for interrupt in interrupts:
            # The metadata is the IRQ type. We need to get the PCI slot from the
            # pciconf output.
            for line in result.stdout.splitlines(keepends=False):
                if interrupt.metadata in line:
                    interrupt.metadata += line
                    break
        return interrupts

    def sum_cpu_counter_by_index(self, pci_slot: str) -> Dict[int, int]:
        interrupts_by_irq: Counter[str] = Counter()
        for interrupt in self.get_interrupt_data():
            # Ignore unrelated entries
            if pci_slot not in interrupt.metadata:
                continue

            # For each CPU, add count to totals
            interrupts_by_irq[interrupt.irq_number] += interrupt.counter_sum
        interrupts_by_cpu: Counter[int] = Counter()
        i = 0
        for irq in interrupts_by_irq:
            interrupts_by_cpu[i] = interrupts_by_irq[irq]
            i += 1
        # Return a standard dictionary
        return dict(interrupts_by_cpu)
