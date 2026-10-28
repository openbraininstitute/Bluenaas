CID_LENGTH = 8
NULL_CID = "-" * CID_LENGTH

STOP_MESSAGE = b"__STOP__"

SERVICE_NAME = "small-scale-simulator"

CIRCUIT_MOD_DIR = "mod"
CIRCUIT_MEMODEL_MOD_DIR = "mechanisms"  # TODO To be replaced with CIRCUIT_MOD_DIR
CIRCUIT_SIMULATION_CONFIG_NAME = "simulation_config.json"
CIRCUIT_CONFIG_NAME = "circuit_config.json"

SINGLE_NEURON_MOD_DIR = "mechanisms"
SINGLE_NEURON_HOC_DIR = "hoc"
SINGLE_NEURON_MORPHOLOGY_DIR = "morphology"

MECHANISMS_DIR_NAME = "x86_64"
LIBNRNMECH_PATH = f"{MECHANISMS_DIR_NAME}/lib/nrnmech.so"

READY_MARKER_FILE_NAME = ".ready"
DIR_LOCK_FILE_NAME = ".dir-lock"

# Retired cache epochs are first moved here (inside the storage root, so that the move stays on
# one filesystem and is atomic) and deleted from there.
STORAGE_TRASH_DIR_NAME = ".trash"

# Written into a retired cache epoch: when it was retired and which jobs might still be using it
RETIRED_MARKER_FILE_NAME = ".retired"

# The longest a job may run, except the cache cleanups. A retired cache epoch is deleted after this
# much time, if not earlier, so no job may run longer.
MAX_JOB_TIMEOUT = 60 * 60

# Time limit of a cache cleanup job
CACHE_CLEANUP_TIMEOUT = 2 * 60 * 60

# How long the lock of a cache cleanup is kept without being renewed. A cleanup that is running
# renews it, one that was killed holds up the next ones until it expires.
CACHE_CLEANUP_LOCK_TTL = 5 * 60

# A reclaim that keeps finding retired epochs that are still in use gives up after this many checks
CACHE_RECLAIM_MAX_ATTEMPTS = 30
