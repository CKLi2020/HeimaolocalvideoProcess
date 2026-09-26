import subprocess


HIDDEN_SUBPROCESS = {
    "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
}
