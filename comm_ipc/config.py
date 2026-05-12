import getpass
import os


def resolve_comm_ipc_path():
    if env_path := os.getenv("COMM_IPC_SOCKET"):
        return env_path

    runtime_dir = os.getenv("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        return os.path.join(runtime_dir, "comm-ipc.default.sock")

    user = getpass.getuser()
    return os.path.join("/tmp", f"comm-ipc.{user}.sock")


SOCKET_PATH = resolve_comm_ipc_path()
DEFAULT_IDLE_TIMEOUT = 60.0
DEFAULT_DATA_TIMEOUT = 60.0
DEFAULT_HEARTBEAT_INTERVAL = 30.0
