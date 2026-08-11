# openEMS runner image for antenna-cad.
#
# Builds openEMS (FDTD solver) with its Python bindings from a pinned commit of the
# openEMS-Project super-repo. antenna-cad writes a simulation spec + standalone runner
# script into a run directory and executes it in this container:
#
#   docker build -t antenna-cad-openems docker/
#   docker run --rm -v "$RUN_DIR":/sim antenna-cad-openems /sim/run_openems.py /sim/spec.json
#
# The runner script depends only on numpy/h5py and the openEMS bindings, never on
# antenna-cad itself, so this image does not change when the package does.

FROM ubuntu:24.04

# Pinned openEMS-Project master (Aug 2026). The last release tag predates the current
# Python API; master is what upstream documents and supports.
ARG OPENEMS_COMMIT=84703e254dafe84ed2f06056e5f105067b8f1910

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git ca-certificates \
    libhdf5-dev libvtk9-dev libboost-all-dev libcgal-dev libtinyxml-dev \
    qtbase5-dev libvtk9-qt-dev \
    python3 python3-dev python3-pip python3-venv \
    python3-numpy python3-h5py cython3 \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/thliebig/openEMS-Project.git /opt/openEMS-Project \
    && cd /opt/openEMS-Project \
    && git checkout "$OPENEMS_COMMIT" \
    && git submodule update --init --recursive

RUN cd /opt/openEMS-Project && ./update_openEMS.sh /opt/openEMS --python

# update_openEMS.sh --python installs the CSXCAD/openEMS bindings into this venv.
ENV PATH=/opt/openEMS/venv/bin:/opt/openEMS/bin:$PATH

WORKDIR /sim
ENTRYPOINT ["/opt/openEMS/venv/bin/python"]
