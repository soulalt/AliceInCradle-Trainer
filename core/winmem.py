# -*- coding: utf-8 -*-
"""Win32 进程内存读写封装（纯 ctypes，x64）。

只依赖 kernel32 / user32 的公开 API：
  OpenProcess / ReadProcessMemory / WriteProcessMemory
  VirtualQueryEx / VirtualProtectEx
  CreateToolhelp32Snapshot（进程与模块枚举）
"""

from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes
from dataclasses import dataclass

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------------------------------------------------------- 常量

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020

MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_FREE = 0x10000
MEM_PRIVATE = 0x20000
MEM_MAPPED = 0x40000
MEM_IMAGE = 0x1000000

PAGE_NOACCESS = 0x01
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE = 0x10
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
PAGE_GUARD = 0x100
PAGE_NOCACHE = 0x200

WRITABLE_PROTECTIONS = (
    PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY
)
READABLE_PROTECTIONS = WRITABLE_PROTECTIONS | PAGE_READONLY | PAGE_EXECUTE_READ | PAGE_EXECUTE

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PATH = 260

# ---------------------------------------------------------------- 原型声明

k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenProcess.restype = ctypes.c_void_p
k32.CloseHandle.argtypes = [ctypes.c_void_p]
k32.CloseHandle.restype = wintypes.BOOL

k32.ReadProcessMemory.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]
k32.ReadProcessMemory.restype = wintypes.BOOL

k32.WriteProcessMemory.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]
k32.WriteProcessMemory.restype = wintypes.BOOL

k32.VirtualQueryEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t

k32.VirtualProtectEx.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
]
k32.VirtualProtectEx.restype = wintypes.BOOL

k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p

k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
k32.Process32FirstW.restype = wintypes.BOOL
k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
k32.Process32NextW.restype = wintypes.BOOL

k32.Module32FirstW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
k32.Module32FirstW.restype = wintypes.BOOL
k32.Module32NextW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
k32.Module32NextW.restype = wintypes.BOOL

k32.IsWow64Process.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL)]
k32.IsWow64Process.restype = wintypes.BOOL

k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
k32.GetExitCodeProcess.restype = wintypes.BOOL

# ---------------------------------------------------------------- 结构体

MEMORY_BASIC_INFORMATION_SIZE = 48  # x64


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * MAX_PATH),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", ctypes.c_void_p),
        ("szModule", ctypes.c_wchar * 256),
        ("szExePath", ctypes.c_wchar * MAX_PATH),
    ]


# ---------------------------------------------------------------- 数据类

@dataclass(frozen=True)
class Region:
    base: int
    size: int

    @property
    def end(self) -> int:
        return self.base + self.size

    @property
    def mib(self) -> int:
        return self.size // (1024 * 1024)


@dataclass(frozen=True)
class Module:
    name: str
    base: int
    size: int
    path: str

    @property
    def end(self) -> int:
        return self.base + self.size


# ---------------------------------------------------------------- 进程枚举

def list_processes() -> list[tuple[int, str]]:
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, INVALID_HANDLE_VALUE):
        return []
    out: list[tuple[int, str]] = []
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.append((int(e.th32ProcessID), e.szExeFile))
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def find_pid_by_name(exe_name: str) -> int | None:
    target = exe_name.lower()
    for pid, name in list_processes():
        if name.lower() == target:
            return pid
    return None


def process_ready(pid: int, min_writable: int = 80 << 20) -> bool:
    """目标进程是不是已经「铺开」了（可以附加了）。

    刚启动的游戏进程地址空间几乎是空的：模块枚举为 0、可写内存几乎为 0。
    这时候附加进去，扫描会一无所获 —— 新手会以为是工具坏了。
    判据取「可写内存总量达到阈值」或「已经加载 Mono 运行时」，
    两者任一成立即认为游戏已经进入可玩状态。
    """
    proc = Process(pid)
    if not proc.open():
        return False
    try:
        if any("mono" in m.name.lower() for m in proc.modules()):
            return True
        return sum(r.size for r in proc.regions()) >= min_writable
    except OSError:
        return False
    finally:
        proc.close()


# ---------------------------------------------------------------- 主类

