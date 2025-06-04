from neuron import h  # For MPI parallel context
from loguru import logger


def main():
    logger.info("Init")

    pc = h.ParallelContext()

    logger.info("ParallelContext created")

    rank = int(pc.id())
    logger.info(f"Rank {rank}: ParallelContext initialized")

    nhost = int(pc.nhost())
    logger.info(f"Rank {rank}: Number of hosts: {nhost}")


if __name__ == "__main__":
    main()
