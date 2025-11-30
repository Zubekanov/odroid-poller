#!/usr/bin/env python3

import time
import psutil
import psycopg
import subprocess
import math

# Database connection details
DB_DSN = "omitted_for_privacy"

# Detect CPU temp via psutil
def get_cpu_temp():
	try:
		temps = psutil.sensors_temperatures()
		for name, entries in temps.items():
			for e in entries:
				if "package" in e.label.lower() or "core 0" in e.label.lower():
					return float(e.current)
		# fallback: return first sensor
		for entries in temps.values():
			return float(entries[0].current)
	except:
		return None
	return None

# Detect CPU power via RAPL (Intel only)
def get_cpu_power():
	# Path to RAPL energy counter
	path = "/sys/class/powercap/intel-rapl:0/energy_uj"

	try:
		with open(path, "r") as f:
			energy_uj = int(f.read().strip())

		t = time.time()

		# First call: we don't have a previous sample yet
		if get_cpu_power.last_energy is None or get_cpu_power.last_time is None:
			get_cpu_power.last_energy = energy_uj
			get_cpu_power.last_time = t
			return None

		# Compute power in watts: Δenergy (J) / Δtime (s)
		delta_e = energy_uj - get_cpu_power.last_energy  # microjoules
		delta_t = t - get_cpu_power.last_time
		if delta_t <= 0:
			return None

		get_cpu_power.last_energy = energy_uj
		get_cpu_power.last_time = t

		power_w = (delta_e / 1e6) / delta_t
		return power_w

	except (FileNotFoundError, PermissionError, ValueError, OSError):
		# Can't read it (unsupported, wrong CPU, or no permission)
		return None

# initialise function attributes
get_cpu_power.last_energy = None
get_cpu_power.last_time = None

# Disk mount to observe
DISK_PATH = "/"

def main():
	period = 5.0

	with psycopg.connect(DB_DSN) as conn:
		with conn.cursor() as cur:
			# initial network counters
			prev = psutil.net_io_counters()
			prev_time = time.time()

			# align first run to the next 5s boundary
			next_target = math.floor(prev_time / period) * period + period

			while True:
				now = time.time()

				# sleep until the next 5s boundary
				if now < next_target:
					time.sleep(next_target - now)
					now = time.time()

				# round down to nearest 5s slot for the timestamp
				slot = math.floor(now / period) * period
				ts_ms = int(slot * 1000)

				# CPU, RAM, disk
				cpu = psutil.cpu_percent(interval=None)
				ram = psutil.virtual_memory().percent
				disk = psutil.disk_usage(DISK_PATH).percent

				# CPU temp & power
				temp = get_cpu_temp()
				pwr = get_cpu_power()

				# Network (bytes/sec)
				net = psutil.net_io_counters()
				elapsed = now - prev_time
				if elapsed <= 0:
					elapsed = 1.0

				up_bps = (net.bytes_sent - prev.bytes_sent) / elapsed
				dn_bps = (net.bytes_recv - prev.bytes_recv) / elapsed
				prev, prev_time = net, now

				# Insert
				cur.execute(
					"""
					INSERT INTO server_metrics
					(ts, cpu_used, ram_used, disk_used, cpu_temp, pwr_used, net_up, net_dn)
					VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
					ON CONFLICT (ts) DO NOTHING;
					""",
					(ts_ms, cpu, ram, disk, temp, pwr, up_bps, dn_bps)
				)
				conn.commit()
		
				print(f"TIMESTAMP: {ts_ms} | CPU: {cpu:.1f}% | RAM: {ram:.1f}% | DISK: {disk:.1f}% | TEMP: {temp is None and 'N/A' or f'{temp:.1f}°C'} | PWR: {pwr is None and 'N/A' or f'{pwr:.1f}W'} | UP: {up_bps:.1f} B/s | DN: {dn_bps:.1f} B/s", flush=True)

				# schedule next target
				next_target += period

				# if we slipped and are already past next_target, jump to the next valid slot
				if next_target <= now:
					next_target = math.floor(now / period) * period + period

if __name__ == "__main__":
	main()
