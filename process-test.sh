#!/bin/bash

urls=(
    "https%3A%2F%2Fsbo-nexus-delta.shapes-registry.org%2Fv1%2Fresources%2Fbbp%2Fmmb-point-neuron-framework-model%2F_%2Fhttps%3A%252F%252Fbbp.epfl.ch%252Fdata%252Fbbp%252Fmmb-point-neuron-framework-model%252Feeeeac3c-6bf1-47ed-ab97-460668eba2d2"
    "https%3A%2F%2Fsbo-nexus-delta.shapes-registry.org%2Fv1%2Fresources%2Fbbp%2Fmmb-point-neuron-framework-model%2F_%2Fhttps%3A%252F%252Fbbp.epfl.ch%252Fdata%252Fbbp%252Fmmb-point-neuron-framework-model%252Ffc98f29b-a608-44d2-b9c4-8f4b6dbfee8d"
    "https%3A%2F%2Fsbo-nexus-delta.shapes-registry.org%2Fv1%2Fresources%2Fbbp%2Fmmb-point-neuron-framework-model%2F_%2Fhttps%3A%252F%252Fbbp.epfl.ch%252Fdata%252Fbbp%252Fmmb-point-neuron-framework-model%252F1e16e488-c4c5-4d44-80f2-82c9e6795422"
  # ... more URLs
)

max_parallel_jobs=5  # Adjust as needed
authorization_header="Bearer xxx"

# Function to send a POST request
send_request() {
  url="$1"
  echo "Sending request to: $url"
  curl -X POST \
    "http://localhost:8001/simulation/run?model_id=$url" \
    -H "accept: application/json" \
    -H "Authorization: $authorization_header" \
    -H "Content-Type: application/json" \
    -d '{
      "celsius": 34,
      "hypamp": 0,
      "vinit": -73,
      "injectTo": "soma[0]",
      "recordFrom": [
        "soma[0]_0"
      ],
      "stimulus": {
        "stimulusType": "current_clamp",
        "stimulusProtocol": "iv",
        "paramValues": {
          "stop_time": 3500
        },
        "amplitudes": [
          40,
          80,
          120
        ]
      },
      "section_name": null
    }'
}

# Iterate over URLs and send requests
for url in "${urls[@]}"; do
  send_request "$url" &
done
