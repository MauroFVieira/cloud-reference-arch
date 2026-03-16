FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    git curl wget unzip python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# .NET 8 SDK
RUN wget https://dot.net/v1/dotnet-install.sh -O /tmp/dotnet-install.sh \
    && chmod +x /tmp/dotnet-install.sh \
    && /tmp/dotnet-install.sh --channel 8.0 --install-dir /usr/local/dotnet \
    && ln -sf /usr/local/dotnet/dotnet /usr/local/bin/dotnet

# Terraform
RUN wget https://releases.hashicorp.com/terraform/1.14.7/terraform_1.14.7_linux_amd64.zip \
    && unzip terraform_1.14.7_linux_amd64.zip \
    && mv terraform /usr/local/bin/ \
    && rm terraform_1.14.7_linux_amd64.zip

# tflocal + AWS CLI
RUN pip install terraform-local --break-system-packages
RUN pip install langgraph langchain-core anthropic pydantic --break-system-packages
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && unzip /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/awscliv2.zip /tmp/aws

# Git identity for agent commits
RUN git config --global user.name "cloud-ref-agent" \
    && git config --global user.email "agent@cloud-ref.local" \
    && git config --global --add safe.directory /repo

RUN mkdir -p /home/user && chmod 777 /home/user
ENV HOME=/home/user

WORKDIR /repo