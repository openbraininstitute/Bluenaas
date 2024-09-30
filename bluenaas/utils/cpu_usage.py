import psutil

def get_cpus_in_use():
    cpu_usage_percent = psutil.cpu_percent(interval=1)
    total_cpus = psutil.cpu_count()
    cpus_in_use = (cpu_usage_percent / 100) * total_cpus
    return {
        "cpus_in_use": round(cpus_in_use),
        "total_cpus": total_cpus,
        "cpu_usage_percent": cpu_usage_percent,
    }