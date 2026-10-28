import platform

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

# nrnivmodl compiles into a directory named after the machine architecture.
MECHANISMS_DIR_NAME = platform.machine()
LIBNRNMECH_PATH = f"{MECHANISMS_DIR_NAME}/lib/nrnmech.so"

READY_MARKER_FILE_NAME = ".ready"
# Contents written into READY_MARKER_FILE_NAME. Bump when what an initialized
# directory contains changes, so entries initialized by an older version are
# re-fetched and re-compiled instead of keeping the old build.
READY_MARKER_VERSION = "2"
DIR_LOCK_FILE_NAME = ".dir-lock"
