#!/usr/bin/env python3
"""
docker_mem_monitor_dual_ts.py
─────────────────────────────
1. 1 秒間隔で全コンテナの ps を取得
2. CSV へ  timestamp, elapsed_sec, container, pid, rss_kb, pmem, nlwp, cmdline
3. Ctrl-C で終了時にコンテナごと累積 RSS 上位 10 を表示
"""
import subprocess, time, csv, datetime, signal, sys, shutil
from collections import Counter, defaultdict

INTERVAL = 1.0
TOPN     = 10
CSV_FILE = "docker_mem_log.csv"

usage   = Counter()
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
         'ps --help 2>&1 | grep -q \"BusyBox\"'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0

# --- CSV 初期化 ---
csv_fh = open(CSV_FILE, "a", newline="")
csv_writer = csv.writer(csv_fh)
if csv_fh.tell() == 0:
    csv_writer.writerow([
        "timestamp", "elapsed_sec", "container", "pid",
        "rss_kb", "pmem", "nlwp", "cmdline"
    ])

t0 = time.time()          # 計測開始基準

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

        for ln in out.strip().splitlines()[1:]:
            parts = ln.split(None, 5)
            if len(parts) < 3:
                continue
            if len(parts) == 4:                      # BusyBox
                pid, rss, comm, args = parts
                pmem = 0.0
                nlwp = 0
            else:                                    # procps
                pid, rss, pmem, nlwp, comm, args = parts
            key = (cn, pid, args)
            rss_kb = int(rss)
            usage[key]  += rss_kb
            mempct[key]+= float(pmem)
            threads[key]= int(nlwp)

            # --- CSV 出力 ---
            csv_writer.writerow([
                now_iso, elapsed, cn, pid, rss_kb,
                pmem, nlwp, args
            ])
    csv_fh.flush()

def summary():
    width = shutil.get_terminal_size((140, 20)).columns
    sep = "-" * width
    per_c = defaultdict(list)
    for (cn, pid, args), total in usage.items():
        per_c[cn].append((total, pid, args))
    for cn in sorted(per_c):
        print(f"\n\033[1m[{cn}]\033[0m")
        print(f"{'PID':<8} {'ΣRSS[MiB]':>12} {'Σ%MEM':>8} {'NLWP':>5}  CMDLINE")
        print(sep)
        for total, pid, args in sorted(
                per_c[cn], key=lambda x: x[0], reverse=True)[:TOPN]:
            rss_mb = total / 1024
            pmem   = mempct[(cn, pid, args)]
            nlwp   = threads[(cn, pid, args)]
            print(f"{pid:<8} {rss_mb:>12.1f} {pmem:>8.1f} {nlwp:>5}  {args}")
        print(sep)

def main():
    print("[INFO] 1 秒間隔で計測開始… (Ctrl-C で終了)")
    try:
        while True:
            t_start = time.time()
            sample()
            time.sleep(max(0, INTERVAL - (time.time() - t_start)))
    except KeyboardInterrupt:
        pass
    finally:
        csv_fh.close()
        summary()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    main()