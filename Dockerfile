FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PARAVIEW_DIR=/opt/paraview

RUN apt-get update && apt-get install -y \
    wget \
    libgl1 \
    libegl1 \
    libxrender1 \
    libxext6 \
    libsm6 \
    libxt6 \
    libxcursor1 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxcb1 \
    libxkbcommon0 \
    libfontconfig1 \
    libfreetype6 \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q https://www.paraview.org/files/v5.13/ParaView-5.13.3-MPI-Linux-Python3.10-x86_64.tar.gz \
    && tar -xzf ParaView-5.13.3-MPI-Linux-Python3.10-x86_64.tar.gz \
    && mv ParaView-5.13.3-MPI-Linux-Python3.10-x86_64 ${PARAVIEW_DIR} \
    && rm ParaView-5.13.3-MPI-Linux-Python3.10-x86_64.tar.gz

ENV PATH="${PARAVIEW_DIR}/bin:${PATH}"

#give python access to paraview packages
RUN cp -rn /opt/paraview/lib/python3.10/site-packages/* /usr/local/lib/python3.10/site-packages

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY src/paraview_mcp_server.py .
COPY src/paraview_manager.py .
COPY src/__init__.py .

# MCP servers over stdio need unbuffered output
ENV PYTHONUNBUFFERED=1

#ENV LD_LIBRARY_PATH=/opt/paraview/lib:${LD_LIBRARY_PATH}
ENV LD_LIBRARY_PATH=/opt/paraview/lib

# Verify
RUN python3 -c "import paraview.simple as pvs; print('ParaView Python OK')"

# The server reads from stdin and writes to stdout
CMD ["python3", "paraview_mcp_server.py", "--server", "host.docker.internal"]
