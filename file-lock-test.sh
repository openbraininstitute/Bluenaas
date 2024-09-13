#!/bin/bash

model_id="https://openbluebrain.com/api/nexus/v1/resources/bbp/mmb-point-neuron-framework-model/_/https:%2F%2Fbbp.epfl.ch%2Fdata%2Fbbp%2Fmmb-point-neuron-framework-model%2Feeeeac3c-6bf1-47ed-ab97-460668eba2d2"

token="eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJZVTEyTEoyNG1sRFRieURlWXgyaGU5RkQzbldkWlBSV2piSVVpa2hocVFVIn0.eyJleHAiOjE3MjYyMzY0NjEsImlhdCI6MTcyNjIzNTU2MSwiYXV0aF90aW1lIjoxNzI2MjEyNTAxLCJqdGkiOiI4NTIxNGM5Mi02MzJiLTRlOTEtYmRiMC1hNjhmOWM0NWI1MjEiLCJpc3MiOiJodHRwczovL29wZW5ibHVlYnJhaW4uY29tL2F1dGgvcmVhbG1zL1NCTyIsInN1YiI6IjA0Yzk2YjllLWMyOGYtNDMyNi1iOGM3LWNlMjI5YjY2MWM1MyIsInR5cCI6IkJlYXJlciIsImF6cCI6Im5leHVzLWRlbHRhIiwibm9uY2UiOiI0MGE2OWFjNDI1ZTU0MGZiODIxOTFmMjkzMTk4NmNmNyIsInNlc3Npb25fc3RhdGUiOiI5MmE4MTk0ZC1kYzhhLTRmY2EtYTM3Yi1mZjBhMGFkMTUzZGMiLCJzY29wZSI6Im9wZW5pZCBwcm9maWxlIGVtYWlsIiwic2lkIjoiOTJhODE5NGQtZGM4YS00ZmNhLWEzN2ItZmYwYTBhZDE1M2RjIiwiZW1haWxfdmVyaWZpZWQiOmZhbHNlLCJuYW1lIjoiRGluaWthIFNheGVuYSIsInByZWZlcnJlZF91c2VybmFtZSI6ImRpbmlrYSIsImdpdmVuX25hbWUiOiJEaW5pa2EiLCJmYW1pbHlfbmFtZSI6IlNheGVuYSIsImVtYWlsIjoiZGluaWthc2F4ZW5hc0BnbWFpbC5jb20ifQ.d-RMrB1nYnxwliJlbIvSLJKmpnbTkyK3aEA7Lls4vfQGauHURdaIDWHj59PpylCBDKJCn8CvecqfRcGJ1PU0mRVcS7ALUHuPUl1VgLPbSUMp_aPjYGbXnC8olQbZ8bqGRYC4Pos1Ax379_NcA_BGivFWWttizRq1NAz-TUwS_4wmm3QJm_wbsoxytG4ZrQ-l8i6AzdQmX6lUA7CUOUg4REKOSIJeTVJVDCcfKvndWa0FyrxP00rZ9bNzzNCQas_A2v8q6bVGeCA6gDKhejnHsqd2qRCaFaHtlqQ8umgkUoL_6fXhhdUvY8WnuwAGbukwlZEoy8BT8_fr0SrRFt5zog"

echo "SECOND REQUEST"
curl 'http://localhost:8001/morphology?model_id=https%3A%2F%2Fopenbluebrain.com%2Fapi%2Fnexus%2Fv1%2Fresources%2Fbbp%2Fmmb-point-neuron-framework-model%2F_%2Fhttps%3A%252F%252Fbbp.epfl.ch%252Fdata%252Fbbp%252Fmmb-point-neuron-framework-model%252Feeeeac3c-6bf1-47ed-ab97-460668eba2d2' --compressed \
    -H 'Accept: application/x-ndjson' \
    -H 'Accept-Language: en-GB,en;q=0.5' \
    -H 'Accept-Encoding: gzip, deflate, br' \
    -H 'Referer: http://localhost:3000/' \
    -H "authorization: Bearer $token" &

curl 'http://localhost:8001/morphology?model_id=https%3A%2F%2Fopenbluebrain.com%2Fapi%2Fnexus%2Fv1%2Fresources%2Fbbp%2Fmmb-point-neuron-framework-model%2F_%2Fhttps%3A%252F%252Fbbp.epfl.ch%252Fdata%252Fbbp%252Fmmb-point-neuron-framework-model%252Feeeeac3c-6bf1-47ed-ab97-460668eba2d2' --compressed \
    -H 'Accept: application/x-ndjson' \
    -H 'Accept-Language: en-GB,en;q=0.5' \
    -H 'Accept-Encoding: gzip, deflate, br' \
    -H 'Referer: http://localhost:3000/' \
    -H "authorization: Bearer $token"
