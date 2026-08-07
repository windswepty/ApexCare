import ctypes
from ctypes import wintypes
import sys

ntdll = ctypes.WinDLL('ntdll', use_last_error=True)
advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

kernel32.GetCurrentProcess.restype = wintypes.HANDLE
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.OpenProcessToken.restype = wintypes.BOOL
advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
advapi32.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL

class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD),
                ("HighPart", wintypes.LONG)]

class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID),
                ("Attributes", wintypes.DWORD)]

class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD),
                ("Privileges", LUID_AND_ATTRIBUTES * 1)]

def enable_privilege(priv_name):
    hToken = wintypes.HANDLE()
    TOKEN_ADJUST_PRIVILEGES = 0x0020
    TOKEN_QUERY = 0x0008
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(hToken)):
        print(f"Failed to open process token for {priv_name}: {ctypes.get_last_error()}")
        return False
        
    luid = LUID()
    if not advapi32.LookupPrivilegeValueW(None, priv_name, ctypes.byref(luid)):
        print(f"Failed to lookup privilege {priv_name}: {ctypes.get_last_error()}")
        kernel32.CloseHandle(hToken)
        return False
        
    tp = TOKEN_PRIVILEGES()
    tp.PrivilegeCount = 1
    tp.Privileges[0].Luid = luid
    tp.Privileges[0].Attributes = 0x00000002 # SE_PRIVILEGE_ENABLED
    
    advapi32.AdjustTokenPrivileges(hToken, False, ctypes.byref(tp), ctypes.sizeof(tp), None, None)
    err = ctypes.get_last_error()
    kernel32.CloseHandle(hToken)
    
    if err == 1300: # ERROR_NOT_ALL_ASSIGNED
        print(f"Privilege {priv_name} not held by caller.")
        return False
    elif err != 0:
        print(f"AdjustTokenPrivileges failed for {priv_name}: {err}")
        return False
        
    return True

def purge_standby_list():
    if not enable_privilege("SeProfileSingleProcessPrivilege"):
        print("Failed to enable SeProfileSingleProcessPrivilege.")
    else:
        print("SeProfileSingleProcessPrivilege enabled.")
        
    command = ctypes.c_int(4) # MemoryPurgeStandbyList
    SystemMemoryListInformation = 80
    
    status = ntdll.NtSetSystemInformation(SystemMemoryListInformation, ctypes.byref(command), ctypes.sizeof(command))
    print(f"NtSetSystemInformation PurgeStandbyList status: {hex(status & 0xffffffff)}")

def flush_file_cache():
    if not enable_privilege("SeIncreaseQuotaPrivilege"):
        print("Failed to enable SeIncreaseQuotaPrivilege.")
    else:
        print("SeIncreaseQuotaPrivilege enabled.")
        
    # SetSystemFileCacheSize(-1, -1, 0)
    kernel32.SetSystemFileCacheSize.argtypes = [ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
    res = kernel32.SetSystemFileCacheSize(ctypes.c_size_t(-1), ctypes.c_size_t(-1), 0)
    if res:
        print("SetSystemFileCacheSize Success!")
    else:
        print(f"SetSystemFileCacheSize Failed! Error: {ctypes.get_last_error()}")

if __name__ == '__main__':
    flush_file_cache()
    purge_standby_list()
