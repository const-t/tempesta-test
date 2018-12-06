#!/bin/sh

# Copyright (C) 2018 Tempesta Technologies, Inc.
# License: GPL2

echo "Checking Framework"
./check_framework.sh
FW=$?

if [ "$FW" != "0" ]
then
    echo "Framework doesn't have required dependencies. Exiting."
    exit 1
fi

echo "Framework ok. Proceeding to nodes dependencies check."

echo "Check commands on nodes"
./check_cmds_nodes.py
NODES=$?

if [ "$NODES" != "0" ]
then
    echo "Node(s) don't have required dependencies. Exiting."
    exit 1
fi

echo "Check files on nodes"
./check_files_nodes.py
NODES=$?

if [ "$NODES" != "0" ]
then
    echo "Node(s) don't have required files. Exiting."
    exit 1
fi

echo "Nodes ok."

echo "Check successed."

exit 0