class Process:
    """打开目标进程后可进行读取/写入/区域枚举/模块枚举。"""

    def __init__(self, pid: int) -> None:
        self.pid = int(pid)
        self.handle: int | None = None
        self.last_error: str = ""
        self.is_64bit = True

    # -------------------------------------------------- 生命周期

    def open(self) -> bool:
        self.close()
        access = (
            PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION
            | PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE
        )
        h = k32.OpenProcess(access, False, self.pid)
        if not h:
            err = ctypes.get_last_error()
            self.last_error = (
                f"OpenProcess 失败（错误码 {err}）"
                + ("：拒绝访问，请尝试以管理员身份运行修改器。" if err == 5 else "")
            )
            return False
        self.handle = h
        try:
            wow = wintypes.BOOL()
            if k32.IsWow64Process(h, ctypes.byref(wow)):
                self.is_64bit = not bool(wow.value)
        except Exception:
            pass
        self.last_error = ""
        return True

    def close(self) -> None:
        if self.handle:
            k32.CloseHandle(self.handle)
            self.handle = None

    @property
    def opened(self) -> bool:
        return bool(self.handle)

    def alive(self) -> bool:
        if not self.handle:
            return False
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE

    def __enter__(self) -> "Process":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -------------------------------------------------- 读写

    def read(self, addr: int, size: int) -> bytes | None:
        if not self.handle or size <= 0:
            return None
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        ok = k32.ReadProcessMemory(
            self.handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)
        )
        if not ok or got.value != size:
            return None
        return buf.raw[: got.value]

    def write(self, addr: int, data: bytes) -> bool:
        """写入；若页面只读则临时改为可写，写完恢复原保护属性。"""
        if not self.handle or not data:
            return False
        size = len(data)
        buf = ctypes.create_string_buffer(data, size)
        written = ctypes.c_size_t(0)
        ok = k32.WriteProcessMemory(
            self.handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(written)
        )
        if ok and written.value == size:
            return True

        old = wintypes.DWORD(0)
        if not k32.VirtualProtectEx(
            self.handle, ctypes.c_void_p(addr), size, PAGE_READWRITE, ctypes.byref(old)
        ):
            return False
        try:
            written = ctypes.c_size_t(0)
            ok = k32.WriteProcessMemory(
                self.handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(written)
            )
            return bool(ok and written.value == size)
        finally:
            restored = wintypes.DWORD(0)
            k32.VirtualProtectEx(
                self.handle, ctypes.c_void_p(addr), size, old.value, ctypes.byref(restored)
            )

    def read_many(self, items: list[tuple[int, int]], max_span: int = 1 << 20) -> dict[int, bytes]:
        """批量读取 [(addr, size), ...]。按邻近关系聚簇，每簇一次 RPM 后切片。"""
        if not self.handle or not items:
            return {}
        result: dict[int, bytes] = {}
        uniq = sorted(set(items), key=lambda it: it[0])

        cluster: list[tuple[int, int]] = []
        span_start = 0
        span_end = 0

        def flush() -> None:
            if not cluster:
                return
            blob = self.read(span_start, span_end - span_start)
            if blob is None:
                for a, s in cluster:
                    one = self.read(a, s)
                    if one is not None:
                        result[a] = one
                return
            for a, s in cluster:
                off = a - span_start
                chunk = blob[off: off + s]
                if len(chunk) == s:
                    result[a] = chunk

        for addr, size in uniq:
            if not cluster:
                cluster = [(addr, size)]
                span_start, span_end = addr, addr + size
                continue
            if addr + size - span_start <= max_span:
                cluster.append((addr, size))
                span_end = max(span_end, addr + size)
            else:
                flush()
                cluster = [(addr, size)]
                span_start, span_end = addr, addr + size
        flush()
        return result

    # -------------------------------------------------- 容错读取

    READ_GRANULE = 0x1000     # 最小下探粒度：一页 4KB
    READ_BUDGET = 512         # 单个大块的额外读取次数上限（防病态区域拖慢扫描）
    READ_WINDOW = 1 << 23     # 单次下探的最大长度，与扫描块一致（8MB）

    def read_pieces(self, addr: int, size: int,
                    granule: int | None = None,
                    budget: int | None = None) -> list[tuple[int, bytes]]:
        """读取 [addr, addr+size)，返回 [(起始地址, 字节)] —— 只含真正读得到的部分。

        快路径是一次 RPM。若整块失败（区域快照过时、中间夹了不可读/刚释放的页等），
        就二分下探到 granule 粒度，**只丢读不到的那几页**，而不是整块 8MB 全部放弃。
        连续可读的部分会合并回一个片段，正常情况返回 1 个片段。
        """
        if size <= 0 or not self.handle:
            return []
        granule = granule or self.READ_GRANULE
        left = [self.READ_BUDGET if budget is None else budget]
        pieces: list[list] = []            # [起始地址, 已合并长度, [字节片段...]]

        def push(a: int, data: bytes) -> None:
            if pieces and pieces[-1][0] + pieces[-1][1] == a:
                pieces[-1][1] += len(data)
                pieces[-1][2].append(data)
            else:
                pieces.append([a, len(data), [data]])

        def walk(a: int, n: int) -> None:
            data = self.read(a, n)
            if data is not None:
                push(a, data)
                return
            if n <= granule or left[0] <= 0:
                return
            left[0] -= 1
            half = n // 2
            if half <= 0:
                return
            walk(a, half)
            walk(a + half, n - half)

        off = 0
        while off < size:
            n = min(self.READ_WINDOW, size - off)
            walk(addr + off, n)
            off += n

        return [(a, b"".join(bufs)) for a, _n, bufs in pieces]

    # -------------------------------------------------- 区域枚举

    def regions(
        self,
        include_readonly: bool = False,
        include_mapped: bool = False,
        max_address: int = 0x00007FFFFFFF0000,
    ) -> list[Region]:
        """返回可扫描的内存区域（已过滤保护属性与类型）。"""
        if not self.handle:
            return []
        allowed = READABLE_PROTECTIONS if include_readonly else WRITABLE_PROTECTIONS
        out: list[Region] = []
        addr = 0
        mbi = ctypes.create_string_buffer(MEMORY_BASIC_INFORMATION_SIZE)

        while addr < max_address:
            n = k32.VirtualQueryEx(
                self.handle, ctypes.c_void_p(addr), mbi, MEMORY_BASIC_INFORMATION_SIZE
            )
            if n != MEMORY_BASIC_INFORMATION_SIZE:
                # 32 位目标或查询失败：步进一页继续尝试
                addr += 0x1000
                if addr > max_address:
                    break
                continue

            raw = mbi.raw
            base = struct.unpack_from("<Q", raw, 0)[0]
            region_size = struct.unpack_from("<Q", raw, 24)[0]
            state = struct.unpack_from("<I", raw, 32)[0]
            protect = struct.unpack_from("<I", raw, 36)[0]
            mtype = struct.unpack_from("<I", raw, 40)[0]

            if region_size == 0:
                addr += 0x1000
                continue

            if state == MEM_COMMIT and not (protect & PAGE_GUARD) and not (protect & PAGE_NOACCESS):
                if (protect & 0xFF) & allowed:
                    if include_mapped or mtype != 0x40000:  # MEM_MAPPED
                        out.append(Region(base, region_size))

            nxt = base + region_size
            if nxt <= addr:
                nxt = addr + 0x1000
            addr = nxt

        return out

    # -------------------------------------------------- 模块枚举

    def modules(self) -> list[Module]:
        snap = k32.CreateToolhelp32Snapshot(
            TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, self.pid
        )
        if snap in (None, INVALID_HANDLE_VALUE):
            return []
        out: list[Module] = []
        try:
            e = MODULEENTRY32W()
            e.dwSize = ctypes.sizeof(MODULEENTRY32W)
            ok = k32.Module32FirstW(snap, ctypes.byref(e))
            while ok:
                out.append(
                    Module(
                        name=e.szModule,
                        base=int(e.modBaseAddr or 0),
                        size=int(e.modBaseSize),
                        path=e.szExePath,
                    )
                )
                ok = k32.Module32NextW(snap, ctypes.byref(e))
        finally:
            k32.CloseHandle(snap)
        out.sort(key=lambda m: m.base)
        return out

    def base_of(self, module_name: str) -> int | None:
        target = module_name.lower()
        for m in self.modules():
            if m.name.lower() == target:
                return m.base
        return None

    # -------------------------------------------------- 指针读取

    def read_ptr(self, addr: int) -> int | None:
        raw = self.read(addr, 8)
        if raw is None:
            return None
        return struct.unpack("<Q", raw)[0]
