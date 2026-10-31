ARG FRIGATE_BASE_IMAGE=ghcr.io/blakeblackshear/frigate:stable
FROM ${FRIGATE_BASE_IMAGE}
COPY integrations/frigate/patch_probes.py /tmp/okam-patch-probes.py
RUN python3 /tmp/okam-patch-probes.py && rm /tmp/okam-patch-probes.py
