#!/usr/bin/env python3
import subprocess, time, csv, datetime, signal, sys, shutil
from collections import defaultdict
import re

INTERVAL = 1.0
TOPN     = 10
CSV_FILE = "docker_mem_log.csv"

_UNIT_FACTORS_KB = {
    'kb': 1, 'kib': 1,
    'mb': 1024, 'mib': 1024,
    'gb': 1024 * 1024, 'gib': 1024 * 1024,
}
def _to_kb(val):
    """
    Convert strings like '12345', '2048kB', '12MB', '1.5GiB' to kB.
    Default unit is kB when omitted.
    """
    if isinstance(val, (int, float)):
        return float(val)
    m = re.match(r'([\d.]+)\s*([KMG]i?B?)?', str(val).strip(), re.I)
    if not m:
        return 0.0
    num  = float(m.group(1))
    unit = (m.group(2) or 'kB').lower().rstrip('b') + 'b'
    return num * _UNIT_FACTORS_KB.get(unit, 1)

usage   = defaultdict(int)  # track peak RSS per process (kB)
threads = defaultdict(int)
mempct  = defaultdict(float)

def running_cids():
    out = subprocess.check_output(["docker", "ps", "-q"], text=True)
    return out.split() if out.strip() else []

def cname(cid):
    return subprocess.check_output(
        ["docker", "inspect", "-f", "{{.Name}}", cid], text=True
    ).strip().lstrip("/")

def busybox(cid):
    return subprocess.call(
        ["docker", "exec", cid, "sh", "-c",
         'ps --help 2>&1 | grep -q "BusyBox"'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0

# CSV 初期化
csv_fh = open(CSV_FILE, "a", newline="")
writer = csv.writer(csv_fh)
if csv_fh.tell() == 0:
    writer.writerow(["timestamp", "elapsed_sec", "container", "pid",
                     "rss_kb", "pmem", "nlwp", "cmdline"])

t0 = time.time()

def sample():
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    elapsed = round(time.time() - t0, 1)

    for cid in running_cids():
        cn = cname(cid)
        cmd = (["docker", "exec", cid, "ps", "-o", "pid,rss,comm,args"]
               if busybox(cid) else
               ["docker", "exec", cid,
                "ps", "-eo", "pid,rss,pmem,nlwp,comm,args", "--no-headers"])
        try:
            out = subprocess.check_output(cmd, text=True)
        except subprocess.CalledProcessError:
            continue

        lines = out.strip().splitlines()
        if lines and lines[0].lstrip().lower().startswith("pid"):
            lines = lines[1:]  # drop header if present
        for ln in lines:
            parts = ln.split(None, 4)            # 最大 5 つ
            if len(parts) < 3:
                continue
            pid, rss = parts[0], parts[1]
            pmem = 0.0
            nlwp = 0
            cmdline = parts[-1]

            if len(parts) == 5:                  # procps 形式想定
                try:
                    pmem = float(parts[2])
                    nlwp = int(parts[3])
                except ValueError:
                    cmdline = " ".join(parts[2:])  # BusyBox の誤検出パターン

            rss_kb = _to_kb(rss)
            if rss_kb <= 0:
                continue
            key = (cn, pid, cmdline)
            usage[key]  = max(usage.get(key, 0), rss_kb)  # peak value
            mempct[key] = pmem
            threads[key] = nlwp

            writer.writerow([now_iso, elapsed, cn, pid,
                             rss_kb, pmem, nlwp, cmdline])
    csv_fh.flush()

def summary():
    w = shutil.get_terminal_size((140, 20)).columns
    sep = "-" * w
    per_c = defaultdict(list)
    for (cn, pid, cmd), total in usage.items():
        per_c[cn].append((total, pid, cmd))
    for cn in sorted(per_c):
        print(f"\n\033[1m[{cn}]\033[0m")
        print(f"{'PID':<8} {'PeakRSS[GiB]':>12} {'%MEM':>8} {'NLWP':>5}  CMDLINE")      
        print(sep)
        for tot, pid, cmd in sorted(per_c[cn],
                                    key=lambda x: x[0], reverse=True)[:TOPN]:
            print(f"{pid:<8} {tot/1048576:>12.2f} "
                f"{mempct[(cn,pid,cmd)]:>8.1f} {threads[(cn,pid,cmd)]:>5}  {cmd}")
        print(sep)

def main():
    print("[INFO] 1 秒間隔で計測開始… (Ctrl-C で終了)")
    try:
        while True:
            t = time.time()
            sample()
            time.sleep(max(0, INTERVAL - (time.time() - t)))
    except KeyboardInterrupt:
        pass
    finally:
        csv_fh.close()
        summary()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    main()