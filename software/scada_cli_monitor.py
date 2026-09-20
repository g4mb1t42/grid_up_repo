#!/usr/bin/env python3
"""
Industrial SCADA CLI Monitor.
Direct Modbus TCP client polling esp1..10 and esp666.
Runs with sub-second response times and no shell regex parsing errors.
"""

import os
import sys
import time
from pyModbusTCP.client import ModbusClient

HOST = "127.0.0.1"
PORT = 5020
DEVICES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, "TEST"]

# ANSI Colors
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_GREEN = "\033[1;32m"
CLR_RED = "\033[1;31m"
CLR_YELLOW = "\033[1;33m"
CLR_CYAN = "\033[1;36m"
CLR_GRAY = "\033[0;90m"
CLR_ALERT_BG = "\033[41;1;37m"

client = ModbusClient(host=HOST, port=PORT, auto_open=True, auto_close=True, timeout=1.5)

def main():
    while True:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"{CLR_BOLD}{CLR_CYAN}" + "=" * 99 + f"{CLR_RESET}",
            f"{CLR_BOLD} SWITCHGEAR SCADA TERMINAL MONITOR (Modbus TCP {HOST}:{PORT})  |  {timestamp}{CLR_RESET}",
            f"{CLR_BOLD}{CLR_CYAN}" + "=" * 99 + f"{CLR_RESET}",
            f"{'DEVICE':<10} | {'STATUS':<10} | {'ARC':<6} | {'CURRENT (A)':<12} | {'HUMIDITY (%)':<12} | {'SAFETY STATE':<20}",
            f"{CLR_GRAY}" + "-" * 99 + f"{CLR_RESET}"
        ]

        for dev in DEVICES:
            dev_name = f"esp{dev}"
            base_addr = (dev - 1) * 10

            # 1. Read 3 Holding Registers (Current, Humidity, State)
            regs = client.read_holding_registers(base_addr, 3)
            # 2. Read 4 Discrete Inputs (Arc, Overcurrent, HumAlert, CommLost)
            bits = client.read_discrete_inputs(base_addr, 4)

            if regs is None or bits is None:
                lines.append(
                    f"{dev_name:<10} | {CLR_GRAY}[NO COMM]{CLR_RESET}   | --     | --           | --           | {CLR_GRAY}UNREACHABLE{CLR_RESET}"
                )
                continue

            curr_raw, hum_raw, state_code = regs
            arc_bit, overcurr_bit, hum_bit, comm_lost_bit = bits

            # Scaled Values
            curr_val = curr_raw / 10.0
            hum_val = hum_raw / 10.0

            # Status Column
            if comm_lost_bit == 1:
                status_str = f"{CLR_RED}OFFLINE{CLR_RESET}   "
            else:
                status_str = f"{CLR_GREEN}ONLINE{CLR_RESET}    "

            # Arc Column
            if arc_bit == 1:
                arc_str = f"{CLR_ALERT_BG} TRIP {CLR_RESET}"
            else:
                arc_str = f"{CLR_GREEN}OK{CLR_RESET}    "

            # Current Format
            if curr_val > 600.0:
                curr_str = f"{CLR_RED}{curr_val:>5.1f} A{CLR_RESET}     "
            else:
                curr_str = f"{curr_val:>5.1f} A     "

            # Humidity Format
            if hum_val > 85.0:
                hum_str = f"{CLR_YELLOW}{hum_val:>5.1f} %{CLR_RESET}     "
            else:
                hum_str = f"{hum_val:>5.1f} %     "

            # State Column
            if state_code == 1:
                state_str = f"{CLR_RED}{CLR_BOLD}ALERT ACTIVE{CLR_RESET}"
            elif state_code == 2:
                state_str = f"{CLR_YELLOW}{CLR_BOLD}INSPECTION REQ{CLR_RESET}"
            else:
                state_str = f"{CLR_GREEN}NORMAL{CLR_RESET}"

            lines.append(
                f"{dev_name:<10} | {status_str} | {arc_str} | {curr_str} | {hum_str} | {state_str}"
            )

        lines.append(f"{CLR_GRAY}" + "-" * 99 + f"{CLR_RESET}")
        lines.append(f"{CLR_GRAY}Refreshing every 1.0s. Press [Ctrl+C] to exit.{CLR_RESET}")

        # Atomic terminal refresh (no flickering)
        sys.stdout.write("\033[H\033[J" + "\n".join(lines) + "\n")
        sys.stdout.flush()

        time.sleep(1.0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{CLR_RESET}Stopped.")