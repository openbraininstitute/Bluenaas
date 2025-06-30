import subprocess


def clear_cache():
    """Remove cached models"""

    subprocess.run("rm -r /opt/blue-naas/models/*")
