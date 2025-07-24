#!/bin/bash

mpiexec -n 4 python \
  /app/app/core/circuit/simulation-mpi-entrypoint.py \
  --config /app/storage/circuit/simulation/1/3/2fd858-39b1-46c2-af54-72571f102bc7/simulation_config.json \
  --execution_id 132fd858-39b1-46c2-af54-72571f102bc7 \
  --libnrnmech_path /app/storage/circuit/model/a/4/5d8644-9cf0-416d-859b-c763b584c28e/x86_64/.libs/libnrnmech.so \
  --save-nwb
