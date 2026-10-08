"""Read Linux statistics without requiring privileges or third-party packages."""
from pathlib import Path
import os
import platform
import shutil
import socket


def memory():
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        values[key] = int(value.split()[0]) * 1024
    total = values['MemTotal']
    return total, total - values.get('MemAvailable', values['MemFree'])


class CpuSampler:
    def __init__(self):
        self.previous = None

    def sample(self):
        ticks = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
        current = (sum(ticks), ticks[3] + ticks[4])
        result = 0.0
        if self.previous:
            delta = current[0] - self.previous[0]
            if delta:
                result = 100 * (1 - (current[1] - self.previous[1]) / delta)
        self.previous = current
        return max(0.0, min(100.0, result))


def information():
    total, used = memory()
    disk = shutil.disk_usage('/')
    seconds = int(float(Path('/proc/uptime').read_text().split()[0]))
    model = next((line.split(':', 1)[1].strip() for line in
                  Path('/proc/cpuinfo').read_text().splitlines()
                  if line.startswith('model name')), platform.machine())
    interfaces = []
    for device in sorted(Path('/sys/class/net').iterdir()):
        try:
            interfaces.append(f'{device.name}: { (device / "operstate").read_text().strip()}')
        except OSError:
            pass
    return [f'Hostname: {socket.gethostname()}', f'Kernel: {platform.release()}',
            f'CPU: {model}', f'Memory: {used // 1048576} / {total // 1048576} MiB',
            f'Root disk: {disk.used // 1073741824} / {disk.total // 1073741824} GiB',
            f'Uptime: {seconds // 3600}h {seconds % 3600 // 60}m',
            'Load: ' + ' '.join(f'{v:.2f}' for v in os.getloadavg()),
            'Network: ' + ', '.join(interfaces)]
