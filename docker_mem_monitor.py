#!/usr/bin/env python3
# docker_mem_monitor_detail.py
"""
INTERVAL 秒ごとに各コンテナの ps を実行し
PID 単位で RSS(kB) を累積する。
終了時にコンテナごと累積 RSS 上位 TOPN プロセスを
PID / RSS / %MEM / NLWP / CMDLINE 付きで表示。
"""

import subprocess, time, shutil, signal, sys
from collections import Counter, defaultdict

INTERVAL = 2.0   # [s]
TOPN     = 10    # 各コンテナで出力する件数

usage = Counter()                 # {(cname,pid,cmd): Σrss}
threads = defaultdict(int)        # {(cname,pid,cmd): nlwp}
mem_pct = defaultdict(float)      # {(cname,pid,cmd): Σ%mem}

def running_cids():
    out = subprocess.check_output(["docker", "ps", "-q"], text=True)
    return out.split() if out.strip() else []

def cname(cid):
    return subprocess.check_output(
        ["docker", "inspect", "-f", "{{.Name}}", cid], text=True
    ).strip().lstrip("/")

def is_busybox(cid):
    return subprocess.call(
        ["docker", "exec", cid, "sh", "-c",
         'ps --help 2>&1 | grep -q "BusyBox"'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ) == 0

def sample():
    """1 回分の ps 出力を取得して累積"""
    for cid in running_cids():
        cname_ = cname(cid)
        if is_busybox(cid):
            # BusyBox: nlwp と %mem が取れないので 0 を入れる
            cmd = ["docker", "exec", cid, "ps", "-o", "pid,rss,comm,args"]
            header_skip = 1
        else:
            cmd = ["docker", "exec", cid,
                   "ps", "-eo", "pid,rss,pmem,nlwp,comm,args", "--no-headers"]
            header_skip = 0
        try:
            out = subprocess.check_output(cmd, text=True)
        except subprocess.CalledProcessError:
            continue
        lines = out.strip().splitlines()[header_skip:]
        for line in lines:
            parts = line.split(None, 5)   # PID  RSS  %MEM  NLWP  COMM  ARGS
            if len(parts) < 3:            # BusyBox fallback
                continue
            if len(parts) == 4:           # BusyBox : pid rss comm args
                pid, rss, comm, args = parts
                pmem = 0.0
                nlwp = 0
            else:
                pid, rss, pmem, nlwp, comm, args = parts
            key = (cname_, pid, args)
            usage[key]  += int(rss)
            threads[key] = int(nlwp)
            mem_pct[key]+= float(pmem)

def print_result():
    w = shutil.get_terminal_size((140, 20)).columns
    sep = "-" * w
    per_container = defaultdict(list)
    for (cname_, pid, args), total in usage.items():
        per_container[cname_].append((total, pid, args))

    for cname_ in sorted(per_container):
        print(f"\n\033[1m[{cname_}]\033[0m")
        print(f"{'PID':<8} {'ΣRSS[MiB]':>12} {'Σ%MEM':>8} {'NLWP':>5}  CMDLINE")
        print(sep)
        for total, pid, args in sorted(
                per_container[cname_], key=lambda x: x[0], reverse=True)[:TOPN]:
            rss_mb = total / 1024
            pmem   = mem_pct.get((cname_, pid, args), 0.0)
            nlwp   = threads.get((cname_, pid, args), 0)
            print(f"{pid:<8} {rss_mb:>12.1f} {pmem:>8.1f} {nlwp:>5}  {args}")
        print(sep)

def main():
    print(f"[INFO] {INTERVAL:.1f}s 間隔で計測開始… (Ctrl-C で終了し集計表示)")
    try:
        while True:
            t0 = time.time()
            sample()
            time.sleep(max(0, INTERVAL - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        print_result()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    main()