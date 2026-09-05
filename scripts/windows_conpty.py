"""Minimal native Windows ConPTY transport, no PyFluent. Author: Manuel Sun."""
from __future__ import annotations
import os, ctypes, subprocess

class ConPTY:
    def __init__(self, argv, cwd):
        if os.name != 'nt': raise OSError('ConPTY requires Windows 10 1809 or later')
        from ctypes import wintypes as w
        self.k = k = ctypes.WinDLL('kernel32', use_last_error=True)
        class COORD(ctypes.Structure): _fields_ = [('X', ctypes.c_short), ('Y', ctypes.c_short)]
        class SI(ctypes.Structure):
            _fields_ = [('cb', w.DWORD), ('lpReserved', w.LPWSTR), ('lpDesktop', w.LPWSTR), ('lpTitle', w.LPWSTR),
                        ('dwX', w.DWORD), ('dwY', w.DWORD), ('dwXSize', w.DWORD), ('dwYSize', w.DWORD),
                        ('dwXCountChars', w.DWORD), ('dwYCountChars', w.DWORD), ('dwFillAttribute', w.DWORD),
                        ('dwFlags', w.DWORD), ('wShowWindow', w.WORD), ('cbReserved2', w.WORD),
                        ('lpReserved2', ctypes.c_void_p), ('hStdInput', w.HANDLE), ('hStdOutput', w.HANDLE), ('hStdError', w.HANDLE)]
        class SIX(ctypes.Structure): _fields_ = [('StartupInfo', SI), ('lpAttributeList', ctypes.c_void_p)]
        class PI(ctypes.Structure): _fields_ = [('hProcess', w.HANDLE), ('hThread', w.HANDLE), ('dwProcessId', w.DWORD), ('dwThreadId', w.DWORD)]
        k.CreatePipe.argtypes = [ctypes.POINTER(w.HANDLE), ctypes.POINTER(w.HANDLE), ctypes.c_void_p, w.DWORD]
        k.CreatePseudoConsole.argtypes = [COORD, w.HANDLE, w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
        k.CreatePseudoConsole.restype = ctypes.c_long
        k.ClosePseudoConsole.argtypes = [w.HANDLE]
        k.CloseHandle.argtypes = [w.HANDLE]
        k.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)]
        k.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, w.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
        k.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
        k.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD, ctypes.c_void_p, w.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(PI)]
        k.ReadFile.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
        k.WriteFile.argtypes = k.ReadFile.argtypes
        k.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        self._handles = []
        self.hpc = w.HANDLE()
        self.pi = PI()
        self.closed = False
        rin, win, rout, wout = w.HANDLE(), w.HANDLE(), w.HANDLE(), w.HANDLE()
        try:
            for a, b in [(rin, win), (rout, wout)]:
                if not k.CreatePipe(ctypes.byref(a), ctypes.byref(b), None, 0): raise ctypes.WinError(ctypes.get_last_error())
                self._handles.extend([a, b])
            hr = k.CreatePseudoConsole(COORD(180, 50), rin, wout, 0, ctypes.byref(self.hpc))
            if hr < 0: raise OSError(f'CreatePseudoConsole HRESULT {hr:#x}')
            self.reader, self.writer = rout, win
            size = ctypes.c_size_t()
            k.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            attrs = ctypes.create_string_buffer(size.value)
            if not k.InitializeProcThreadAttributeList(attrs, 1, 0, ctypes.byref(size)): raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not k.UpdateProcThreadAttribute(attrs, 0, 0x00020016, self.hpc, ctypes.sizeof(w.HANDLE), None, None): raise ctypes.WinError(ctypes.get_last_error())
                si = SIX(); si.StartupInfo.cb = ctypes.sizeof(si); si.lpAttributeList = ctypes.cast(attrs, ctypes.c_void_p)
                si.StartupInfo.dwFlags = 1; si.StartupInfo.wShowWindow = 0
                line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
                if not k.CreateProcessW(None, line, None, None, False, 0x00080000, None, str(cwd), ctypes.byref(si), ctypes.byref(self.pi)): raise ctypes.WinError(ctypes.get_last_error())
            finally: k.DeleteProcThreadAttributeList(attrs)
            self.pid = self.pi.dwProcessId
            k.CloseHandle(self.pi.hThread)
            for h in (rin, wout):
                k.CloseHandle(h); self._handles.remove(h)
        except Exception:
            self.close(); raise

    def read(self):
        from ctypes import wintypes as w
        buf, n = ctypes.create_string_buffer(8192), w.DWORD()
        if not self.k.ReadFile(self.reader, buf, len(buf), ctypes.byref(n), None): return b''
        return buf.raw[:n.value]

    def write(self, data):
        from ctypes import wintypes as w
        n = w.DWORD()
        if not self.k.WriteFile(self.writer, data, len(data), ctypes.byref(n), None): raise ctypes.WinError(ctypes.get_last_error())
        if n.value != len(data): raise OSError('Partial ConPTY write')

    def poll(self):
        from ctypes import wintypes as w
        code = w.DWORD()
        if not self.k.GetExitCodeProcess(self.pi.hProcess, ctypes.byref(code)): return -1
        return None if code.value == 259 else code.value

    def close(self):
        if self.closed: return
        self.closed = True
        if self.hpc: self.k.ClosePseudoConsole(self.hpc)
        for h in self._handles: self.k.CloseHandle(h)
        self._handles.clear()
        if self.pi.hProcess: self.k.CloseHandle(self.pi.hProcess)
