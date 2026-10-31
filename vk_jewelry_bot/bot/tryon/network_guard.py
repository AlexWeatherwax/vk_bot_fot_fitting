"""Fail-closed Linux worker isolation, before any native inference import."""
import ctypes, errno, os, socket, sys

def deny_network():
    if sys.platform != "linux":
        raise RuntimeError("Offline inference requires Linux/libseccomp; use Docker on macOS or Windows")
    os.environ['ORT_DISABLE_TELEMETRY']='1'
    lib=ctypes.CDLL('libseccomp.so.2',use_errno=True)
    lib.seccomp_init.argtypes=[ctypes.c_uint32];lib.seccomp_init.restype=ctypes.c_void_p
    lib.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint]
    lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];lib.seccomp_syscall_resolve_name.restype=ctypes.c_int
    lib.seccomp_load.argtypes=[ctypes.c_void_p];lib.seccomp_release.argtypes=[ctypes.c_void_p]
    ctx=lib.seccomp_init(0x7fff0000)
    if not ctx:raise RuntimeError('Cannot create network-deny filter')
    try:
     for name in ['socket','socketpair','connect','sendto','sendmsg','sendmmsg','io_uring_setup','io_uring_enter','io_uring_register']:
      nr=lib.seccomp_syscall_resolve_name(name.encode())
      if nr>=0 and lib.seccomp_rule_add(ctx,0x00050000|errno.EPERM,nr,0)!=0:raise RuntimeError('Cannot block '+name)
     if lib.seccomp_load(ctx)!=0:raise RuntimeError('Cannot enforce network denial')
    finally:lib.seccomp_release(ctx)
    try:
     socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    except PermissionError:
     pass
    else:raise RuntimeError('Networking was not blocked; refusing inference')
